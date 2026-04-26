from django.shortcuts import render, redirect
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from .models import Student, Grade, BehavioralGrade
from .forms import StudentSignUpForm


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
