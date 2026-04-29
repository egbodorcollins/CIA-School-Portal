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

from .models import Student, Grade, BehavioralGrade, TermSetting, Profile, Activity, Subject
from django.db.models import Q
from .forms import StudentSignUpForm, GradeEntryForm, BehavioralGradeEntryForm, TeacherCreationForm, get_class_code
from django.forms import HiddenInput


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
    if profile is None:
        messages.error(request, 'Unable to determine your role. Contact admin.')
        return redirect('teacher_dashboard')

    # Admins can create admins, class teachers and subject teachers.
    # Class teachers can only create subject teachers (and assign them subjects).
    if profile.role == Profile.ROLE_ADMIN:
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
    # If there is no Profile object but the user is marked as staff/superuser,
    # treat them as a teacher/admin for dashboard access. Create a Profile
    # record if missing to make template/context usage consistent.
    if profile is None:
        if request.user.is_superuser or getattr(request.user, 'is_staff', False):
            try:
                profile, _ = Profile.objects.get_or_create(user=request.user, defaults={'role': Profile.ROLE_ADMIN if request.user.is_superuser else Profile.ROLE_CLASS_TEACHER})
            except Exception:
                profile = None
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
    })


@login_required
@admin_required
def set_current_term(request):
    messages.info(request, 'Current academic term is managed in the Django admin dashboard.')
    return redirect('admin:grades_termsetting_changelist')


@login_required
@teacher_or_admin_required
def enter_academic_scores(request):
    current_term = TermSetting.get_current_term()
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
                term=data['term'],
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
        form = GradeEntryForm(initial={'term': current_term})
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
        grades = Grade.objects.filter(term=current_term, student=selected_student).select_related('student', 'subject').order_by('subject__name')
    else:
        grades = Grade.objects.filter(term=current_term).select_related('student', 'subject').order_by('student__last_name', 'subject__name')
        if profile and profile.role == Profile.ROLE_CLASS_TEACHER and profile.assigned_class:
            grades = grades.filter(student__class_name=profile.assigned_class)
        if profile and profile.role == Profile.ROLE_SUBJECT_TEACHER:
            grades = grades.filter(subject__in=profile.assigned_subjects.all())

    return render(request, 'grades/enter_academic_scores.html', {
        'form': form,
        'grades': grades,
        'current_term': current_term,
        'students': students_for_select,
        'selected_student': selected_student,
    })


@login_required
@class_teacher_or_admin_required
def enter_behavioral_assessments(request):
    current_term = TermSetting.get_current_term()
    profile = getattr(request.user, 'profile', None)

    if request.method == 'POST':
        form = BehavioralGradeEntryForm(request.POST)
        if profile and profile.role == 'class_teacher' and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)

        if form.is_valid():
            data = form.cleaned_data
            bg, created = BehavioralGrade.objects.update_or_create(
                student=data['student'],
                term=data['term'],
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
        form = BehavioralGradeEntryForm(initial={'term': current_term})
        if profile and profile.role == 'class_teacher' and profile.assigned_class:
            form.fields['student'].queryset = Student.objects.filter(class_name=profile.assigned_class)

    reports = BehavioralGrade.objects.filter(term=current_term).select_related('student').order_by('student__last_name')
    if profile and profile.role == 'class_teacher' and profile.assigned_class:
        reports = reports.filter(student__class_name=profile.assigned_class)

    return render(request, 'grades/enter_behavioral_assessments.html', {
        'form': form,
        'reports': reports,
        'current_term': current_term,
    })


@login_required
@class_teacher_or_admin_required
def manage_students(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'class_teacher' and profile.assigned_class:
        students = Student.objects.filter(class_name=profile.assigned_class).order_by('last_name')
    else:
        students = Student.objects.all().order_by('last_name')

    return render(request, 'grades/manage_students.html', {
        'students': students,
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
def student_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role != 'student':
        return redirect('teacher_dashboard')

    student = None
    grades = []
    behavioral_grades = []
    try:
        student = Student.objects.get(student_id=request.user.username)
        grades = Grade.objects.filter(student=student).select_related('subject')
        behavioral_grades = BehavioralGrade.objects.filter(student=student).order_by('-term')
    except Student.DoesNotExist:
        messages.info(request, 'No student profile was found for your username. Please contact administration.')

    return render(request, 'grades/student_dashboard.html', {
        'student': student,
        'grades': grades,
        'behavioral_grades': behavioral_grades,
    })


@login_required
def report_card_pdf(request):
    student = None
    try:
        student = Student.objects.get(student_id=request.user.username)
    except Student.DoesNotExist:
        messages.error(request, 'Unable to generate report: student profile not found.')
        return redirect('student_dashboard')

    grades = Grade.objects.filter(student=student).select_related('subject')
    behavioral_grades = BehavioralGrade.objects.filter(student=student).order_by('-term')
    latest_term = 'first_term'
    term_order = {'first_term': 1, 'second_term': 2, 'third_term': 3}
    term_candidates = [grade.term for grade in grades] + [bg.term for bg in behavioral_grades]
    if term_candidates:
        latest_term = max(term_candidates, key=lambda t: term_order.get(t, 0))

    term_display = dict(Grade.TERM_CHOICES).get(latest_term, latest_term.replace('_', ' ').title())
    selected_grades = [grade for grade in grades if grade.term == latest_term]
    selected_behavior = behavioral_grades.filter(term=latest_term).first()

    class_students = Student.objects.filter(class_name=student.class_name)
    class_count = class_students.count()

    def average_score_for_student(student_obj):
        student_grades = Grade.objects.filter(student=student_obj, term=latest_term)
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
    response['Content-Disposition'] = f'attachment; filename="{safe_student_id}_{latest_term}_report.pdf"'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    styles = getSampleStyleSheet()
    heading = Paragraph('CORINAISA INTERNATIONAL ACADEMY', ParagraphStyle('Title', parent=styles['Title'], alignment=1, fontSize=18, leading=22, spaceAfter=10))
    subtitle = Paragraph(f'<b>{term_display.upper()} REPORT</b>', ParagraphStyle('Subtitle', parent=styles['Heading2'], alignment=1, fontSize=14, textColor=colors.red, spaceAfter=14))

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
