from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .forms import AUTO_STUDENT_PASSWORD, StudentSignUpForm, generate_student_id
from .models import Student, Subject, TermSetting


class StudentRegistrationTests(TestCase):
    def setUp(self):
        self.form_data = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'class_name': 'Nursery 2',
            'nationality': 'Nigeria',
            'state_of_origin': 'Abuja',
            'club_and_society': '',
            'sport_house': '',
            'date_of_birth': '2010-05-01',
            'password1': 'Strongpass123!',
            'password2': 'Strongpass123!',
        }

    @patch('grades.forms.timezone.now')
    def test_signup_creates_user_and_student_with_generated_id(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        form = StudentSignUpForm(data=self.form_data)

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.username, 'CIA/N22026/0001')
        self.assertTrue(User.objects.filter(username='CIA/N22026/0001').exists())
        self.assertTrue(Student.objects.filter(student_id='CIA/N22026/0001', class_name='Nursery 2').exists())

    @patch('grades.forms.timezone.now')
    def test_generated_student_id_increments_hex_sequence(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        Student.objects.create(
            student_id='CIA/B52026/0001',
            first_name='Existing',
            last_name='Student',
            class_name='Basic 5',
        )

        generated_id = generate_student_id('Basic 5')

        self.assertEqual(generated_id, 'CIA/B52026/0002')

    def test_unsupported_class_name_is_rejected(self):
        form = StudentSignUpForm(data={**self.form_data, 'class_name': 'Form 10'})

        self.assertFalse(form.is_valid())
        self.assertIn('class_name', form.errors)

    def test_generate_student_id_rejects_unknown_class(self):
        with self.assertRaises(ValidationError):
            generate_student_id('Unknown Class')


class PortalRenderingTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='teacher',
            password='pass12345',
            first_name='Grace',
            last_name='Hopper',
        )
        self.staff_user.is_staff = True
        self.staff_user.save()

    def test_teacher_dashboard_uses_base_template(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'grades/base.html')
        self.assertContains(response, 'Teacher Dashboard')
        self.assertContains(response, 'Grace Hopper')
        self.assertContains(response, 'account-avatar')
        self.assertContains(response, 'Change Password')
        self.assertContains(response, 'Log Out')
        self.assertContains(response, 'Term: First Term')
        self.assertContains(response, 'Date:')

    def test_set_current_term_redirects_to_admin_dashboard(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('set_current_term'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin:grades_termsetting_changelist'))

    def test_password_change_page_renders(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('password_change'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Change Password')

    def test_register_student_page_renders(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('register_student'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'grades/register_student.html')
        self.assertContains(response, 'Register New Student')

    def test_register_student_invalid_post_renders_errors(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.post(reverse('register_student'), data={})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'grades/register_student.html')
        self.assertContains(response, 'This field is required')

    @patch('grades.forms.timezone.now')
    def test_register_student_valid_post_creates_profile(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        self.client.login(username='teacher', password='pass12345')

        response = self.client.post(reverse('register_student'), data={
            'first_name': 'Mary',
            'last_name': 'Adewale',
            'class_name': 'Basic 5',
            'nationality': 'Nigeria',
            'state_of_origin': 'Lagos',
            'club_and_society': '',
            'sport_house': '',
            'date_of_birth': '2011-01-01',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Student profile created successfully')
        self.assertTrue(Student.objects.filter(student_id='CIA/B52026/0001', first_name='Mary', last_name='Adewale').exists())
        self.assertTrue(User.objects.filter(username='CIA/B52026/0001').exists())
        self.assertTrue(User.objects.get(username='CIA/B52026/0001').check_password(AUTO_STUDENT_PASSWORD))

    def test_behavioral_assessment_template_renders_real_fields(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('enter_behavioral_assessments'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Punctuality')
        self.assertContains(response, 'Relationship with Staff')
        self.assertContains(response, 'Times Present')
        self.assertNotContains(response, 'behavioral_score')


class DeleteStudentTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username='teacher', password='pass12345')
        self.staff_user.is_staff = True
        self.staff_user.save()
        self.student = Student.objects.create(
            student_id='CIA/B52026/0001',
            first_name='John',
            last_name='Doe',
            class_name='Basic 5',
        )

    def test_delete_student_requires_post(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('delete_student', args=[self.student.student_id]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Student.objects.filter(student_id=self.student.student_id).exists())

    def test_delete_student_via_post(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.post(reverse('delete_student', args=[self.student.student_id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Student.objects.filter(student_id=self.student.student_id).exists())

    def test_manage_students_page_renders_delete_form_for_slash_ids(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('manage_students'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('delete_student', args=[self.student.student_id]))


class PromoteClassTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username='admin', password='pass12345')
        self.staff_user.is_staff = True
        self.staff_user.save()
        TermSetting.objects.create(current_term='first_term')
        self.old_subject = Subject.objects.create(code='ENG B51', name='English Studies')
        self.new_subject = Subject.objects.create(code='ENG B61', name='English Studies')
        self.second_new_subject = Subject.objects.create(code='MAT B61', name='Mathematics')
        self.student = Student.objects.create(
            student_id='CIA/B52026/0001',
            first_name='John',
            last_name='Doe',
            class_name='Basic 5',
        )
        self.student.subjects.add(self.old_subject)

    def test_promote_class_requires_post(self):
        self.client.login(username='admin', password='pass12345')

        response = self.client.get(reverse('promote_class'))

        self.assertEqual(response.status_code, 405)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')

    def test_promote_class_requires_confirmation(self):
        self.client.login(username='admin', password='pass12345')

        response = self.client.post(reverse('promote_class'), data={'from_class': 'Basic 5'})

        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')
        self.assertEqual(list(self.student.subjects.values_list('code', flat=True)), ['ENG B51'])

    def test_promote_class_moves_students_and_resets_subjects(self):
        self.client.login(username='admin', password='pass12345')

        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'Basic 5',
            'confirm': 'yes',
        })

        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 6')
        self.assertCountEqual(
            self.student.subjects.values_list('code', flat=True),
            ['ENG B61', 'MAT B61'],
        )
        self.assertNotIn(self.old_subject, self.student.subjects.all())

    def test_promote_class_rejects_class_without_progression(self):
        self.client.login(username='admin', password='pass12345')

        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'SSS 3',
            'confirm': 'yes',
        })

        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')
