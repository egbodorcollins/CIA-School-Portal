from io import BytesIO
import os
import re
from urllib.parse import urlencode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
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
from reportlab.pdfbase.pdfmetrics import stringWidth

from .models import (
    Student,
    Grade,
    BehavioralGrade,
    TermSetting,
    Profile,
    Activity,
    Announcement,
    Subject,
    ClassPromotionRequest,
    ResultPublication,
    TERM_CHOICES,
    validate_academic_year,
)
from django.db.models import Avg, Count, Q
from django.db.utils import DatabaseError
from .forms import (
    AUTO_STUDENT_PASSWORD,
    StudentSignUpForm,
    GradeEntryForm,
    BehavioralGradeEntryForm,
    TermSettingForm,
    AnnouncementForm,
    TeacherCreationForm,
    enroll_student_in_standard_subjects,
    get_class_code,
)
from .subject_map import CLASS_NAME_BY_CODE, CLASS_PROGRESSION, STANDARD_SUBJECTS
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
TERM_DIGITS = {'first_term': '1', 'second_term': '2', 'third_term': '3'}
SUBJECT_CODE_RE = re.compile(r'^(?P<abbr>[A-Z]+)\s+(?P<class_code>[A-Z]+\d?)(?P<term>[123S])$', re.IGNORECASE)


def _term_display(term):
    return dict(TERM_CHOICES).get(term, term.replace('_', ' ').title())


def _current_period():
    return TermSetting.get_current_period()


def _subject_code_parts(subject):
    match = SUBJECT_CODE_RE.match((subject.code or '').strip())
    if not match:
        return None
    return (
        match.group('abbr').upper(),
        match.group('class_code').upper(),
        match.group('term').upper(),
    )


def _subject_family_key(subject):
    parts = _subject_code_parts(subject)
    if parts:
        abbr, class_code, _term_digit = parts
        return f'{abbr}:{class_code}'
    return f'name:{(subject.name or subject.code).strip().lower()}'


def _subject_codes_for_class_term(class_name, term):
    class_code = get_class_code(class_name)
    term_digit = TERM_DIGITS.get(term)
    if not class_code or not term_digit:
        return []
    return [
        f'{abbr} {class_code}{term_digit}'
        for abbr, _name in STANDARD_SUBJECTS.get(class_code, [])
    ]


def _term_subjects_for_student(student, term):
    codes = _subject_codes_for_class_term(student.class_name, term)
    if codes:
        subjects = Subject.objects.filter(code__in=codes).order_by('name', 'code')
        if subjects.exists():
            return subjects

    parts = get_class_code(student.class_name)
    term_digit = TERM_DIGITS.get(term)
    if parts and term_digit:
        fallback = student.subjects.filter(code__endswith=f'{parts}{term_digit}').order_by('name', 'code')
        if fallback.exists():
            return fallback
    return student.subjects.all().order_by('name', 'code')


def _resolve_subject_for_term(subject, term):
    parts = _subject_code_parts(subject)
    term_digit = TERM_DIGITS.get(term)
    if not parts or not term_digit:
        return subject
    abbr, class_code, _old_term_digit = parts
    return Subject.objects.filter(code=f'{abbr} {class_code}{term_digit}').first() or subject


def _subject_teacher_subjects(profile, term=None):
    if not profile or profile.role != Profile.ROLE_SUBJECT_TEACHER:
        return Subject.objects.none()

    assigned_subjects = profile.assigned_subjects.all()
    if not term or term == 'session':
        return assigned_subjects.order_by('name', 'code')

    subject_ids = []
    seen_ids = set()
    for subject in assigned_subjects:
        resolved_subject = _resolve_subject_for_term(subject, term)
        if resolved_subject.pk not in seen_ids:
            subject_ids.append(resolved_subject.pk)
            seen_ids.add(resolved_subject.pk)
    return Subject.objects.filter(pk__in=subject_ids).order_by('name', 'code')


def _subject_teacher_students(profile, subject=None):
    assigned_subjects = _subject_teacher_subjects(profile, TermSetting.get_current_term())
    subjects = Subject.objects.filter(pk=subject.pk) if subject else assigned_subjects
    subject_list = list(subjects)

    class_names = []
    for subject_obj in subject_list:
        parts = _subject_code_parts(subject_obj)
        if parts:
            _abbr, class_code, _term_digit = parts
            class_name = CLASS_NAME_BY_CODE.get(class_code)
            if class_name and class_name not in class_names:
                class_names.append(class_name)

    if class_names:
        return Student.objects.filter(class_name__in=class_names).order_by('last_name', 'first_name')

    return Student.objects.filter(subjects__in=subject_list).distinct().order_by('last_name', 'first_name')


def _student_result_period(student, requested_year=None, requested_term=None):
    grade_periods = Grade.objects.filter(student=student).values_list('academic_year', 'term')
    behavior_periods = BehavioralGrade.objects.filter(student=student).values_list('academic_year', 'term')
    publication_periods = ResultPublication.objects.filter(student=student).values_list('academic_year', 'term')
    periods = sorted(
        set(grade_periods).union(set(behavior_periods)).union(set(publication_periods)),
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


def _staff_student_queryset(user):
    profile = getattr(user, 'profile', None)
    if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        return Student.objects.filter(class_name=profile.assigned_class)
    if _user_can_approve_promotions(user, profile):
        return Student.objects.all()
    return Student.objects.none()


def _visible_announcements_for_user(user, limit=6):
    if not user or not user.is_authenticated:
        try:
            return list(Announcement.objects.filter(
                is_active=True,
                audience=Announcement.AUDIENCE_EVERYONE,
            ).select_related('created_by')[:limit])
        except DatabaseError:
            return []

    profile = getattr(user, 'profile', None)
    role = profile.role if profile else None
    if user.is_superuser or role == Profile.ROLE_ADMIN:
        try:
            return list(Announcement.objects.filter(is_active=True).select_related('created_by').prefetch_related('target_users')[:limit])
        except DatabaseError:
            return []

    is_staff_user = bool(user.is_superuser or getattr(user, 'is_staff', False) or role in [
        Profile.ROLE_ADMIN,
        Profile.ROLE_CLASS_TEACHER,
        Profile.ROLE_SUBJECT_TEACHER,
    ])

    try:
        student = Student.objects.filter(student_id=user.username).first()
    except Exception:
        student = None

    visible = []
    try:
        announcements = Announcement.objects.filter(is_active=True).select_related('created_by').prefetch_related('target_users')
    except DatabaseError:
        return []

    try:
        for announcement in announcements:
            target_classes = announcement.target_classes or []
            is_target_user = announcement.target_users.filter(pk=user.pk).exists()
            is_target_class = (
                (student and student.class_name in target_classes)
                or (profile and profile.assigned_class in target_classes)
            )

            if announcement.audience == Announcement.AUDIENCE_EVERYONE:
                visible.append(announcement)
            elif announcement.audience == Announcement.AUDIENCE_STAFF and is_staff_user:
                visible.append(announcement)
            elif announcement.audience == Announcement.AUDIENCE_CLASS_TEACHERS and role == Profile.ROLE_CLASS_TEACHER:
                visible.append(announcement)
            elif announcement.audience == Announcement.AUDIENCE_SUBJECT_TEACHERS and role == Profile.ROLE_SUBJECT_TEACHER:
                visible.append(announcement)
            elif announcement.audience == Announcement.AUDIENCE_STUDENTS and role == Profile.ROLE_STUDENT:
                visible.append(announcement)
            elif announcement.audience == Announcement.AUDIENCE_CLASSES and is_target_class:
                visible.append(announcement)
            elif announcement.audience == Announcement.AUDIENCE_INDIVIDUALS and is_target_user:
                visible.append(announcement)

            if len(visible) >= limit:
                break
    except DatabaseError:
        return []

    return visible


def _admin_announcements(limit=6):
    try:
        return list(Announcement.objects.filter(is_active=True).select_related('created_by')[:limit])
    except DatabaseError:
        return []


def _term_subject_for_family(class_code, abbr, term):
    term_digit = TERM_DIGITS.get(term)
    if not term_digit:
        return None
    return Subject.objects.filter(code=f'{abbr} {class_code}{term_digit}').first()


def _session_entry_rows(student, academic_year):
    class_code = get_class_code(student.class_name)
    if not class_code or class_code not in STANDARD_SUBJECTS:
        return []

    academic_terms = ['first_term', 'second_term', 'third_term']
    rows = []
    for abbr, subject_name in STANDARD_SUBJECTS[class_code]:
        terms = {}
        marks = []
        for term in academic_terms:
            subject = _term_subject_for_family(class_code, abbr, term)
            grade = None
            if subject:
                grade = Grade.objects.filter(
                    student=student,
                    subject=subject,
                    academic_year=academic_year,
                    term=term,
                ).first()
            value = grade.marks if grade else None
            if value is not None:
                marks.append(value)
            terms[term] = {
                'subject': subject,
                'grade': grade,
                'value': value,
                'is_locked': grade is not None,
                'input_name': f'total_{subject.pk}_{term}' if subject and grade is None else '',
            }

        average = (sum(marks) / len(marks)) if marks else None
        rows.append({
            'abbr': abbr,
            'subject': subject_name,
            'terms': terms,
            'average': average,
            'letter': _average_letter_grade(average or 0),
        })
    return rows


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
        'announcements': _admin_announcements(),
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
        'announcements': _visible_announcements_for_user(request.user),
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
            if request.resolver_match and request.resolver_match.url_name == 'admin_staff_new':
                return redirect('admin_staff')
            return redirect('teacher_dashboard')
    else:
        form = TeacherCreationForm()
        form.fields['role'].choices = [c for c in Profile.ROLE_CHOICES if c[0] in allowed_roles]
        if profile.role == Profile.ROLE_CLASS_TEACHER:
            form.fields['assigned_class'].initial = profile.assigned_class

    return render(request, 'grades/register_teacher.html', {
        'form': form,
        'cancel_url_name': 'admin_staff' if request.resolver_match and request.resolver_match.url_name == 'admin_staff_new' else 'teacher_dashboard',
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
@admin_required
def admin_classes(request):
    current_academic_year, current_term = _current_period()
    class_rows = []
    class_names = _class_options()
    for class_name in class_names:
        students = Student.objects.filter(class_name=class_name)
        grade_qs = Grade.objects.filter(
            student__class_name=class_name,
            academic_year=current_academic_year,
            term=current_term,
        )
        behavior_count = BehavioralGrade.objects.filter(
            student__class_name=class_name,
            academic_year=current_academic_year,
            term=current_term,
        ).count()
        class_teacher = Profile.objects.filter(
            role=Profile.ROLE_CLASS_TEACHER,
            assigned_class=class_name,
        ).select_related('user').first()
        class_rows.append({
            'name': class_name,
            'student_count': students.count(),
            'grade_count': grade_qs.count(),
            'average': grade_qs.aggregate(average=Avg('marks'))['average'],
            'behavior_count': behavior_count,
            'teacher': class_teacher.user if class_teacher else None,
            'next_class': CLASS_PROGRESSION.get(class_name),
        })

    return render(request, 'grades/admin_classes.html', {
        'class_rows': class_rows,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
    })


@login_required
@admin_required
def admin_class_detail(request, class_name):
    current_academic_year, current_term = _current_period()
    students = Student.objects.filter(class_name=class_name).order_by('last_name', 'first_name')
    grade_qs = Grade.objects.filter(
        student__class_name=class_name,
        academic_year=current_academic_year,
        term=current_term,
    )
    subject_averages = (
        grade_qs.values('subject__name', 'subject__code')
        .annotate(average=Avg('marks'), entries=Count('id'))
        .order_by('subject__name')
    )
    teacher_profile = Profile.objects.filter(
        role=Profile.ROLE_CLASS_TEACHER,
        assigned_class=class_name,
    ).select_related('user').first()

    return render(request, 'grades/admin_class_detail.html', {
        'class_name': class_name,
        'students': students,
        'student_count': students.count(),
        'teacher': teacher_profile.user if teacher_profile else None,
        'average': grade_qs.aggregate(average=Avg('marks'))['average'],
        'grade_count': grade_qs.count(),
        'behavior_count': BehavioralGrade.objects.filter(
            student__class_name=class_name,
            academic_year=current_academic_year,
            term=current_term,
        ).count(),
        'subject_averages': subject_averages,
        'next_class': CLASS_PROGRESSION.get(class_name),
        'current_academic_year': current_academic_year,
        'current_term': current_term,
        'current_term_display': _term_display(current_term),
    })


@login_required
@admin_required
def admin_subjects(request):
    current_academic_year, current_term = _current_period()
    subjects = (
        Subject.objects.annotate(
            student_count=Count('students', distinct=True),
            current_grade_count=Count(
                'grades',
                filter=Q(grades__academic_year=current_academic_year, grades__term=current_term),
                distinct=True,
            ),
            current_average=Avg(
                'grades__marks',
                filter=Q(grades__academic_year=current_academic_year, grades__term=current_term),
            ),
        )
        .order_by('name', 'code')
    )

    return render(request, 'grades/admin_subjects.html', {
        'subjects': subjects,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
    })


@login_required
@admin_required
def admin_subject_detail(request, subject_id):
    current_academic_year, current_term = _current_period()
    subject = get_object_or_404(Subject, pk=subject_id)
    grades = Grade.objects.filter(
        subject=subject,
        academic_year=current_academic_year,
        term=current_term,
    ).select_related('student').order_by('student__class_name', 'student__last_name')
    students = Student.objects.filter(subjects=subject).order_by('class_name', 'last_name', 'first_name')
    class_rows = (
        grades.values('student__class_name')
        .annotate(average=Avg('marks'), entries=Count('id'))
        .order_by('student__class_name')
    )

    return render(request, 'grades/admin_subject_detail.html', {
        'subject': subject,
        'students': students,
        'grades': grades,
        'class_rows': class_rows,
        'student_count': students.count(),
        'grade_count': grades.count(),
        'average': grades.aggregate(average=Avg('marks'))['average'],
        'current_academic_year': current_academic_year,
        'current_term': current_term,
        'current_term_display': _term_display(current_term),
    })


@login_required
@admin_required
def admin_students(request):
    selected_class = request.GET.get('class') or ''
    search = (request.GET.get('q') or '').strip()
    sort = request.GET.get('sort') or 'name'
    students = Student.objects.all()
    class_options = _class_options()
    if selected_class and selected_class in class_options:
        students = students.filter(class_name=selected_class)
    elif selected_class:
        selected_class = ''
    if search:
        students = students.filter(
            Q(first_name__icontains=search)
            | Q(other_names__icontains=search)
            | Q(last_name__icontains=search)
            | Q(student_id__icontains=search)
        )
    ordering = {
        'name': ['last_name', 'first_name', 'student_id'],
        'class': ['class_name', 'last_name', 'first_name'],
        'student_id': ['student_id', 'last_name', 'first_name'],
        'registered_newest': ['-enrollment_date', 'last_name', 'first_name'],
        'registered_oldest': ['enrollment_date', 'last_name', 'first_name'],
    }.get(sort, ['last_name', 'first_name', 'student_id'])

    return render(request, 'grades/admin_students.html', {
        'students': students.order_by(*ordering),
        'class_options': class_options,
        'selected_class': selected_class,
        'search': search,
        'sort': sort,
        'sort_options': [
            {'value': 'name', 'label': 'Name A-Z'},
            {'value': 'class', 'label': 'Class'},
            {'value': 'student_id', 'label': 'Student ID'},
            {'value': 'registered_newest', 'label': 'Newest Registered'},
            {'value': 'registered_oldest', 'label': 'Oldest Registered'},
        ],
    })


@login_required
@admin_required
def admin_student_detail(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    selected_academic_year, selected_term, year_options, term_options = _student_result_period(
        student,
        request.GET.get('academic_year'),
        request.GET.get('term'),
    )
    grades = Grade.objects.filter(
        student=student,
        academic_year=selected_academic_year,
        term=selected_term,
    ).select_related('subject').order_by('subject__name')
    behavior = BehavioralGrade.objects.filter(
        student=student,
        academic_year=selected_academic_year,
        term=selected_term,
    ).first()
    promotion_requests = [
        request_item
        for request_item in ClassPromotionRequest.objects.all()[:50]
        if student.pk in (request_item.student_pks or [])
    ][:10]

    return render(request, 'grades/admin_student_detail.html', {
        'student': student,
        'grades': grades,
        'behavior': behavior,
        'average': grades.aggregate(average=Avg('marks'))['average'],
        'selected_academic_year': selected_academic_year,
        'selected_term': selected_term,
        'selected_term_display': _term_display(selected_term),
        'academic_year_options': year_options,
        'term_options': term_options,
        'promotion_requests': promotion_requests,
    })


@login_required
@admin_required
def admin_staff(request):
    profiles = (
        Profile.objects.filter(
            Q(role__in=[Profile.ROLE_ADMIN, Profile.ROLE_CLASS_TEACHER, Profile.ROLE_SUBJECT_TEACHER])
            | Q(user__is_staff=True)
            | Q(user__is_superuser=True)
        )
        .select_related('user')
        .prefetch_related('assigned_subjects')
        .order_by('role', 'user__last_name', 'user__first_name', 'user__username')
    )
    return render(request, 'grades/admin_staff.html', {
        'profiles': profiles,
        'total_staff': profiles.count(),
        'active_staff': profiles.filter(user__is_active=True).count(),
        'class_teacher_count': profiles.filter(role=Profile.ROLE_CLASS_TEACHER).count(),
        'subject_teacher_count': profiles.filter(role=Profile.ROLE_SUBJECT_TEACHER).count(),
    })


@login_required
@admin_required
def admin_staff_detail(request, staff_id):
    profile = get_object_or_404(
        Profile.objects.filter(
            Q(role__in=[Profile.ROLE_ADMIN, Profile.ROLE_CLASS_TEACHER, Profile.ROLE_SUBJECT_TEACHER])
            | Q(user__is_staff=True)
            | Q(user__is_superuser=True)
        ).select_related('user').prefetch_related('assigned_subjects'),
        pk=staff_id,
    )
    assigned_class_count = 1 if profile.assigned_class else 0
    return render(request, 'grades/admin_staff_detail.html', {
        'staff_profile': profile,
        'assigned_class_count': assigned_class_count,
    })


@login_required
@admin_required
def admin_promotion(request):
    current_academic_year, current_term = _current_period()
    pending_requests = ClassPromotionRequest.objects.filter(
        status=ClassPromotionRequest.STATUS_PENDING,
    ).select_related('requested_by')
    promotion_rows = []
    for from_class, to_class in CLASS_PROGRESSION.items():
        student_count = Student.objects.filter(class_name=from_class).count()
        if not student_count:
            continue
        pending = next((item for item in pending_requests if item.from_class == from_class), None)
        promotion_rows.append({
            'from_class': from_class,
            'to_class': to_class,
            'student_count': student_count,
            'pending_request': pending,
            'status': 'Pending' if pending else ('Ready' if current_term == 'third_term' else 'Open'),
        })

    return render(request, 'grades/admin_promotion.html', {
        'promotion_rows': promotion_rows,
        'pending_requests': pending_requests,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
    })


@login_required
@admin_required
def admin_promotion_class(request, class_name):
    to_class = CLASS_PROGRESSION.get(class_name)
    if not to_class:
        messages.error(request, 'The selected class does not have a configured next class.')
        return redirect('admin_promotion')

    students = Student.objects.filter(class_name=class_name).order_by('last_name', 'first_name')
    pending_request = ClassPromotionRequest.objects.filter(
        from_class=class_name,
        status=ClassPromotionRequest.STATUS_PENDING,
    ).select_related('requested_by').first()
    selected_pks = set(pending_request.student_pks if pending_request else students.values_list('pk', flat=True))

    return render(request, 'grades/admin_promotion_class.html', {
        'class_name': class_name,
        'to_class': to_class,
        'students': students,
        'pending_request': pending_request,
        'selected_pks': selected_pks,
    })


@login_required
@admin_required
def admin_results(request):
    current_academic_year, current_term = _current_period()
    publications = ResultPublication.objects.filter(
        academic_year=current_academic_year,
        term=current_term,
    )
    grade_count = Grade.objects.filter(academic_year=current_academic_year, term=current_term).count()
    student_count = Student.objects.count()
    approved_count = publications.filter(is_results_approved=True).count()
    released_count = publications.filter(is_fee_cleared=True, is_results_approved=True).count()

    class_rows = []
    for class_name in _class_options():
        class_students = Student.objects.filter(class_name=class_name)
        class_publications = publications.filter(student__class_name=class_name)
        class_rows.append({
            'name': class_name,
            'student_count': class_students.count(),
            'grade_count': Grade.objects.filter(
                student__class_name=class_name,
                academic_year=current_academic_year,
                term=current_term,
            ).count(),
            'approved_count': class_publications.filter(is_results_approved=True).count(),
            'released_count': class_publications.filter(is_fee_cleared=True, is_results_approved=True).count(),
        })

    return render(request, 'grades/admin_results.html', {
        'current_academic_year': current_academic_year,
        'current_term': current_term,
        'current_term_display': _term_display(current_term),
        'student_count': student_count,
        'grade_count': grade_count,
        'approved_count': approved_count,
        'released_count': released_count,
        'locked_count': max(student_count - released_count, 0),
        'class_rows': class_rows,
    })


@login_required
@admin_required
def admin_settings(request):
    term_setting = TermSetting.objects.order_by('-updated_at').first()
    return render(request, 'grades/admin_settings.html', {
        'term_setting': term_setting,
    })


@login_required
@admin_required
def manage_announcements(request):
    if request.method == 'POST':
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            form.save_m2m()
            messages.success(request, 'Announcement published successfully.')
            return redirect('manage_announcements')
    else:
        form = AnnouncementForm()

    announcements = Announcement.objects.select_related('created_by').prefetch_related('target_users')[:30]
    return render(request, 'grades/manage_announcements.html', {
        'form': form,
        'announcements': announcements,
    })


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
        assigned_subjects = _subject_teacher_subjects(profile, _current_period()[1])
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
        'announcements': _visible_announcements_for_user(request.user),
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
@class_teacher_or_admin_required
def staff_results(request):
    current_academic_year, current_term = _current_period()
    selected_academic_year = request.GET.get('academic_year') or current_academic_year
    selected_term = request.GET.get('term') or current_term
    selected_class = request.GET.get('class') or ''
    search = (request.GET.get('q') or '').strip()
    sort = request.GET.get('sort') or 'name'
    valid_terms = {value for value, _label in TERM_CHOICES}
    if selected_term not in valid_terms:
        selected_term = current_term
    try:
        validate_academic_year(selected_academic_year)
    except ValidationError:
        selected_academic_year = current_academic_year

    base_students = _staff_student_queryset(request.user)
    profile = getattr(request.user, 'profile', None)
    class_options = list(
        base_students.exclude(class_name__isnull=True)
        .exclude(class_name='')
        .order_by('class_name')
        .values_list('class_name', flat=True)
        .distinct()
    )
    if selected_class and selected_class in class_options:
        base_students = base_students.filter(class_name=selected_class)
    elif selected_class:
        selected_class = ''
    if search:
        base_students = base_students.filter(
            Q(first_name__icontains=search)
            | Q(other_names__icontains=search)
            | Q(last_name__icontains=search)
            | Q(student_id__icontains=search)
        )

    students = list(base_students.order_by('last_name', 'first_name', 'student_id'))
    rows = []
    for student in students:
        if selected_term == 'session':
            summary = _session_summary_for_student(student, selected_academic_year)
            average_score = summary['overall_average']
            grade_count = summary['subject_count']
        else:
            grades = Grade.objects.filter(
                student=student,
                academic_year=selected_academic_year,
                term=selected_term,
            )
            grade_count = grades.count()
            average_score = (sum(grade.marks for grade in grades) / grade_count) if grade_count else None
        rows.append({
            'student': student,
            'average': average_score,
            'grade_count': grade_count,
        })

    sorters = {
        'name': lambda row: (row['student'].last_name, row['student'].first_name, row['student'].student_id),
        'class': lambda row: (row['student'].class_name or '', row['student'].last_name, row['student'].first_name),
        'student_id': lambda row: (row['student'].student_id, row['student'].last_name, row['student'].first_name),
        'average_desc': lambda row: (row['average'] is not None, row['average'] or 0),
        'average_asc': lambda row: (row['average'] is None, row['average'] or 0),
    }
    rows.sort(key=sorters.get(sort, sorters['name']), reverse=(sort == 'average_desc'))

    query = {
        'academic_year': selected_academic_year,
        'term': selected_term,
    }
    if selected_class:
        query['class'] = selected_class
    if search:
        query['q'] = search

    return render(request, 'grades/staff_results.html', {
        'rows': rows,
        'class_options': class_options,
        'term_options': [{'value': value, 'label': label} for value, label in TERM_CHOICES],
        'sort_options': [
            {'value': 'name', 'label': 'Name A-Z'},
            {'value': 'class', 'label': 'Class'},
            {'value': 'student_id', 'label': 'Student ID'},
            {'value': 'average_desc', 'label': 'Average High-Low'},
            {'value': 'average_asc', 'label': 'Average Low-High'},
        ],
        'selected_academic_year': selected_academic_year,
        'selected_term': selected_term,
        'selected_term_display': _term_display(selected_term),
        'selected_class': selected_class,
        'search': search,
        'sort': sort,
        'student_count': len(rows),
        'profile': profile,
        'query_string': urlencode(query),
    })


@login_required
@class_teacher_or_admin_required
def session_summary_entry(request, student_pk):
    current_academic_year, _current_term = _current_period()
    selected_academic_year = request.GET.get('academic_year') or request.POST.get('academic_year') or current_academic_year
    try:
        validate_academic_year(selected_academic_year)
    except ValidationError:
        selected_academic_year = current_academic_year

    student = get_object_or_404(_staff_student_queryset(request.user), pk=student_pk)
    term_labels = dict(TERM_CHOICES)
    rows = _session_entry_rows(student, selected_academic_year)

    if request.method == 'POST':
        created_count = 0
        errors = []
        valid_input_names = {
            term_data['input_name']: (row['subject'], term, term_data['subject'])
            for row in rows
            for term, term_data in row['terms'].items()
            if term_data['input_name']
        }

        with transaction.atomic():
            for field_name, raw_value in request.POST.items():
                if field_name not in valid_input_names:
                    continue
                raw_value = (raw_value or '').strip()
                if raw_value == '':
                    continue
                subject_label, term, subject = valid_input_names[field_name]
                try:
                    total = float(raw_value)
                except ValueError:
                    errors.append(f'{subject_label} {term_labels.get(term, term)} must be a number.')
                    continue
                if total < 0 or total > 100:
                    errors.append(f'{subject_label} {term_labels.get(term, term)} must be between 0 and 100.')
                    continue

                _grade, created = Grade.objects.get_or_create(
                    student=student,
                    subject=subject,
                    academic_year=selected_academic_year,
                    term=term,
                    defaults={
                        'homework': 0,
                        'class_work': 0,
                        'project': 0,
                        'first_test': 0,
                        'midterm_test': 0,
                        'exam': total,
                        'remarks': 'Total entered from session summary for a missing term result.',
                    },
                )
                if created:
                    created_count += 1

        for error in errors:
            messages.error(request, error)
        if created_count:
            messages.success(request, f'Added {created_count} missing term total(s) to the session summary.')
        elif not errors:
            messages.info(request, 'No missing term totals were entered.')

        return redirect(f"{reverse('session_summary_entry', args=[student.pk])}?academic_year={selected_academic_year}")

    return render(request, 'grades/session_summary_entry.html', {
        'student': student,
        'rows': rows,
        'selected_academic_year': selected_academic_year,
        'term_labels': term_labels,
        'academic_terms': ['first_term', 'second_term', 'third_term'],
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
        subject_options = list(_subject_teacher_subjects(profile, current_term))
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
    assigned_subjects = _subject_teacher_subjects(profile, current_term)
    subject_pk = request.GET.get('subject') or request.POST.get('subject')
    selected_subject = None
    requested_subject = Subject.objects.filter(pk=subject_pk).first() if subject_pk else None
    if requested_subject:
        requested_subject = _resolve_subject_for_term(requested_subject, current_term)
    if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
        selected_subject = assigned_subjects.filter(pk=requested_subject.pk).first() if requested_subject else assigned_subjects.first()

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

    subject_options = Subject.objects.none()

    if selected_student:
        subject_options = _term_subjects_for_student(selected_student, current_term)

        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            subject_options = subject_options.filter(pk__in=assigned_subjects)

        if requested_subject:
            selected_subject = subject_options.filter(pk=requested_subject.pk).first()
        elif profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            selected_subject = subject_options.filter(pk=selected_subject.pk).first() if selected_subject else subject_options.first()
    elif profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
        subject_options = assigned_subjects
        selected_subject = assigned_subjects.filter(pk=requested_subject.pk).first() if requested_subject else assigned_subjects.first()

    existing_grade = None
    if selected_student and selected_subject:
        existing_grade = Grade.objects.filter(
            student=selected_student,
            subject=selected_subject,
            academic_year=current_academic_year,
            term=current_term,
        ).first()

    if request.method == 'POST':
        form = GradeEntryForm(request.POST, instance=existing_grade)

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
            form.fields['student'].initial = selected_student.pk
            form.fields['student'].widget = HiddenInput()
            form.fields['subject'].queryset = subject_options

        if selected_subject:
            form.fields['subject'].queryset = Subject.objects.filter(pk=selected_subject.pk)
            form.fields['subject'].initial = selected_subject.pk
            form.fields['subject'].widget = HiddenInput()

        if form.is_valid():
            data = form.cleaned_data
            grade, created = Grade.objects.update_or_create(
                student=data['student'],
                subject=data['subject'],
                academic_year=current_academic_year,
                term=current_term,
                defaults={
                    'homework': data['homework'],
                    'class_work': data['class_work'],
                    'project': data['project'],
                    'first_test': data['first_test'],
                    'midterm_test': data['midterm_test'],
                    'exam': data['exam'],
                    'remarks': data.get('remarks') or '',
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
        if existing_grade:
            form = GradeEntryForm(instance=existing_grade)
        else:
            form = GradeEntryForm(initial={
                'student': selected_student,
                'subject': selected_subject,
            })

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
            form.fields['subject'].queryset = subject_options
            if selected_subject:
                form.fields['subject'].queryset = Subject.objects.filter(pk=selected_subject.pk)
                form.fields['subject'].initial = selected_subject.pk
                form.fields['subject'].widget = HiddenInput()

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
        'subject_options': subject_options,
        'is_subject_teacher': profile and profile.role == Profile.ROLE_SUBJECT_TEACHER,
    })


@login_required
@class_teacher_or_admin_required
def enter_behavioral_assessments(request):
    current_academic_year, current_term = _current_period()
    profile = getattr(request.user, 'profile', None)

    if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
        students_for_select = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    else:
        students_for_select = Student.objects.all().order_by('last_name')

    selected_student = None
    sel_student_pk = request.GET.get('student') or request.POST.get('student')
    if sel_student_pk:
        try:
            selected_student = students_for_select.get(pk=sel_student_pk)
        except Exception:
            selected_student = None

    if request.method == 'POST':
        form = BehavioralGradeEntryForm(request.POST)
        if profile and profile.role == 'class_teacher' and profile.assigned_class:
            form.fields['student'].queryset = students_for_select

        if selected_student:
            form.fields['student'].queryset = Student.objects.filter(pk=selected_student.pk)
            form.fields['student'].initial = selected_student.pk
            form.fields['student'].widget = HiddenInput()

        submitted_student = form.fields['student'].queryset.filter(pk=request.POST.get('student')).first()
        if submitted_student:
            existing_report = BehavioralGrade.objects.filter(
                student=submitted_student,
                academic_year=current_academic_year,
                term=current_term,
            ).first()
            if existing_report:
                form.instance = existing_report

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
            if selected_student:
                return redirect(f"{request.path}?student={selected_student.pk}")
            return redirect('enter_behavioral_assessments')
    else:
        existing_report = None
        if selected_student:
            existing_report = BehavioralGrade.objects.filter(
                student=selected_student,
                academic_year=current_academic_year,
                term=current_term,
            ).first()

        if existing_report:
            form = BehavioralGradeEntryForm(instance=existing_report)
        else:
            form = BehavioralGradeEntryForm()

        if profile and profile.role == 'class_teacher' and profile.assigned_class:
            form.fields['student'].queryset = students_for_select

        if selected_student:
            form.fields['student'].queryset = Student.objects.filter(pk=selected_student.pk)
            form.fields['student'].initial = selected_student.pk
            form.fields['student'].widget = HiddenInput()

    reports = BehavioralGrade.objects.filter(academic_year=current_academic_year, term=current_term).select_related('student').order_by('student__last_name')
    if profile and profile.role == 'class_teacher' and profile.assigned_class:
        reports = reports.filter(student__class_name=profile.assigned_class)

    return render(request, 'grades/enter_behavioral_assessments.html', {
        'form': form,
        'reports': reports,
        'current_term': current_term,
        'current_academic_year': current_academic_year,
        'current_term_display': _term_display(current_term),
        'students': students_for_select,
        'selected_student': selected_student,
    })


@login_required
@class_teacher_or_admin_required
def manage_students(request):
    profile = getattr(request.user, 'profile', None)
    selected_class = request.GET.get('class') or ''
    search = (request.GET.get('q') or '').strip()
    sort = request.GET.get('sort') or 'name'
    if profile and profile.role == 'class_teacher' and profile.assigned_class:
        students = Student.objects.filter(class_name=profile.assigned_class)
    else:
        students = Student.objects.all()

    class_options = list(
        students.exclude(class_name__isnull=True)
        .exclude(class_name='')
        .order_by('class_name')
        .values_list('class_name', flat=True)
        .distinct()
    )
    if selected_class and selected_class in class_options:
        students = students.filter(class_name=selected_class)
    elif selected_class:
        selected_class = ''
    if search:
        students = students.filter(
            Q(first_name__icontains=search)
            | Q(other_names__icontains=search)
            | Q(last_name__icontains=search)
            | Q(student_id__icontains=search)
        )
    ordering = {
        'name': ['last_name', 'first_name', 'student_id'],
        'class': ['class_name', 'last_name', 'first_name'],
        'student_id': ['student_id', 'last_name', 'first_name'],
        'registered_newest': ['-enrollment_date', 'last_name', 'first_name'],
        'registered_oldest': ['enrollment_date', 'last_name', 'first_name'],
    }.get(sort, ['last_name', 'first_name', 'student_id'])
    students = students.order_by(*ordering)

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
        'class_options': class_options,
        'selected_class': selected_class,
        'search': search,
        'sort': sort,
        'sort_options': [
            {'value': 'name', 'label': 'Name A-Z'},
            {'value': 'class', 'label': 'Class'},
            {'value': 'student_id', 'label': 'Student ID'},
            {'value': 'registered_newest', 'label': 'Newest Registered'},
            {'value': 'registered_oldest', 'label': 'Oldest Registered'},
        ],
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
    session_summary = None
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
            if selected_term == 'session':
                session_summary = _session_summary_for_student(student, selected_academic_year)
            else:
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
        'session_summary': session_summary,
        'selected_academic_year': selected_academic_year,
        'selected_term': selected_term,
        'selected_term_display': _term_display(selected_term) if selected_term else '',
        'academic_year_options': academic_year_options,
        'term_options': term_options,
        'result_access_allowed': result_access_allowed,
        'publication': publication,
        'announcements': _visible_announcements_for_user(request.user),
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

def _wrap_text(text, font_name, font_size, max_width):
    """Break text into lines that each fit within max_width."""
    words = (text or '').split()
    lines = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


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


def _session_summary_for_student(student, academic_year):
    term_labels = dict(TERM_CHOICES)
    academic_terms = ['first_term', 'second_term', 'third_term']
    grades = (
        Grade.objects.filter(
            student=student,
            academic_year=academic_year,
            term__in=academic_terms,
        )
        .select_related('subject')
        .order_by('subject__name', 'term')
    )

    subject_rows = {}
    for grade in grades:
        key = _subject_family_key(grade.subject)
        if key not in subject_rows:
            subject_rows[key] = {
                'subject': grade.subject.name,
                'terms': {},
            }
        subject_rows[key]['terms'][grade.term] = grade.marks

    rows = []
    for item in subject_rows.values():
        marks = [item['terms'][term] for term in academic_terms if term in item['terms']]
        average = (sum(marks) / len(marks)) if marks else None
        rows.append({
            'subject': item['subject'],
            'first_term': item['terms'].get('first_term'),
            'second_term': item['terms'].get('second_term'),
            'third_term': item['terms'].get('third_term'),
            'average': average,
            'letter': _average_letter_grade(average or 0),
        })

    valid_averages = [row['average'] for row in rows if row['average'] is not None]
    overall_average = (sum(valid_averages) / len(valid_averages)) if valid_averages else None
    return {
        'rows': rows,
        'overall_average': overall_average,
        'subject_count': len(rows),
        'promotion_decision': 'Promoted' if overall_average is not None and overall_average >= 50 else 'Not Promoted',
        'term_labels': term_labels,
    }


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

def _render_single_page_pdf(draw_content, min_scale=0.55, bottom_buffer=6 * mm):
    """Render draw_content(cv) onto a single A4 page, auto-scaling down
    uniformly if the content would overflow the bottom margin."""
    width, height = A4
    margin = 18 * mm

    probe_buf = BytesIO()
    probe_cv = canvas.Canvas(probe_buf, pagesize=A4)
    final_y = draw_content(probe_cv)

    needed_bottom = margin + bottom_buffer
    scale = 1.0
    if final_y < needed_bottom:
        content_height = (height - margin) - final_y
        available_height = (height - margin) - needed_bottom
        if content_height > 0:
            scale = max(min_scale, available_height / content_height)

    buf = BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    if scale < 1.0:
        anchor_x, anchor_y = width / 2, height - margin
        cv.saveState()
        cv.translate(anchor_x, anchor_y)
        cv.scale(scale, scale)
        cv.translate(-anchor_x, -anchor_y)
        draw_content(cv)
        cv.restoreState()
    else:
        draw_content(cv)

    cv.showPage()
    cv.save()
    return buf.getvalue()

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
    
    def _draw(cv):
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

        line_height = 3.3 * mm
        max_text_width = right_col_w - 6 * mm

        teacher_text = (teacher_comment or '').strip()
        head_text = (head_comment or '').strip()
        teacher_lines = _wrap_text(teacher_text, 'Helvetica', 7.5, max_text_width) if teacher_text else ['_' * 36]
        head_lines = _wrap_text(head_text, 'Helvetica', 7.5, max_text_width) if head_text else ['_' * 36]

        teacher_block_h = 10.5 * mm + len(teacher_lines) * line_height
        head_block_h = 10.5 * mm + len(head_lines) * line_height
        comment_top = y - key_h - 3 * mm
        comment_h = max(behavior_height - key_h - 3 * mm, teacher_block_h + head_block_h + 4 * mm, 22 * mm)
        _rounded_rect(cv, right_col_x, comment_top - comment_h, right_col_w, comment_h, 3, fill=_WHITE, stroke=_GREY)

        cv.setFont('Helvetica-Bold', 7.5)
        cv.setFillColor(_RED)
        cv.drawString(right_col_x + 3 * mm, comment_top - 5 * mm, "CLASS TEACHER'S COMMENT")
        cv.setFont('Helvetica', 7.5)
        cv.setFillColor(_DARK)
        for index, line in enumerate(teacher_lines):
            cv.drawString(right_col_x + 3 * mm, comment_top - 10.5 * mm - index * line_height, line)

        head_label_y = comment_top - 10.5 * mm - len(teacher_lines) * line_height - 4 * mm
        cv.setFont('Helvetica-Bold', 7.5)
        cv.setFillColor(_RED)
        cv.drawString(right_col_x + 3 * mm, head_label_y, "HEAD TEACHER'S COMMENT")
        cv.setFont('Helvetica', 7.5)
        cv.setFillColor(_DARK)
        for index, line in enumerate(head_lines):
            cv.drawString(right_col_x + 3 * mm, head_label_y - 5.5 * mm - index * line_height, line)

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
        return y

    return _render_single_page_pdf(_draw)


def _term_report_pdf_bytes(student, selected_academic_year, selected_term):
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
    return pdf_bytes


def build_session_summary_report(*, student, academic_year):
    summary = _session_summary_for_student(student, academic_year)

    def _draw(cv):
        width, height = A4
        margin = 18 * mm
        content_width = width - 2 * margin
        y = height - margin

        _rounded_rect(cv, margin, y - 30 * mm, content_width, 30 * mm, 6, fill=_RED)
        cv.setFillColor(_WHITE)
        cv.setFont('Helvetica-Bold', 15)
        cv.drawCentredString(width / 2, y - 11 * mm, 'CORINASIA INTERNATIONAL ACADEMY')
        cv.setFont('Helvetica-Bold', 11)
        cv.drawCentredString(width / 2, y - 22 * mm, f'{academic_year} SESSION SUMMARY RESULT')
        y -= 36 * mm

        _rounded_rect(cv, margin, y - 28 * mm, content_width, 28 * mm, 4, fill=_LIGHT, stroke=_GREY)
        cv.setFillColor(_DARK)
        cv.setFont('Helvetica-Bold', 8)
        cv.drawString(margin + 4 * mm, y - 8 * mm, 'NAME:')
        cv.drawString(margin + 4 * mm, y - 17 * mm, 'STUDENT ID:')
        cv.drawString(margin + content_width / 2, y - 8 * mm, 'CLASS:')
        cv.drawString(margin + content_width / 2, y - 17 * mm, 'SESSION AVERAGE:')
        cv.setFont('Helvetica', 8)
        cv.drawString(margin + 30 * mm, y - 8 * mm, student.full_name)
        cv.drawString(margin + 30 * mm, y - 17 * mm, student.student_id)
        cv.drawString(margin + content_width / 2 + 32 * mm, y - 8 * mm, student.class_name or 'Not assigned')
        overall_text = f"{summary['overall_average']:.1f}" if summary['overall_average'] is not None else 'No scores'
        cv.drawString(margin + content_width / 2 + 42 * mm, y - 17 * mm, overall_text)
        y -= 36 * mm

        rows = [['SUBJECT', 'FIRST TERM', 'SECOND TERM', 'THIRD TERM', 'SESSION AVG', 'GRADE']]
        for row in summary['rows']:
            rows.append([
                row['subject'],
                '-' if row['first_term'] is None else f"{row['first_term']:.0f}",
                '-' if row['second_term'] is None else f"{row['second_term']:.0f}",
                '-' if row['third_term'] is None else f"{row['third_term']:.0f}",
                '-' if row['average'] is None else f"{row['average']:.1f}",
                row['letter'],
            ])
        if len(rows) == 1:
            rows.append(['No recorded scores for this session', '-', '-', '-', '-', '-'])

        table = Table(rows, colWidths=[62 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm, 18 * mm])
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), _RED),
            ('TEXTCOLOR', (0, 0), (-1, 0), _WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.4, _GREY),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [_WHITE, colors.HexColor('#fdf6f0')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])
        for row_index, row in enumerate(summary['rows'], start=1):
            table_style.add('TEXTCOLOR', (-1, row_index), (-1, row_index), _letter_color(row['letter']))
            table_style.add('FONTNAME', (-1, row_index), (-1, row_index), 'Helvetica-Bold')
        table.setStyle(table_style)
        _table_width, table_height = table.wrapOn(cv, content_width, height)
        table.drawOn(cv, margin, y - table_height)
        y -= table_height + 10 * mm

        _rounded_rect(cv, margin, y - 18 * mm, content_width, 18 * mm, 4, fill=_LIGHT, stroke=_GREY)
        cv.setFillColor(_RED)
        cv.setFont('Helvetica-Bold', 9)
        cv.drawString(margin + 4 * mm, y - 7 * mm, 'PROMOTION DECISION:')
        cv.setFillColor(_DARK)
        cv.setFont('Helvetica-Bold', 10)
        cv.drawString(margin + 48 * mm, y - 7 * mm, summary['promotion_decision'])
        cv.setFont('Helvetica', 7)
        cv.drawString(margin + 4 * mm, y - 14 * mm, 'Decision is based on the average of first, second and third term subject results.')
        y -= 18 * mm
        return y

    return _render_single_page_pdf(_draw)

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
    pdf_bytes = _term_report_pdf_bytes(student, selected_academic_year, selected_term)

    safe_student_id = student.student_id.replace('/', '-')
    safe_year = selected_academic_year.replace('/', '-')
    filename = f'{safe_student_id}_{safe_year}_{selected_term}_report.pdf'

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@class_teacher_or_admin_required
def staff_report_pdf(request, student_pk):
    student = get_object_or_404(_staff_student_queryset(request.user), pk=student_pk)
    selected_academic_year = request.GET.get('academic_year') or _current_period()[0]
    selected_term = request.GET.get('term') or _current_period()[1]
    valid_terms = {value for value, _label in TERM_CHOICES}
    if selected_term not in valid_terms:
        selected_term = _current_period()[1]
    try:
        validate_academic_year(selected_academic_year)
    except ValidationError:
        selected_academic_year = _current_period()[0]

    if selected_term == 'session':
        pdf_bytes = build_session_summary_report(student=student, academic_year=selected_academic_year)
    else:
        pdf_bytes = _term_report_pdf_bytes(student, selected_academic_year, selected_term)

    safe_student_id = student.student_id.replace('/', '-')
    safe_year = selected_academic_year.replace('/', '-')
    filename = f'{safe_student_id}_{safe_year}_{selected_term}_staff_report.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
