from django.test import TestCase
from django.contrib.auth.models import User
from .models import Student, Subject, Grade


class GradeModelTest(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            student_id='12345',
            first_name='John',
            last_name='Doe'
        )
        self.subject = Subject.objects.create(
            code='MATH101',
            name='Mathematics'
        )

    def test_letter_grade_a(self):
        grade = Grade.objects.create(
            student=self.student,
            subject=self.subject,
            marks=95
        )
        self.assertEqual(grade.letter_grade, 'A')

    def test_letter_grade_b(self):
        grade = Grade.objects.create(
            student=self.student,
            subject=self.subject,
            marks=85
        )
        self.assertEqual(grade.letter_grade, 'B')

    def test_letter_grade_f(self):
        grade = Grade.objects.create(
            student=self.student,
            subject=self.subject,
            marks=45
        )
        self.assertEqual(grade.letter_grade, 'F')


class StudentViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student1', password='pass')
        self.student = Student.objects.create(
            student_id='student1',
            first_name='Jane',
            last_name='Smith'
        )

    def test_student_dashboard_requires_login(self):
        response = self.client.get('/student/dashboard/')
        self.assertEqual(response.status_code, 302)  # Redirect to login
