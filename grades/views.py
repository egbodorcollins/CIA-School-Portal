from io import BytesIO
from datetime import timedelta

from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Student, Grade, BehavioralGrade
from .forms import StudentSignUpForm


class RateLimitedLoginView(LoginView):
    template_name = 'grades/login.html'
    redirect_authenticated_user = True

    # @ratelimit(key='ip', rate='5/m', method='POST')  # Disabled for development
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


def home(request):
    return render(request, 'grades/home.html')


@login_required
@user_passes_test(lambda u: u.is_staff)
def register_student(request):
    if request.method == 'POST':
        form = StudentSignUpForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Student account created successfully.')
            return redirect('teacher_dashboard')
    else:
        form = StudentSignUpForm()

    return render(request, 'grades/register_student_modal.html', {
        'form': form,
    })


def logout_view(request):
    logout(request)
    request.session.flush()
    messages.success(request, 'You have successfully logged out.')
    return redirect('home')


@login_required
def teacher_dashboard(request):
    if not request.user.is_staff:
        messages.warning(request, 'Teacher access only. Please sign in with a teacher account.')
        return redirect('student_dashboard')

    students = Student.objects.all().order_by('last_name')
    form = StudentSignUpForm()
    return render(request, 'grades/teacher_dashboard.html', {'students': students, 'form': form})


@login_required
def student_dashboard(request):
    if request.user.is_staff:
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
    response['Content-Disposition'] = f'attachment; filename="{student.student_id}_{latest_term}_report.pdf"'

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

    assessment_data = [['SUBJECT', 'CLASS', 'PROJ', 'TEST', 'C.A', 'EXAMS', 'TOTAL', 'GRADE', 'POSITION']]
    for idx, grade in enumerate(selected_grades, start=1):
        assessment_data.append([
            grade.subject.name,
            '15',
            '5',
            '20',
            '40',
            '20',
            f'{grade.marks:.0f}',
            grade.letter_grade,
            str(idx),
        ])

    total_marks = sum(g.marks for g in selected_grades)
    assessment_data.append(['TOTAL', '180', '57', '226', '463', '20', f'{total_marks:.0f}', '', ''])
    assessment_table = Table(assessment_data, colWidths=[120, 35, 35, 35, 35, 45, 40, 35, 35])
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
