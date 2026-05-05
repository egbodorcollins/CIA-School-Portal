from io import BytesIO
from datetime import timedelta

from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.db import transaction
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from .decorators import class_teacher_or_admin_required, teacher_or_admin_required, admin_required
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.utils import timezone
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import (
    Student,
    Grade,
    BehavioralGrade,
    TermSetting,
    Profile,
    Activity,
    Subject,
    ClassPromotionRequest,
    TERM_CHOICES,
    TERM_MAP,
)
from django.db.models import Avg, Count, Q
from .forms import (
    StudentSignUpForm,
    GradeEntryForm,
    BehavioralGradeEntryForm,
    TeacherCreationForm,
    enroll_student_in_standard_subjects,
    get_class_code,
)
from .subject_map import CLASS_PROGRESSION
from django.forms import HiddenInput


def _user_can_approve_promotions(user, profile=None):
    return (
        (profile and profile.role == Profile.ROLE_ADMIN)
        or user.is_superuser
        or getattr(user, 'is_staff', False)
    )


TERM_ORDER = {'first_term': 1, 'second_term': 2, 'third_term': 3, 'session': 4}


def _term_display(term):
    return dict(TERM_CHOICES).get(term, term.replace('_', ' ').title())


def _current_period():
    return TermSetting.get_current_period()


def _student_result_period(student, requested_year=None, requested_term=None):
    grade_periods = Grade.objects.filter(student=student).values_list('academic_year', 'term')
    behavior_periods = BehavioralGrade.objects.filter(student=student).values_list('academic_year', 'term')
    periods = sorted(
        set(grade_periods).union(set(behavior_periods)),
        key=lambda item: (item[0], TERM_ORDER.get(item[1], 0)),
        reverse=True,
    )

    requested_year_periods = [period for period in periods if period[0] == requested_year]

    if periods and (requested_year, requested_term) in periods:
        selected_year, selected_term = requested_year, requested_term
    elif requested_year_periods:
        selected_year, selected_term = requested_year_periods[0]
    elif periods:
        selected_year, selected_term = periods[0]
    else:
        selected_year, selected_term = _current_period()

    academic_year_options = sorted({year for year, _term in periods} or {selected_year}, reverse=True)
    term_options = [
        {
            'value': term,
            'label': _term_display(term),
        }
        for year, term in periods
        if year == selected_year
    ]
    if not term_options:
        term_options = [{'value': selected_term, 'label': _term_display(selected_term)}]

    return selected_year, selected_term, academic_year_options, term_options


class RateLimitedLoginView(LoginView):
    template_name = 'grades/login.html'
    redirect_authenticated_user = True

    # @ratelimit(key='ip', rate='5/m', method='POST')  # Disabled for development
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


def home(request):
    recent_activities = Activity.objects.none()
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        # Admin / staff see everything
        if request.user.is_superuser or getattr(request.user, 'is_staff', False) or (profile and profile.role == Profile.ROLE_ADMIN):
            recent_activities = Activity.objects.select_related('actor', 'target_student', 'target_subject').all()[:40]
        elif profile and profile.role == Profile.ROLE_CLASS_TEACHER:
            # Activities for students in the class or activities on subjects assigned to the teacher
            assigned_subjects = profile.assigned_subjects.all()
            recent_activities = Activity.objects.filter(
                Q(target_student__class_name=profile.assigned_class) |
                Q(target_subject__in=assigned_subjects)
            ).select_related('actor', 'target_student', 'target_subject').distinct()[:40]
        elif profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            assigned_subjects = profile.assigned_subjects.all()
            recent_activities = Activity.objects.filter(
                Q(target_subject__in=assigned_subjects) |
                Q(target_student__subjects__in=assigned_subjects)
            ).select_related('actor', 'target_student', 'target_subject').distinct()[:40]
        elif profile and profile.role == Profile.ROLE_STUDENT:
            try:
                student = Student.objects.get(student_id=request.user.username)
                recent_activities = Activity.objects.filter(target_student=student).select_related('actor', 'target_student', 'target_subject')[:40]
            except Student.DoesNotExist:
                recent_activities = Activity.objects.none()

    return render(request, 'grades/home.html', {
        'recent_activities': recent_activities,
    })


@login_required
@class_teacher_or_admin_required
def register_student(request):
    profile = getattr(request.user, 'profile', None)

    if request.method == 'POST':
        form = StudentSignUpForm(request.POST, user=request.user)
        if form.is_valid():
            # If the current user is a class teacher, ensure they can only register
            # students for their assigned class.
            if profile and profile.role == Profile.ROLE_CLASS_TEACHER:
                chosen_class = form.cleaned_data.get('class_name')
                if chosen_class != profile.assigned_class:
                    form.add_error('class_name', 'You may only register students for your assigned class.')
                else:
                    with transaction.atomic():
                        new_user = form.save()
                    # Log registration activity
                    try:
                        student_obj = Student.objects.filter(student_id=new_user.username).first()
                        Activity.objects.create(
                            actor=request.user,
                            action_type=Activity.ACTION_STUDENT_REGISTERED,
                            target_student=student_obj,
                            description=f"{request.user.get_full_name() or request.user.username} registered student {student_obj if student_obj else new_user.username}",
                        )
                    except Exception as e:
                        print(f"Error logging student registration activity: {e}")
                        pass
                    messages.success(
                        request,
                        f'Student profile created successfully. Login ID: {new_user.username}. Password: CIA@123456.'
                    )
                    return redirect('teacher_dashboard')
            else:
                with transaction.atomic():
                    new_user = form.save()
                # Log registration activity
                try:
                    student_obj = Student.objects.filter(student_id=new_user.username).first()
                    Activity.objects.create(
                        actor=request.user,
                        action_type=Activity.ACTION_STUDENT_REGISTERED,
                        target_student=student_obj,
                        description=f"{request.user.get_full_name() or request.user.username} registered student {student_obj if student_obj else new_user.username}",
                    )
                except Exception as e:
                    print(f"Error logging student registration activity: {e}")
                    pass
                messages.success(
                    request,
                    f'Student profile created successfully. Login ID: {new_user.username}. Password: CIA@123456.'
                )
                return redirect('teacher_dashboard')
    else:
        form = StudentSignUpForm(user=request.user)

    return render(request, 'grades/register_student.html', {
        'form': form,
        'user_profile': profile,
    })


@login_required
@class_teacher_or_admin_required
def register_teacher(request):
    profile = getattr(request.user, 'profile', None)

    # Ensure profile exists for admin/staff to prevent "Unable to determine role" errors
    if profile is None and (request.user.is_superuser or request.user.is_staff):
        profile, _ = Profile.objects.get_or_create(
            user=request.user, 
            defaults={'role': Profile.ROLE_ADMIN if request.user.is_superuser else Profile.ROLE_CLASS_TEACHER}
        )

    if profile is None:
        messages.error(request, 'Unable to determine your role. Contact admin.')
        return redirect('teacher_dashboard')

    if profile.role == Profile.ROLE_ADMIN or request.user.is_superuser:
        allowed_roles = [r[0] for r in Profile.ROLE_CHOICES if r[0] != Profile.ROLE_STUDENT]
    elif profile.role == Profile.ROLE_CLASS_TEACHER:
        allowed_roles = [Profile.ROLE_SUBJECT_TEACHER]
    else:
        messages.error(request, 'You do not have permission to create teacher accounts.')
        return redirect('teacher_dashboard')

    if request.method == 'POST':
        form = TeacherCreationForm(request.POST)
        # limit role choices to allowed_roles
        form.fields['role'].choices = [c for c in Profile.ROLE_CHOICES if c[0] in allowed_roles]
        if profile.role == Profile.ROLE_CLASS_TEACHER:
            form.fields['assigned_class'].initial = profile.assigned_class

        if form.is_valid():
            chosen_role = form.cleaned_data.get('role')
            if chosen_role not in allowed_roles:
                messages.error(request, 'Invalid role selected.')
                return redirect('register_teacher')
            
            with transaction.atomic():
                user = form.save()
                
                # Strict enforcement for Class Teachers
                if profile.role == Profile.ROLE_CLASS_TEACHER:
                    user.profile.assigned_class = profile.assigned_class
                    user.profile.save()

            # Log teacher/admin creation
            try:
                Activity.objects.create(
                    actor=request.user,
                    action_type=Activity.ACTION_TEACHER_REGISTERED,
                    description=f"{request.user.get_full_name() or request.user.username} created account {user.username} with role {dict(Profile.ROLE_CHOICES).get(chosen_role)}",
                )
            except Exception as e:
                print(f"Error logging teacher registration activity: {e}")
                pass

            messages.success(request, f'{dict(Profile.ROLE_CHOICES).get(chosen_role, chosen_role)} account created for {user.username}.')
            return redirect('teacher_dashboard')
    else:
        form = TeacherCreationForm()
        form.fields['role'].choices = [c for c in Profile.ROLE_CHOICES if c[0] in allowed_roles]
        if profile.role == Profile.ROLE_CLASS_TEACHER:
            form.fields['assigned_class'].initial = profile.assigned_class

    return render(request, 'grades/register_teacher.html', {
        'form': form,
    })


def logout_view(request):
    logout(request)
    request.session.flush()
    messages.success(request, 'You have successfully logged out.')
    return redirect('home')


@login_required
def teacher_dashboard(request):
    profile = getattr(request.user, 'profile', None)

    if profile is None:
        messages.warning(request, 'Teacher access only. Please sign in with a teacher account.')
        return redirect('student_dashboard')
        if request.user.is_superuser or request.user.is_staff:
            profile, _ = Profile.objects.get_or_create(
                user=request.user, 
                defaults={'role': Profile.ROLE_ADMIN if request.user.is_superuser else Profile.ROLE_CLASS_TEACHER}
            )
        else:
            messages.warning(request, 'Teacher access only. Please sign in with a teacher account.')
            return redirect('student_dashboard')

    if profile and profile.role == 'student':
        # If the user is marked as staff/superuser, treat them as a teacher
        # for dashboard access and update their profile role for consistency.
        if request.user.is_superuser or getattr(request.user, 'is_staff', False):
            try:
                profile.role = Profile.ROLE_ADMIN if request.user.is_superuser else Profile.ROLE_CLASS_TEACHER
                profile.save()
            except Exception:
                pass
        else:
            messages.warning(request, 'Teacher access only. Please sign in with a teacher account.')
            return redirect('student_dashboard')

    # Guard against profile still being None after a failed get_or_create
    if not profile:
        messages.error(request, 'Could not load your staff profile. Please contact the administrator.')
        return redirect('home')

    if profile.role == 'admin':
        students = Student.objects.all().order_by('last_name')
    elif profile.role == 'class_teacher':
        students = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    elif profile.role == 'subject_teacher':
        assigned_subjects = profile.assigned_subjects.all()
        students = Student.objects.filter(grades__subject__in=assigned_subjects).distinct().order_by('last_name')
    else:
        students = Student.objects.none()

    form = StudentSignUpForm(user=request.user)
    return render(request, 'grades/teacher_dashboard.html', {
        'students': students,
        'form': form,
        'can_request_promotion': profile.role == Profile.ROLE_CLASS_TEACHER or _user_can_approve_promotions(request.user, profile),
    })


@login_required
@teacher_or_admin_required
def class_analytics(request):
    profile = getattr(request.user, 'profile', None)
    current_academic_year, current_term = _current_period()
    term_labels = dict(TERM_CHOICES)
    academic_terms = [term for term, _label in TERM_CHOICES if term != 'session']
    if current_term not in academic_terms:
        academic_terms.append(current_term)

    if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        class_options = [profile.assigned_class]
        selected_class = profile.assigned_class
    elif profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
        assigned_subjects = profile.assigned_subjects.all()
        class_options = list(
            Student.objects.filter(
                Q(subjects__in=assigned_subjects) | Q(grades__subject__in=assigned_subjects)
            )
            .exclude(class_name__isnull=True)
            .exclude(class_name='')
            .order_by('class_name')
            .values_list('class_name', flat=True)
            .distinct()
        )
        selected_class = request.GET.get('class') or (class_options[0] if class_options else '')
    else:
        class_options = list(
            Student.objects.exclude(class_name__isnull=True)
            .exclude(class_name='')
            .order_by('class_name')
            .values_list('class_name', flat=True)
            .distinct()
        )
        selected_class = request.GET.get('class') or (class_options[0] if class_options else '')

    if selected_class not in class_options and class_options:
        selected_class = class_options[0]

    class_grades = Grade.objects.filter(student__class_name=selected_class).select_related('student', 'subject')
    current_grades = class_grades.filter(academic_year=current_academic_year, term=current_term)

    subject_averages = list(
        current_grades.values('subject__name', 'subject__code')
        .annotate(average=Avg('marks'), entries=Count('id'))
        .order_by('subject__name')
    )

    raw_distribution = dict(
        current_grades.values('letter_grade').annotate(total=Count('id')).values_list('letter_grade', 'total')
    )
    max_grade_count = max(raw_distribution.values(), default=0)
    grade_distribution = []
    for index, letter in enumerate(['A', 'B', 'C', 'D', 'E', 'F']):
        count = raw_distribution.get(letter, 0)
        height = round((count / max_grade_count) * 140, 1) if max_grade_count else 0
        x = 36 + (index * 52)
        y = 150 - height
        grade_distribution.append({
            'letter': letter,
            'count': count,
            'height': height,
            'x': x,
            'label_x': x + 17,
            'y': y,
            'count_y': max(14, y - 8),
        })

    ranked_students = list(
        current_grades.values('student__student_id', 'student__first_name', 'student__last_name')
        .annotate(average=Avg('marks'), entries=Count('id'))
        .order_by('-average', 'student__last_name', 'student__first_name')
    )
    top_students = ranked_students[:5]
    bottom_students = sorted(
        ranked_students,
        key=lambda row: (row['average'] if row['average'] is not None else 0, row['student__last_name'], row['student__first_name'])
    )[:5]

    term_averages = []
    raw_term_averages = {
        row['term']: row
        for row in class_grades.filter(term__in=academic_terms)
        .filter(academic_year=current_academic_year)
        .values('term')
        .annotate(average=Avg('marks'), entries=Count('id'))
    }
    current_average = raw_term_averages.get(current_term, {}).get('average')
    for term in academic_terms:
        row = raw_term_averages.get(term, {})
        average = row.get('average')
        delta = None
        if average is not None and current_average is not None and term != current_term:
            delta = current_average - average
        term_averages.append({
            'term': term,
            'label': term_labels.get(term, term.replace('_', ' ').title()),
            'average': average,
            'entries': row.get('entries', 0),
            'is_current': term == current_term,
            'delta_from_current': delta,
        })

    return render(request, 'grades/class_analytics.html', {
        'class_options': class_options,
        'selected_class': selected_class,
        'current_term': current_term,
        'current_term_display': term_labels.get(current_term, current_term.replace('_', ' ').title()),
        'current_academic_year': current_academic_year,
        'subject_averages': subject_averages,
        'grade_distribution': grade_distribution,
        'top_students': top_students,
        'bottom_students': bottom_students,
        'term_averages': term_averages,
        'total_grade_entries': current_grades.count(),
        'student_count': Student.objects.filter(class_name=selected_class).count() if selected_class else 0,
    })


@login_required
@admin_required
def set_current_term(request):
    messages.info(request, 'Current academic term is managed in the Django admin dashboard.')
    return redirect('admin:grades_termsetting_changelist')


@login_required
@teacher_or_admin_required
def enter_academic_scores(request):
    current_academic_year, current_term = _current_period()
    profile = getattr(request.user, 'profile', None)

    # Prepare students available for selection based on user's role
    if profile and profile.role == Profile.ROLE_ADMIN:
        students_for_select = Student.objects.all().order_by('last_name')
    elif profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        students_for_select = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    elif profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
        students_for_select = Student.objects.filter(subjects__in=profile.assigned_subjects.all()).distinct().order_by('last_name')
    else:
        students_for_select = Student.objects.none()

    selected_student = None
    sel_student_pk = request.GET.get('student')
    if sel_student_pk:
        try:
            selected_student = students_for_select.get(pk=sel_student_pk)
        except Exception:
            selected_student = None

    if request.method == 'POST':
        form = GradeEntryForm(request.POST)

        # Restrict student/subject querysets based on role
        if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            form.fields['subject'].queryset = profile.assigned_subjects.all()

        # If a student was pre-selected, lock the student field
        if selected_student:
            form.fields['student'].queryset = Student.objects.filter(pk=selected_student.pk)

        if form.is_valid():
            data = form.cleaned_data
            grade, created = Grade.objects.update_or_create(
                student=data['student'],
                subject=data['subject'],
                academic_year=current_academic_year,
                term=current_term,
                defaults={
                    'homework': data.get('homework', 0),
                    'class_work': data.get('class_work', 0),
                    'project': data.get('project', 0),
                    'first_test': data.get('first_test', 0),
                    'midterm_test': data.get('midterm_test', 0),
                    'exam': data.get('exam', 0),
                    'remarks': data.get('remarks', ''),
                }
            )
            # Log activity
            try:
                Activity.objects.create(
                    actor=request.user,
                    action_type=Activity.ACTION_GRADE_CREATED if created else Activity.ACTION_GRADE_UPDATED,
                    target_student=grade.student,
                    target_subject=grade.subject,
                    description=f"{request.user.get_full_name() or request.user.username} {'created' if created else 'updated'} grade for {grade.student} in {grade.subject}: {grade.marks} ({grade.letter_grade})",
                )
            except Exception:
                pass
            messages.success(request, 'Academic score saved successfully.')
            if selected_student:
                return redirect(f"{request.path}?student={selected_student.pk}")
            return redirect('enter_academic_scores')
    else:
        form = GradeEntryForm()
        if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            form.fields['subject'].queryset = profile.assigned_subjects.all()

        if selected_student:
            # Lock and hide the student field
            form.fields['student'].queryset = Student.objects.filter(pk=selected_student.pk)
            form.fields['student'].initial = selected_student.pk
            form.fields['student'].widget = HiddenInput()

            # Restrict subjects to the student's enrolled subjects for the current term
            try:
                term_map = {'first_term': '1', 'second_term': '2', 'third_term': '3'}
                term_digit = term_map.get(current_term, '1')
                class_code = get_class_code(selected_student.class_name)
                if class_code:
                    subj_qs = selected_student.subjects.filter(code__endswith=f"{class_code}{term_digit}")
                else:
                    subj_qs = selected_student.subjects.all()

                if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
                    subj_qs = subj_qs.filter(pk__in=profile.assigned_subjects.all())

                form.fields['subject'].queryset = subj_qs
            except Exception:
                form.fields['subject'].queryset = selected_student.subjects.all()

    # Show only selected student's grades when a student is selected
    if selected_student:
        grades = Grade.objects.filter(academic_year=current_academic_year, term=current_term, student=selected_student).select_related('student', 'subject').order_by('subject__name')
    else:
        grades = Grade.objects.filter(academic_year=current_academic_year, term=current_term).select_related('student', 'subject').order_by('student__last_name', 'subject__name')
        if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
            grades = grades.filter(student__class_name=profile.assigned_class)
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            grades = grades.filter(subject__in=profile.assigned_subjects.all())

    return render(request, 'grades/enter_academic_scores.html', {
        'form': form,
        'grades': grades,
        'current_term': current_term,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
        'students': students_for_select,
        'selected_student': selected_student,
    })


@login_required
@class_teacher_or_admin_required
def enter_behavioral_assessments(request):
    current_academic_year, current_term = _current_period()
    profile = getattr(request.user, 'profile', None)

    if request.method == 'POST':
        form = BehavioralGradeEntryForm(request.POST)
        if profile and profile.role == 'class_teacher' and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)

        if form.is_valid():
            data = form.cleaned_data
            bg, created = BehavioralGrade.objects.update_or_create(
                student=data['student'],
                academic_year=current_academic_year,
                term=current_term,
                defaults={
                    'punctuality': data['punctuality'],
                    'relationship_with_staff': data['relationship_with_staff'],
                    'politeness': data['politeness'],
                    'neatness': data['neatness'],
                    'co_operation': data['co_operation'],
                    'obedience': data['obedience'],
                    'attentiveness': data['attentiveness'],
                    'adjustment_in_school': data['adjustment_in_school'],
                    'relationship_with_peers': data['relationship_with_peers'],
                    'times_present': data['times_present'],
                    'remarks': data['remarks'],
                }
            )
            try:
                Activity.objects.create(
                    actor=request.user,
                    action_type=Activity.ACTION_BEHAVIORAL_CREATED if created else Activity.ACTION_BEHAVIORAL_UPDATED,
                    target_student=bg.student,
                    description=f"{request.user.get_full_name() or request.user.username} {'created' if created else 'updated'} behavioral assessment for {bg.student} (term: {bg.term})",
                )
            except Exception:
                pass
            messages.success(request, 'Behavioral assessment saved successfully.')
            return redirect('enter_behavioral_assessments')
    else:
        form = BehavioralGradeEntryForm()
        if profile and profile.role == 'class_teacher' and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)

    reports = BehavioralGrade.objects.filter(academic_year=current_academic_year, term=current_term).select_related('student').order_by('student__last_name')
    if profile and profile.role == 'class_teacher' and profile.assigned_class:
        reports = reports.filter(student__class_name=profile.assigned_class)

    return render(request, 'grades/enter_behavioral_assessments.html', {
        'form': form,
        'reports': reports,
        'current_term': current_term,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
    })


@login_required
@class_teacher_or_admin_required
def manage_students(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'class_teacher' and profile.assigned_class:
        students = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    else:
        students = Student.objects.all().order_by('last_name')

    can_approve_promotions = _user_can_approve_promotions(request.user, profile)

    # Build promotion_students: a list of {student, to_class, preselected}
    # for the inline per-student checkbox table.
    promotion_students = []
    promotion_from_class = None

    if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        from_class = profile.assigned_class
        to_class = CLASS_PROGRESSION.get(from_class)
        if to_class:
            promotion_from_class = from_class
            for s in Student.objects.filter(class_name=from_class).order_by('last_name', 'first_name'):
                promotion_students.append({
                    'student': s,
                    'to_class': to_class,
                    'preselected': True,   # default: all ticked, teacher unticks failures
                })
    elif can_approve_promotions:
        # Admins see every class that has students and a next class configured.
        # We don't pre-populate a single from_class here; instead we show all
        # classes grouped. For simplicity, show all promotable students across
        # all classes with their destination, still using a single form.
        # The from_class is derived from each student's class_name on submit.
        #
        # However, the form only supports one from_class per submission, so we
        # redirect admins to the per-class selector instead of a flat list.
        # Build promotion_options for the dropdown (kept for admin use).
        pass
 
    # Promotion options dropdown (used only when promotion_students is empty,
    # i.e. for admin users who select a class first).
    promotion_options = []
    if can_approve_promotions and not promotion_students:
        for from_class, to_class in CLASS_PROGRESSION.items():
            count = Student.objects.filter(class_name=from_class).count()
            if count:
                promotion_options.append({
                    'from_class': from_class,
                    'to_class': to_class,
                    'count': count,
                })
 
    pending_promotion_requests = ClassPromotionRequest.objects.filter(
        status=ClassPromotionRequest.STATUS_PENDING
    ).select_related('requested_by')
    if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        pending_promotion_requests = pending_promotion_requests.filter(from_class=profile.assigned_class)
 
    return render(request, 'grades/manage_students.html', {
        'students': students,
        'promotion_students': promotion_students,
        'promotion_from_class': promotion_from_class,
        'promotion_options': promotion_options,
        'pending_promotion_requests': pending_promotion_requests,
        'can_approve_promotions': can_approve_promotions,
    })
 


@login_required
@admin_required
@require_POST
def delete_student(request, student_id):
    student = Student.objects.filter(student_id=student_id).first()
    if student:
        student.delete()
        messages.success(request, 'Student has been removed from the portal.')
    else:
        messages.error(request, 'Student not found.')
    return redirect('manage_students')


@login_required
@class_teacher_or_admin_required
@require_POST
def promote_class(request):
    profile = getattr(request.user, 'profile', None)
    can_approve_promotions = _user_can_approve_promotions(request.user, profile)
 
    from_class = request.POST.get('from_class', '').strip()
    confirmed  = request.POST.get('confirm') == 'yes'
    # Collect the individually-checked student PKs (may be empty if none ticked)
    raw_pks = request.POST.getlist('student_pks')
 
    if not confirmed:
        messages.error(request, 'Please tick the confirmation checkbox before submitting.')
        return redirect('manage_students')
 
    to_class = CLASS_PROGRESSION.get(from_class)
    if not to_class:
        messages.error(request, 'The selected class does not have a configured next class.')
        return redirect('manage_students')
 
    # Class teachers may only request promotion for their own assigned class.
    if (
        profile
        and profile.role == Profile.ROLE_CLASS_TEACHER
        and not can_approve_promotions
        and from_class != profile.assigned_class
    ):
        messages.error(request, 'You may only request promotion for your assigned class.')
        return redirect('manage_students')
 
    # Parse and validate the student PKs
    try:
        student_pks = [int(pk) for pk in raw_pks if str(pk).isdigit()]
    except (ValueError, TypeError):
        student_pks = []
 
    if not student_pks:
        messages.error(request, 'Please select at least one student to promote.')
        return redirect('manage_students')
 
    # Confirm all selected PKs actually belong to from_class (security check)
    valid_students = Student.objects.filter(pk__in=student_pks, class_name=from_class)
    if valid_students.count() != len(student_pks):
        messages.error(request, 'One or more selected students do not belong to the specified class.')
        return redirect('manage_students')
 
    # Prevent duplicate pending requests for the same class
    existing_request = ClassPromotionRequest.objects.filter(
        from_class=from_class,
        status=ClassPromotionRequest.STATUS_PENDING,
    ).first()
    if existing_request:
        messages.info(request, f'A promotion request for {from_class} is already pending admin approval.')
        return redirect('manage_students')
 
    ClassPromotionRequest.objects.create(
        from_class=from_class,
        to_class=to_class,
        requested_by=request.user,
        student_count=len(student_pks),
        student_pks=student_pks,
    )
    messages.success(
        request,
        f'Promotion request submitted for {len(student_pks)} student(s) from {from_class} to {to_class}. '
        f'An admin must approve it before students are moved.'
    )
    return redirect('manage_students')


@login_required
@admin_required
@require_POST
def approve_class_promotion(request, request_id):
    promotion_request = ClassPromotionRequest.objects.filter(pk=request_id).first()
    if not promotion_request:
        messages.error(request, 'Promotion request not found.')
        return redirect('manage_students')
 
    if promotion_request.status != ClassPromotionRequest.STATUS_PENDING:
        messages.info(request, 'This promotion request has already been reviewed.')
        return redirect('manage_students')
 
    from_class = promotion_request.from_class
    to_class   = promotion_request.to_class
    student_pks = promotion_request.student_pks or []
 
    with transaction.atomic():
        promotion_request = ClassPromotionRequest.objects.select_for_update().get(pk=promotion_request.pk)
        if promotion_request.status != ClassPromotionRequest.STATUS_PENDING:
            messages.info(request, 'This promotion request has already been reviewed.')
            return redirect('manage_students')
 
        if student_pks:
            # Promote only the individually-selected students
            students = list(
                Student.objects.select_for_update()
                .filter(pk__in=student_pks, class_name=from_class)
                .order_by('last_name', 'first_name')
            )
        else:
            # Legacy path: older requests that stored no individual PKs
            students = list(
                Student.objects.select_for_update()
                .filter(class_name=from_class)
                .order_by('last_name', 'first_name')
            )
 
        for student in students:
            student.class_name = to_class
            student.save(update_fields=['class_name'])
            enroll_student_in_standard_subjects(student, to_class, clear_existing=True)
 
        promotion_request.status       = ClassPromotionRequest.STATUS_APPROVED
        promotion_request.approved_by  = request.user
        promotion_request.reviewed_at  = timezone.now()
        promotion_request.student_count = len(students)
        promotion_request.save(update_fields=['status', 'approved_by', 'reviewed_at', 'student_count'])
 
    if students:
        messages.success(
            request,
            f'Approved and promoted {len(students)} student(s) from {from_class} to {to_class}.'
        )
    else:
        messages.info(request, f'Approved the request, but no matching students were found in {from_class}.')

    return redirect('manage_students')


@login_required
def student_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role != 'student':
        return redirect('teacher_dashboard')

    student = None
    grades = []
    behavioral_grades = []
    selected_academic_year = request.GET.get('academic_year')
    selected_term = request.GET.get('term')
    academic_year_options = []
    term_options = []
    try:
        student = Student.objects.get(student_id=request.user.username)
        selected_academic_year, selected_term, academic_year_options, term_options = _student_result_period(
            student,
            selected_academic_year,
            selected_term,
        )
        grades = Grade.objects.filter(
            student=student,
            academic_year=selected_academic_year,
            term=selected_term,
        ).select_related('subject').order_by('subject__name')
        behavioral_grades = BehavioralGrade.objects.filter(
            student=student,
            academic_year=selected_academic_year,
            term=selected_term,
        ).order_by('-term')
    except Student.DoesNotExist:
        messages.info(request, 'No student profile was found for your username. Please contact administration.')

    return render(request, 'grades/student_dashboard.html', {
        'student': student,
        'grades': grades,
        'behavioral_grades': behavioral_grades,
        'selected_academic_year': selected_academic_year,
        'selected_term': selected_term,
        'selected_term_display': _term_display(selected_term) if selected_term else '',
        'academic_year_options': academic_year_options,
        'term_options': term_options,
    })


@login_required
def report_card_pdf(request):
    student = None
    try:
        student = Student.objects.get(student_id=request.user.username)
    except Student.DoesNotExist:
        messages.error(request, 'Unable to generate report: student profile not found.')
        return redirect('student_dashboard')

    selected_academic_year, selected_term, _year_options, _term_options = _student_result_period(
        student,
        request.GET.get('academic_year'),
        request.GET.get('term'),
    )
    term_display = _term_display(selected_term)
    selected_grades = list(
        Grade.objects.filter(
            student=student,
            academic_year=selected_academic_year,
            term=selected_term,
        ).select_related('subject').order_by('subject__name')
    )
    selected_behavior = BehavioralGrade.objects.filter(
        student=student,
        academic_year=selected_academic_year,
        term=selected_term,
    ).first()

    class_students = Student.objects.filter(class_name=student.class_name)
    class_count = class_students.count()

    def average_score_for_student(student_obj):
        student_grades = Grade.objects.filter(
            student=student_obj,
            academic_year=selected_academic_year,
            term=selected_term,
        )
        if not student_grades:
            return 0
        return sum(g.marks for g in student_grades) / len(student_grades)

    average_score = average_score_for_student(student)
    highest_average = 0
    for classmate in class_students:
        highest_average = max(highest_average, average_score_for_student(classmate))

    response = HttpResponse(content_type='application/pdf')
    # Keep the download filename filesystem-friendly because student IDs contain slashes.
    safe_student_id = student.student_id.replace('/', '-')
    safe_year = selected_academic_year.replace('/', '-')
    response['Content-Disposition'] = f'attachment; filename="{safe_student_id}_{safe_year}_{selected_term}_report.pdf"'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    styles = getSampleStyleSheet()
    heading = Paragraph('CORINAISA INTERNATIONAL ACADEMY', ParagraphStyle('Title', parent=styles['Title'], alignment=1, fontSize=18, leading=22, spaceAfter=10))
    subtitle = Paragraph(f'<b>{selected_academic_year} {term_display.upper()} REPORT</b>', ParagraphStyle('Subtitle', parent=styles['Heading2'], alignment=1, fontSize=14, textColor=colors.red, spaceAfter=14))

    next_term_begin = timezone.now().date() + timedelta(days=90)
    header_data = [
        ['CLASS', student.class_name or 'Not assigned', 'GRADE IN CLASS', 'A'],
        ['NAME', f'{student.first_name} {student.last_name}', 'AVERAGE SCORE', f'{average_score:.2f}'],
        ['NATIONALITY', student.nationality or 'N/A', 'HIGHEST AVERAGE IN CLASS', f'{highest_average:.2f}'],
        ['STATE OF ORIGIN', student.state_of_origin or 'N/A', 'NO. OF TIMES SCHOOL OPENED', '112'],
        ['CLUB/SOCIETY', student.club_and_society or 'N/A', 'NEXT TERM BEGIN', next_term_begin.strftime('%d %b, %Y')],
        ['NO. OF CHILDREN IN CLASS', str(class_count), 'NO. OF TIMES PRESENT', str(selected_behavior.times_present if selected_behavior else 0)],
    ]

    info_table = Table(header_data, colWidths=[90, 160, 140, 120])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBEFORE', (2, 0), (2, -1), 1, colors.black),
    ]))

    assessment_data = [['SUBJECT', 'HW', 'CW', 'PRJ', 'T1', 'MID', 'EXAM', 'TOTAL', 'GRADE', 'POSITION']]
    hw_total = cw_total = proj_total = t1_total = mid_total = exam_total = 0
    for idx, grade in enumerate(selected_grades, start=1):
        hw_total += getattr(grade, 'homework', 0) or 0
        cw_total += getattr(grade, 'class_work', 0) or 0
        proj_total += getattr(grade, 'project', 0) or 0
        t1_total += getattr(grade, 'first_test', 0) or 0
        mid_total += getattr(grade, 'midterm_test', 0) or 0
        exam_total += getattr(grade, 'exam', 0) or 0

        assessment_data.append([
            grade.subject.name,
            f'{grade.homework:.0f}',
            f'{grade.class_work:.0f}',
            f'{grade.project:.0f}',
            f'{grade.first_test:.0f}',
            f'{grade.midterm_test:.0f}',
            f'{grade.exam:.0f}',
            f'{grade.marks:.0f}',
            grade.letter_grade,
            str(idx),
        ])

    total_marks = sum(g.marks for g in selected_grades)
    assessment_data.append([
        'TOTAL',
        f'{hw_total:.0f}',
        f'{cw_total:.0f}',
        f'{proj_total:.0f}',
        f'{t1_total:.0f}',
        f'{mid_total:.0f}',
        f'{exam_total:.0f}',
        f'{total_marks:.0f}',
        '',
        '',
    ])

    assessment_table = Table(assessment_data, colWidths=[120, 30, 30, 30, 30, 30, 40, 40, 35, 35])
    assessment_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -2), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4a261')),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ]))

    behavior_data = [
        ['BEHAVIOUR', 'GRADE (A-F)'],
        ['PUNCTUALITY', selected_behavior.punctuality if selected_behavior else 'N/A'],
        ['RELATIONSHIP WITH STAFF', selected_behavior.relationship_with_staff if selected_behavior else 'N/A'],
        ['POLITENESS', selected_behavior.politeness if selected_behavior else 'N/A'],
        ['NEATNESS', selected_behavior.neatness if selected_behavior else 'N/A'],
        ['CO-OPERATION', selected_behavior.co_operation if selected_behavior else 'N/A'],
        ['OBEDIENCE', selected_behavior.obedience if selected_behavior else 'N/A'],
        ['ATTENTIVENESS', selected_behavior.attentiveness if selected_behavior else 'N/A'],
        ['ADJUSTMENT IN SCHOOL', selected_behavior.adjustment_in_school if selected_behavior else 'N/A'],
        ['RELATIONSHIP WITH PEERS', selected_behavior.relationship_with_peers if selected_behavior else 'N/A'],
    ]
    behavior_table = Table(behavior_data, colWidths=[220, 80])
    behavior_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4a261')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
    ]))

    rating_data = [
        ['KEY TO RATING', ''],
        ['A = EXCELLENT', '90-100'],
        ['B = VERY GOOD', '80-89'],
        ['C = GOOD', '70-79'],
        ['D = AVERAGE', '60-69'],
        ['E = PASS', '50-59'],
        ['F = FAIL', '< 50'],
    ]
    rating_table = Table(rating_data, colWidths=[180, 120])
    rating_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4a261')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
    ]))

    doc.build([
        heading,
        subtitle,
        Spacer(1, 12),
        info_table,
        Spacer(1, 12),
        assessment_table,
        Spacer(1, 12),
        rating_table,
        Spacer(1, 12),
        behavior_table,
        Spacer(1, 36),
        Paragraph('Class Teacher\'s Comment: ___________________________________________', styles['Normal']),
        Spacer(1, 18),
        Paragraph('Head Teacher\'s Comment: ___________________________________________', styles['Normal']),
    ])

    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response
