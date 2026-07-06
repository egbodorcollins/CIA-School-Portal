from io import BytesIO
import os
from urllib.parse import urlencode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.db import transaction
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from .decorators import class_teacher_or_admin_required, teacher_or_admin_required, admin_required
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from .models import (
    Student,
    Grade,
    BehavioralGrade,
    TermSetting,
    Profile,
    Activity,
    Subject,
    ClassPromotionRequest,
    ResultPublication,
    TERM_CHOICES,
    validate_academic_year,
)
from django.db.models import Avg, Count, Q
from .forms import (
    AUTO_STUDENT_PASSWORD,
    StudentSignUpForm,
    GradeEntryForm,
    BehavioralGradeEntryForm,
    TermSettingForm,
    TeacherCreationForm,
    enroll_student_in_standard_subjects,
    get_class_code,
)
from .subject_map import CLASS_PROGRESSION
from django.forms import HiddenInput


class CaseInsensitiveAuthenticationForm(AuthenticationForm):
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username:
            return username

        try:
            return User.objects.get(username__iexact=username).username
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            return username


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


def _subject_teacher_subjects(profile):
    if not profile or profile.role != Profile.ROLE_SUBJECT_TEACHER:
        return Subject.objects.none()
    return profile.assigned_subjects.all().order_by('name', 'code')


def _subject_teacher_students(profile, subject=None):
    assigned_subjects = _subject_teacher_subjects(profile)
    subjects = Subject.objects.filter(pk=subject.pk) if subject else assigned_subjects
    return (
        Student.objects.filter(subjects__in=subjects)
        .distinct()
        .order_by('last_name', 'first_name')
    )


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


def _result_publication_for(student, academic_year, term):
    return ResultPublication.objects.filter(
        student=student,
        academic_year=academic_year,
        term=term,
    ).first()


def _result_access_allowed(student, academic_year, term):
    publication = _result_publication_for(student, academic_year, term)
    return bool(publication and publication.is_available)


def _class_options():
    return list(
        Student.objects.exclude(class_name__isnull=True)
        .exclude(class_name='')
        .order_by('class_name')
        .values_list('class_name', flat=True)
        .distinct()
    )


def _admin_dashboard_context():
    current_academic_year, current_term = _current_period()
    current_publications = ResultPublication.objects.filter(
        academic_year=current_academic_year,
        term=current_term,
    )
    released_count = current_publications.filter(
        is_fee_cleared=True,
        is_results_approved=True,
    ).count()
    fee_cleared_count = current_publications.filter(is_fee_cleared=True).count()
    approved_count = current_publications.filter(is_results_approved=True).count()
    total_students = Student.objects.count()
    staff_profiles = Profile.objects.exclude(role=Profile.ROLE_STUDENT)
    pending_promotions = ClassPromotionRequest.objects.filter(
        status=ClassPromotionRequest.STATUS_PENDING,
    ).select_related('requested_by')[:6]

    return {
        'current_academic_year': current_academic_year,
        'current_term': current_term,
        'current_term_display': _term_display(current_term),
        'total_students': total_students,
        'total_staff': staff_profiles.count(),
        'admin_staff_count': staff_profiles.filter(role=Profile.ROLE_ADMIN).count(),
        'teacher_count': staff_profiles.filter(
            role__in=[Profile.ROLE_CLASS_TEACHER, Profile.ROLE_SUBJECT_TEACHER],
        ).count(),
        'class_count': Student.objects.exclude(class_name__isnull=True).exclude(class_name='').values('class_name').distinct().count(),
        'grade_count': Grade.objects.filter(academic_year=current_academic_year, term=current_term).count(),
        'behavioral_count': BehavioralGrade.objects.filter(academic_year=current_academic_year, term=current_term).count(),
        'released_count': released_count,
        'fee_cleared_count': fee_cleared_count,
        'approved_count': approved_count,
        'locked_count': max(total_students - released_count, 0),
        'pending_promotion_count': ClassPromotionRequest.objects.filter(status=ClassPromotionRequest.STATUS_PENDING).count(),
        'pending_promotions': pending_promotions,
        'class_summaries': Student.objects.exclude(class_name__isnull=True)
        .exclude(class_name='')
        .values('class_name')
        .annotate(student_count=Count('id'))
        .order_by('class_name'),
        'recent_activities': Activity.objects.select_related('actor', 'target_student', 'target_subject')[:10],
    }


class RateLimitedLoginView(LoginView):
    template_name = 'grades/login.html'
    redirect_authenticated_user = True
    authentication_form = CaseInsensitiveAuthenticationForm

    def get_success_url(self):
        user = self.request.user
        if user.is_authenticated and user.check_password(AUTO_STUDENT_PASSWORD):
            messages.info(self.request, 'Please change the default password before continuing.')
            return reverse('password_change')
        return super().get_success_url()

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
@admin_required
def admin_dashboard(request):
    return render(request, 'grades/admin_dashboard.html', _admin_dashboard_context())


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

    subject_rosters = []
    assigned_subjects = Subject.objects.none()

    if profile.role == 'admin':
        students = Student.objects.all().order_by('last_name')
    elif profile.role == 'class_teacher':
        students = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    elif profile.role == 'subject_teacher':
        assigned_subjects = _subject_teacher_subjects(profile)
        students = _subject_teacher_students(profile)
        for subject in assigned_subjects:
            subject_rosters.append({
                'subject': subject,
                'students': _subject_teacher_students(profile, subject),
            })
    else:
        students = Student.objects.none()

    form = StudentSignUpForm(user=request.user)
    return render(request, 'grades/teacher_dashboard.html', {
        'students': students,
        'form': form,
        'profile': profile,
        'assigned_subjects': assigned_subjects,
        'subject_rosters': subject_rosters,
        'can_request_promotion': profile.role == Profile.ROLE_CLASS_TEACHER or _user_can_approve_promotions(request.user, profile),
        'can_manage_result_publications': _user_can_approve_promotions(request.user, profile),
    })


@login_required
@admin_required
def result_publications(request):
    current_academic_year, current_term = _current_period()
    selected_academic_year = request.GET.get('academic_year') or request.POST.get('academic_year') or current_academic_year
    selected_term = request.GET.get('term') or request.POST.get('term') or current_term
    selected_class = request.GET.get('class') or request.POST.get('class') or ''
    search = (request.GET.get('q') or request.POST.get('q') or '').strip()
    valid_terms = {value for value, _label in TERM_CHOICES}
    if selected_term not in valid_terms:
        selected_term = current_term
    try:
        validate_academic_year(selected_academic_year)
    except ValidationError:
        selected_academic_year = current_academic_year

    students = Student.objects.all().order_by('class_name', 'last_name', 'first_name')
    if selected_class:
        students = students.filter(class_name=selected_class)
    if search:
        students = students.filter(
            Q(first_name__icontains=search)
            | Q(other_names__icontains=search)
            | Q(last_name__icontains=search)
            | Q(student_id__icontains=search)
        )

    students = list(students)

    if request.method == 'POST':
        visible_student_ids = [int(pk) for pk in request.POST.getlist('student_pks') if str(pk).isdigit()]
        student_map = {student.pk: student for student in students}
        updated_count = 0

        with transaction.atomic():
            for student_pk in visible_student_ids:
                student = student_map.get(student_pk)
                if not student:
                    continue

                is_fee_cleared = request.POST.get(f'fee_cleared_{student_pk}') == 'on'
                is_results_approved = request.POST.get(f'results_approved_{student_pk}') == 'on'
                publication, _created = ResultPublication.objects.get_or_create(
                    student=student,
                    academic_year=selected_academic_year,
                    term=selected_term,
                )
                publication.is_fee_cleared = is_fee_cleared
                publication.is_results_approved = is_results_approved
                if is_results_approved:
                    if not publication.approved_by:
                        publication.approved_by = request.user
                    if not publication.approved_at:
                        publication.approved_at = timezone.now()
                else:
                    publication.approved_by = None
                    publication.approved_at = None
                publication.save()
                updated_count += 1

        messages.success(request, f'Result release settings updated for {updated_count} student(s).')
        query = {
            'academic_year': selected_academic_year,
            'term': selected_term,
        }
        if selected_class:
            query['class'] = selected_class
        if search:
            query['q'] = search
        redirect_url = f"{reverse('result_publications')}?{urlencode(query)}"
        return redirect(redirect_url)

    publications = {
        publication.student_id: publication
        for publication in ResultPublication.objects.filter(
            student__in=students,
            academic_year=selected_academic_year,
            term=selected_term,
        ).select_related('approved_by')
    }
    rows = []
    for student in students:
        publication = publications.get(student.pk)
        rows.append({
            'student': student,
            'publication': publication,
            'is_fee_cleared': bool(publication and publication.is_fee_cleared),
            'is_results_approved': bool(publication and publication.is_results_approved),
            'is_available': bool(publication and publication.is_available),
        })

    released_count = sum(1 for row in rows if row['is_available'])
    fee_cleared_count = sum(1 for row in rows if row['is_fee_cleared'])
    approved_count = sum(1 for row in rows if row['is_results_approved'])

    return render(request, 'grades/result_publications.html', {
        'rows': rows,
        'class_options': _class_options(),
        'term_options': [{'value': value, 'label': label} for value, label in TERM_CHOICES],
        'selected_academic_year': selected_academic_year,
        'selected_term': selected_term,
        'selected_class': selected_class,
        'search': search,
        'student_count': len(rows),
        'released_count': released_count,
        'locked_count': len(rows) - released_count,
        'fee_cleared_count': fee_cleared_count,
        'approved_count': approved_count,
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

    is_subject_analytics = profile and profile.role == Profile.ROLE_SUBJECT_TEACHER
    subject_options = []
    selected_subject = None

    if is_subject_analytics:
        subject_options = list(_subject_teacher_subjects(profile))
        requested_subject = request.GET.get('subject')
        if requested_subject:
            selected_subject = next((subject for subject in subject_options if str(subject.pk) == requested_subject), None)
        if not selected_subject and subject_options:
            selected_subject = subject_options[0]
        selected_class = ''
        class_options = []
    elif profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        class_options = [profile.assigned_class]
        selected_class = profile.assigned_class
    else:
        class_options = list(
            Student.objects.exclude(class_name__isnull=True)
            .exclude(class_name='')
            .order_by('class_name')
            .values_list('class_name', flat=True)
            .distinct()
        )
        selected_class = request.GET.get('class') or (class_options[0] if class_options else '')

    if not is_subject_analytics and selected_class not in class_options and class_options:
        selected_class = class_options[0]

    if is_subject_analytics:
        all_grades = Grade.objects.none()
        current_grades = Grade.objects.none()
        subject_students = Student.objects.none()
        if selected_subject:
            all_grades = Grade.objects.filter(
                subject=selected_subject,
                student__subjects=selected_subject,
            ).select_related('student', 'subject')
            current_grades = all_grades.filter(academic_year=current_academic_year, term=current_term)
            subject_students = _subject_teacher_students(profile, selected_subject)
    else:
        all_grades = Grade.objects.filter(student__class_name=selected_class).select_related('student', 'subject')
        current_grades = all_grades.filter(academic_year=current_academic_year, term=current_term)
        subject_students = Student.objects.none()

    subject_averages = list(
        current_grades.values('subject__name', 'subject__code')
        .annotate(average=Avg('marks'), entries=Count('id'))
        .order_by('subject__name')
    )
    class_averages = list(
        current_grades.values('student__class_name')
        .annotate(average=Avg('marks'), entries=Count('id'))
        .order_by('student__class_name')
    ) if is_subject_analytics else []

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
        for row in all_grades.filter(term__in=academic_terms)
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
        'is_subject_analytics': is_subject_analytics,
        'subject_options': subject_options,
        'selected_subject': selected_subject,
        'subject_averages': subject_averages,
        'class_averages': class_averages,
        'grade_distribution': grade_distribution,
        'top_students': top_students,
        'bottom_students': bottom_students,
        'term_averages': term_averages,
        'total_grade_entries': current_grades.count(),
        'student_count': subject_students.count() if is_subject_analytics else (Student.objects.filter(class_name=selected_class).count() if selected_class else 0),
    })


@login_required
@admin_required
def set_current_term(request):
    term_setting = TermSetting.objects.order_by('-updated_at').first()
    if request.method == 'POST':
        form = TermSettingForm(request.POST, instance=term_setting)
        if form.is_valid():
            form.save()
            messages.success(request, 'Current academic period updated successfully.')
            return redirect('admin_dashboard')
    else:
        form = TermSettingForm(instance=term_setting)

    return render(request, 'grades/set_current_term.html', {
        'form': form,
        'term_setting': term_setting,
    })


@login_required
@teacher_or_admin_required
def enter_academic_scores(request):
    current_academic_year, current_term = _current_period()
    profile = getattr(request.user, 'profile', None)
    assigned_subjects = _subject_teacher_subjects(profile)
    selected_subject = None
    subject_pk = request.GET.get('subject') or request.POST.get('subject')
    if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER and subject_pk:
        selected_subject = assigned_subjects.filter(pk=subject_pk).first()
    if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER and not selected_subject:
        selected_subject = assigned_subjects.first()
    if profile and profile.role in [Profile.ROLE_ADMIN, Profile.ROLE_CLASS_TEACHER] and subject_pk:
        selected_subject = Subject.objects.filter(pk=subject_pk).first()

    # Prepare students available for selection based on user's role
    if profile and profile.role == Profile.ROLE_ADMIN:
        students_for_select = Student.objects.all().order_by('last_name')
    elif profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        students_for_select = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    elif profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
        students_for_select = _subject_teacher_students(profile, selected_subject)
    else:
        students_for_select = Student.objects.none()

    selected_student = None
    sel_student_pk = request.GET.get('student') or request.POST.get('student')
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
            form.fields['student'].queryset = students_for_select
            form.fields['subject'].queryset = assigned_subjects
            if selected_subject:
                form.fields['subject'].queryset = assigned_subjects.filter(pk=selected_subject.pk)

        # If a student was pre-selected, lock the student field
        if selected_student:
            form.fields['student'].queryset = Student.objects.filter(pk=selected_student.pk)

        submitted_student = form.fields['student'].queryset.filter(pk=request.POST.get('student')).first()
        submitted_subject = form.fields['subject'].queryset.filter(pk=request.POST.get('subject')).first()
        if submitted_student and submitted_subject:
            existing_grade = Grade.objects.filter(
                student=submitted_student,
                subject=submitted_subject,
                academic_year=current_academic_year,
                term=current_term,
            ).first()
            if existing_grade:
                form.instance = existing_grade

        if form.is_valid():
            data = form.cleaned_data
            existing_grade = Grade.objects.filter(
                student=data['student'],
                subject=data['subject'],
                academic_year=current_academic_year,
                term=current_term,
            ).first()
            grade, created = Grade.objects.update_or_create(
                student=data['student'],
                subject=data['subject'],
                academic_year=current_academic_year,
                term=current_term,
                defaults={
                    'homework': data['homework'] if data.get('homework') is not None else (existing_grade.homework if existing_grade else 0),
                    'class_work': data['class_work'] if data.get('class_work') is not None else (existing_grade.class_work if existing_grade else 0),
                    'project': data['project'] if data.get('project') is not None else (existing_grade.project if existing_grade else 0),
                    'first_test': data['first_test'] if data.get('first_test') is not None else (existing_grade.first_test if existing_grade else 0),
                    'midterm_test': data['midterm_test'] if data.get('midterm_test') is not None else (existing_grade.midterm_test if existing_grade else 0),
                    'exam': data['exam'] if data.get('exam') is not None else (existing_grade.exam if existing_grade else 0),
                    'remarks': data.get('remarks') if data.get('remarks') is not None else (existing_grade.remarks if existing_grade else ''),
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
            if selected_subject:
                if selected_student:
                    return redirect(f"{request.path}?subject={selected_subject.pk}&student={selected_student.pk}")
                return redirect(f"{request.path}?subject={selected_subject.pk}")
            if selected_student:
                return redirect(f"{request.path}?student={selected_student.pk}")
            return redirect('enter_academic_scores')
    else:
        existing_grade = None
        if selected_student and selected_subject:
            existing_grade = Grade.objects.filter(
                student=selected_student,
                subject=selected_subject,
                academic_year=current_academic_year,
                term=current_term,
            ).first()

        if existing_grade:
            form = GradeEntryForm(instance=existing_grade)
        else:
            form = GradeEntryForm()

        if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            form.fields['student'].queryset = students_for_select
            form.fields['subject'].queryset = assigned_subjects
            if selected_subject:
                form.fields['subject'].queryset = assigned_subjects.filter(pk=selected_subject.pk)
                form.fields['subject'].initial = selected_subject.pk
                form.fields['subject'].widget = HiddenInput()

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
                    subj_qs = subj_qs.filter(pk__in=assigned_subjects)
                    if selected_subject:
                        subj_qs = subj_qs.filter(pk=selected_subject.pk)

                form.fields['subject'].queryset = subj_qs
            except Exception:
                form.fields['subject'].queryset = selected_student.subjects.all()

    # Show only selected student's grades when a student is selected
    if selected_student:
        grades = Grade.objects.filter(academic_year=current_academic_year, term=current_term, student=selected_student).select_related('student', 'subject').order_by('subject__name')
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            grades = grades.filter(subject__in=assigned_subjects)
            if selected_subject:
                grades = grades.filter(subject=selected_subject)
    else:
        grades = Grade.objects.filter(academic_year=current_academic_year, term=current_term).select_related('student', 'subject').order_by('student__last_name', 'subject__name')
        if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
            grades = grades.filter(student__class_name=profile.assigned_class)
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            grades = grades.filter(subject__in=assigned_subjects)
            if selected_subject:
                grades = grades.filter(subject=selected_subject)

    return render(request, 'grades/enter_academic_scores.html', {
        'form': form,
        'grades': grades,
        'current_term': current_term,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
        'students': students_for_select,
        'selected_student': selected_student,
        'assigned_subjects': assigned_subjects,
        'selected_subject': selected_subject,
        'is_subject_teacher': profile and profile.role == Profile.ROLE_SUBJECT_TEACHER,
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
    result_access_allowed = False
    publication = None
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
        publication = _result_publication_for(student, selected_academic_year, selected_term)
        result_access_allowed = _result_access_allowed(student, selected_academic_year, selected_term)
        if result_access_allowed:
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
        else:
            messages.info(
                request,
                'Results are currently locked. They will be available once outstanding fees are cleared and the school approves the result publication.',
            )
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
        'result_access_allowed': result_access_allowed,
        'publication': publication,
    })


_RED = colors.HexColor('#c81a26')
_ORANGE = colors.HexColor('#f6931e')
_DARK = colors.HexColor('#24181c')
_LIGHT = colors.HexColor('#fff7f0')
_GREY = colors.HexColor('#e8e2dc')
_WHITE = colors.white


def _rounded_rect(c, x, y, w, h, r, fill=None, stroke=None, stroke_width=0.5):
    path = c.beginPath()
    path.moveTo(x + r, y)
    path.lineTo(x + w - r, y)
    path.arcTo(x + w - r, y, x + w, y + r, 270, 90)
    path.lineTo(x + w, y + h - r)
    path.arcTo(x + w - r, y + h - r, x + w, y + h, 0, 90)
    path.lineTo(x + r, y + h)
    path.arcTo(x, y + h - r, x + r, y + h, 90, 90)
    path.lineTo(x, y + r)
    path.arcTo(x, y, x + r, y + r, 180, 90)
    path.close()

    should_fill = fill is not None
    should_stroke = stroke is not None
    if should_fill:
        c.setFillColor(fill)
    if should_stroke:
        c.setStrokeColor(stroke)
        c.setLineWidth(stroke_width)
    c.drawPath(path, fill=int(should_fill), stroke=int(should_stroke))


def _letter_color(letter):
    return {
        'A': colors.HexColor('#1f6b3e'),
        'B': colors.HexColor('#276fbf'),
        'C': colors.HexColor('#e07b00'),
        'D': colors.HexColor('#b05000'),
        'E': colors.HexColor('#a00000'),
        'F': colors.HexColor('#6b0000'),
    }.get(str(letter).upper(), _DARK)


def _average_letter_grade(average_score):
    if average_score >= 90:
        return 'A'
    if average_score >= 80:
        return 'B'
    if average_score >= 70:
        return 'C'
    if average_score >= 60:
        return 'D'
    if average_score >= 50:
        return 'E'
    return 'F'


def _head_teacher_comment(average_score):
    comments = {
        'A': 'Excellent result. Keep up the outstanding performance.',
        'B': 'Very good result. Keep working hard for excellence.',
        'C': 'Good result. More consistent effort will bring higher achievement.',
        'D': 'Satisfactory result. Greater focus and regular study are needed.',
        'E': 'Fair result. Please improve study habits and seek support.',
        'F': 'Poor result. Urgent improvement and close guidance are required.',
    }
    return comments[_average_letter_grade(average_score)]


def _resolve_logo_path():
    """Return absolute path to logo2.png, or None if not found."""
    base = getattr(settings, 'BASE_DIR', None)
    candidates = []
    if base:
        candidates += [
            os.path.join(str(base), 'graphic',          'logo2.png'),
            os.path.join(str(base), 'grades', 'static', 'logo2.png'),
            os.path.join(str(base), 'static',           'logo2.png'),
        ]
    for static_dir in getattr(settings, 'STATICFILES_DIRS', []):
        candidates.append(os.path.join(str(static_dir), 'logo2.png'))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def build_report_card(
    *,
    student_name,
    student_id,
    class_name,
    nationality,
    state_of_origin,
    club_society,
    academic_year,
    term_display,
    class_count,
    times_present,
    average_score,
    highest_average,
    grades,
    behavior,
    teacher_comment='',
    head_comment='',
):
    buf = BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)

    width, height = A4
    margin = 18 * mm
    content_width = width - 2 * margin
    y = height - margin

    band_h  = 32 * mm
    logo_sz = 30 * mm   # logo drawn as a square inside the header

    _rounded_rect(cv, margin, y - band_h, content_width, band_h, 6, fill=_RED)

    # ── Logo (left side of header) ────────────────────────────────────────────
    logo_drawn = False
    logo_path = _resolve_logo_path()
    if logo_path:
        try:
            logo_x = margin + 4 * mm
            logo_y = y - band_h + (band_h - logo_sz) / 2   # vertically centred
            # # White circle behind logo so it pops on the red background
            # cv.setFillColor(_WHITE)
            # cv.circle(logo_x + logo_sz / 2, logo_y + logo_sz / 2,
            #           logo_sz / 4 + 1.5 * mm, fill=1, stroke=0)
            cv.drawImage(
                logo_path, logo_x, logo_y,
                width=logo_sz, height=logo_sz,
                preserveAspectRatio=True, mask='auto',
            )
            logo_drawn = True
        except Exception:
            logo_drawn = False   # graceful fallback: text stays centred

    # Text centred in the space to the right of the logo (or full width if no logo)
    text_cx = (margin + logo_sz + 8 * mm + width - margin) / 2 if logo_drawn else width / 2

    cv.setFillColor(_WHITE)
    cv.setFont('Helvetica-Bold', 15)
    cv.drawCentredString(text_cx, y - 10 * mm, 'CORINASIA INTERNATIONAL ACADEMY')
    cv.setFont('Helvetica', 8.5)
    cv.drawCentredString(text_cx, y - 17 * mm, 'CIA - Uniqueness in All | ciaabuja@gmail.com | +234 802 3160 109')
    cv.setFont('Helvetica-Bold', 11)
    cv.drawCentredString(text_cx, y - 26 * mm, f'{academic_year} | {term_display.upper()} REPORT CARD')

    y -= band_h + 4 * mm

    info_h = 32 * mm
    _rounded_rect(cv, margin, y - info_h, content_width, info_h, 4, fill=_LIGHT, stroke=_GREY)

    row_h = 5.6 * mm
    left_x = margin + 4 * mm
    right_x = margin + content_width / 2 + 4 * mm

    rows_left = [
        ('NAME', student_name),
        ('STUDENT ID', student_id),
        ('CLASS', class_name or '-'),
    ]
    rows_right = [
        ('NATIONALITY', nationality or 'Nigeria'),
        ('STATE OF ORIGIN', state_of_origin or '-'),
        ('CLUB / SOCIETY', club_society or '-'),
        ('ACADEMIC YEAR', academic_year),
    ]

    def draw_info_row(x, row_y, label, value):
        cv.setFont('Helvetica-Bold', 7)
        cv.setFillColor(_RED)
        cv.drawString(x, row_y, f'{label}:')
        cv.setFont('Helvetica', 8)
        cv.setFillColor(_DARK)
        cv.drawString(x + 33 * mm, row_y, str(value))

    base_y = y - 7 * mm
    for index, (label, value) in enumerate(rows_left):
        draw_info_row(left_x, base_y - index * row_h, label, value)
    for index, (label, value) in enumerate(rows_right):
        draw_info_row(right_x, base_y - index * row_h, label, value)

    y -= info_h + 4 * mm

    stat_items = [
        ('STUDENTS IN CLASS', str(class_count), _ORANGE),
        ('TIMES PRESENT', str(times_present), _ORANGE),
        ('YOUR AVERAGE', f'{average_score:.1f}', _RED),
        ('CLASS HIGHEST', f'{highest_average:.1f}', colors.HexColor('#276fbf')),
    ]
    box_w = content_width / len(stat_items)
    stat_h = 14 * mm
    for index, (label, value, color) in enumerate(stat_items):
        box_x = margin + index * box_w
        _rounded_rect(cv, box_x + 1.5 * mm, y - stat_h, box_w - 3 * mm, stat_h, 3, fill=color)
        cv.setFillColor(_WHITE)
        cv.setFont('Helvetica-Bold', 15)
        cv.drawCentredString(box_x + box_w / 2, y - 8 * mm, value)
        cv.setFont('Helvetica', 6.5)
        cv.drawCentredString(box_x + box_w / 2, y - 12.5 * mm, label)

    y -= stat_h + 5 * mm

    cv.setFont('Helvetica-Bold', 9)
    cv.setFillColor(_DARK)
    cv.drawString(margin, y, 'ACADEMIC PERFORMANCE')
    y -= 3 * mm

    header = ['SUBJECT', 'HW\n/5', 'CW\n/10', 'PRJ\n/5', '1ST\n/10', 'MID\n/10', 'EXAM\n/60', 'TOTAL\n/100', 'GRADE']
    col_widths = [53 * mm, 12 * mm, 12 * mm, 12 * mm, 12 * mm, 12 * mm, 14 * mm, 16 * mm, 13 * mm]

    hw_total = cw_total = proj_total = t1_total = mid_total = exam_total = total_marks = 0
    rows = [header]
    for grade in grades:
        rows.append([
            grade['subject'],
            f"{grade['hw']:.0f}",
            f"{grade['cw']:.0f}",
            f"{grade['proj']:.0f}",
            f"{grade['t1']:.0f}",
            f"{grade['mid']:.0f}",
            f"{grade['exam']:.0f}",
            f"{grade['total']:.0f}",
            grade['letter'],
        ])
        hw_total += grade['hw']
        cw_total += grade['cw']
        proj_total += grade['proj']
        t1_total += grade['t1']
        mid_total += grade['mid']
        exam_total += grade['exam']
        total_marks += grade['total']

    rows.append([
        'CUMULATIVE TOTAL',
        f'{hw_total:.0f}',
        f'{cw_total:.0f}',
        f'{proj_total:.0f}',
        f'{t1_total:.0f}',
        f'{mid_total:.0f}',
        f'{exam_total:.0f}',
        f'{total_marks:.0f}',
        '',
    ])

    table = Table(rows, colWidths=col_widths)
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), _RED),
        ('TEXTCOLOR', (0, 0), (-1, 0), _WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 8),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8e8d8')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, _GREY),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, _RED),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [_WHITE, colors.HexColor('#fdf6f0')]),
        ('LEFTPADDING', (0, 0), (0, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ])
    for row_index, grade in enumerate(grades, start=1):
        table_style.add('TEXTCOLOR', (-1, row_index), (-1, row_index), _letter_color(grade['letter']))
        table_style.add('FONTNAME', (-1, row_index), (-1, row_index), 'Helvetica-Bold')
        table_style.add('FONTSIZE', (-1, row_index), (-1, row_index), 9)

    table.setStyle(table_style)
    _table_width, table_height = table.wrapOn(cv, content_width, height)
    table.drawOn(cv, margin, y - table_height)
    y -= table_height + 6 * mm

    left_col_w = 82 * mm
    right_col_w = content_width - left_col_w - 5 * mm
    right_col_x = margin + left_col_w + 5 * mm

    behavior_rows = [['BEHAVIOUR TRAIT', 'GRADE']]
    trait_labels = [
        ('Punctuality', 'punctuality'),
        ('Relationship with Staff', 'relationship_with_staff'),
        ('Politeness', 'politeness'),
        ('Neatness', 'neatness'),
        ('Co-operation', 'co_operation'),
        ('Obedience', 'obedience'),
        ('Attentiveness', 'attentiveness'),
        ('Adjustment in School', 'adjustment_in_school'),
        ('Relationship with Peers', 'relationship_with_peers'),
    ]
    for label, key in trait_labels:
        behavior_rows.append([label, behavior.get(key, '-') if behavior else '-'])

    behavior_table = Table(behavior_rows, colWidths=[62 * mm, 20 * mm])
    behavior_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), _ORANGE),
        ('TEXTCOLOR', (0, 0), (-1, 0), _WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('GRID', (0, 0), (-1, -1), 0.4, _GREY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [_WHITE, colors.HexColor('#fff8f2')]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (0, -1), 4),
    ])
    if behavior:
        for row_index, (_label, key) in enumerate(trait_labels, start=1):
            behavior_style.add('TEXTCOLOR', (1, row_index), (1, row_index), _letter_color(behavior.get(key, '')))
            behavior_style.add('FONTNAME', (1, row_index), (1, row_index), 'Helvetica-Bold')
            behavior_style.add('FONTSIZE', (1, row_index), (1, row_index), 9)
    behavior_table.setStyle(behavior_style)
    _behavior_width, behavior_height = behavior_table.wrapOn(cv, left_col_w, height)
    behavior_table.drawOn(cv, margin, y - behavior_height)

    key_h = 36 * mm
    _rounded_rect(cv, right_col_x, y - key_h, right_col_w, key_h, 3, fill=_LIGHT, stroke=_GREY)
    cv.setFont('Helvetica-Bold', 7.5)
    cv.setFillColor(_RED)
    cv.drawString(right_col_x + 3 * mm, y - 5 * mm, 'KEY TO RATING')
    ratings = [
        ('A', 'EXCELLENT', '90 - 100'),
        ('B', 'VERY GOOD', '80 - 89'),
        ('C', 'GOOD', '70 - 79'),
        ('D', 'SATISFACTORY', '60 - 69'),
        ('E', 'PASS', '50 - 59'),
        ('F', 'FAIL', 'Below 50'),
    ]
    for index, (letter, description, score_range) in enumerate(ratings):
        row_y = y - 11 * mm - index * 4.2 * mm
        cv.setFillColor(_letter_color(letter))
        cv.setFont('Helvetica-Bold', 7.5)
        cv.drawString(right_col_x + 3 * mm, row_y, letter)
        cv.setFillColor(_DARK)
        cv.setFont('Helvetica', 7.5)
        cv.drawString(right_col_x + 9 * mm, row_y, f'= {description}')
        cv.setFillColor(colors.HexColor('#888888'))
        cv.drawRightString(right_col_x + right_col_w - 3 * mm, row_y, score_range)

    comment_top = y - key_h - 3 * mm
    comment_h = max(behavior_height - key_h - 3 * mm, 22 * mm)
    _rounded_rect(cv, right_col_x, comment_top - comment_h, right_col_w, comment_h, 3, fill=_WHITE, stroke=_GREY)

    cv.setFont('Helvetica-Bold', 7.5)
    cv.setFillColor(_RED)
    cv.drawString(right_col_x + 3 * mm, comment_top - 5 * mm, "CLASS TEACHER'S COMMENT")
    cv.setFont('Helvetica', 7.5)
    cv.setFillColor(_DARK)
    cv.drawString(right_col_x + 3 * mm, comment_top - 10.5 * mm, (teacher_comment or '').strip() or ('_' * 36))

    cv.setFont('Helvetica-Bold', 7.5)
    cv.setFillColor(_RED)
    cv.drawString(right_col_x + 3 * mm, comment_top - 17 * mm, "HEAD TEACHER'S COMMENT")
    cv.setFont('Helvetica', 7.5)
    cv.setFillColor(_DARK)
    cv.drawString(right_col_x + 3 * mm, comment_top - 22.5 * mm, (head_comment or '').strip() or ('_' * 36))

    y -= max(behavior_height, key_h + comment_h + 3 * mm) + 5 * mm

    cv.setStrokeColor(_GREY)
    cv.setLineWidth(0.5)
    cv.line(margin, y, margin + content_width, y)
    y -= 4 * mm
    cv.setFont('Helvetica', 7)
    cv.setFillColor(colors.HexColor('#888888'))
    cv.drawCentredString(
        width / 2,
        y,
        'Official use requires the school stamp and authorised signature. This report is computer-generated for preview only.',
    )

    cv.showPage()
    cv.save()
    return buf.getvalue()


@login_required
def report_card_pdf(request):
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
    if not _result_access_allowed(student, selected_academic_year, selected_term):
        messages.error(request, 'Results are not yet available. They become visible once fees are cleared and the school approves them.')
        return redirect('student_dashboard')
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

    def average_for(student_obj):
        grades = Grade.objects.filter(
            student=student_obj,
            academic_year=selected_academic_year,
            term=selected_term,
        )
        return (sum(grade.marks for grade in grades) / len(grades)) if grades else 0.0

    average_score = average_for(student)
    highest_average = max((average_for(classmate) for classmate in class_students), default=0.0)

    grade_dicts = [
        {
            'subject': grade.subject.name,
            'hw': grade.homework,
            'cw': grade.class_work,
            'proj': grade.project,
            't1': grade.first_test,
            'mid': grade.midterm_test,
            'exam': grade.exam,
            'total': grade.marks,
            'letter': grade.letter_grade,
        }
        for grade in selected_grades
    ]

    behavior_dict = None
    if selected_behavior:
        behavior_dict = {
            'punctuality': selected_behavior.punctuality,
            'relationship_with_staff': selected_behavior.relationship_with_staff,
            'politeness': selected_behavior.politeness,
            'neatness': selected_behavior.neatness,
            'co_operation': selected_behavior.co_operation,
            'obedience': selected_behavior.obedience,
            'attentiveness': selected_behavior.attentiveness,
            'adjustment_in_school': selected_behavior.adjustment_in_school,
            'relationship_with_peers': selected_behavior.relationship_with_peers,
        }

    pdf_bytes = build_report_card(
        student_name=student.full_name,
        student_id=student.student_id,
        class_name=student.class_name or 'Not assigned',
        nationality=student.nationality,
        state_of_origin=student.state_of_origin or '',
        # sport_house removed from model
        club_society=student.club_and_society or '',
        academic_year=selected_academic_year,
        term_display=term_display,
        class_count=class_count,
        times_present=selected_behavior.times_present if selected_behavior else 0,
        average_score=average_score,
        highest_average=highest_average,
        grades=grade_dicts,
        behavior=behavior_dict,
        teacher_comment=selected_behavior.remarks if selected_behavior and selected_behavior.remarks else '',
        head_comment=_head_teacher_comment(average_score),
    )

    safe_student_id = student.student_id.replace('/', '-')
    safe_year = selected_academic_year.replace('/', '-')
    filename = f'{safe_student_id}_{safe_year}_{selected_term}_report.pdf'

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
