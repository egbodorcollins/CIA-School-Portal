from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Student, Grade


def home(request):
    return render(request, 'grades/home.html')


@login_required
def teacher_dashboard(request):
    if not request.user.is_staff:
        messages.warning(request, 'Teacher access only. Please sign in with a teacher account.')
        return redirect('student_dashboard')

    students = Student.objects.all().order_by('last_name')
    return render(request, 'grades/teacher_dashboard.html', {'students': students})


@login_required
def student_dashboard(request):
    if request.user.is_staff:
        return redirect('teacher_dashboard')

    student = None
    grades = []
    try:
        student = Student.objects.get(student_id=request.user.username)
        grades = Grade.objects.filter(student=student).select_related('subject')
    except Student.DoesNotExist:
        messages.info(request, 'No student profile was found for your username. Please contact administration.')

    return render(request, 'grades/student_dashboard.html', {
        'student': student,
        'grades': grades,
    })
