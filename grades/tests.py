from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .forms import AUTO_STUDENT_PASSWORD, StudentSignUpForm, generate_student_id
from .models import ClassPromotionRequest, Grade, Profile, Student, Subject, TermSetting


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

    def test_teacher_dashboard_links_to_promotion_tool_for_staff(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request Promotion')
        self.assertContains(response, f"{reverse('manage_students')}#end-of-year-promotion")

    def test_set_current_term_redirects_to_admin_dashboard(self):
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('set_current_term'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin:grades_termsetting_changelist'))

    def test_admin_dashboard_links_to_promotion_tool(self):
        admin_user = User.objects.create_superuser(
            username='superadmin',
            password='pass12345',
            email='admin@example.com',
        )
        self.client.login(username=admin_user.username, password='pass12345')

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End-of-Year Student Promotion Approvals')
        self.assertContains(response, f"{reverse('manage_students')}#end-of-year-promotion")

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

    def test_class_analytics_renders_aggregate_sections(self):
        TermSetting.objects.create(current_term='first_term')
        math = Subject.objects.create(code='MAT B51', name='Mathematics')
        english = Subject.objects.create(code='ENG B51', name='English Studies')
        ada = Student.objects.create(student_id='CIA/B52026/0001', first_name='Ada', last_name='King', class_name='Basic 5')
        ben = Student.objects.create(student_id='CIA/B52026/0002', first_name='Ben', last_name='Stone', class_name='Basic 5')
        Grade.objects.create(student=ada, subject=math, term='first_term', homework=5, class_work=10, project=5, first_test=10, midterm_test=10, exam=55)
        Grade.objects.create(student=ada, subject=english, term='first_term', homework=5, class_work=9, project=5, first_test=9, midterm_test=9, exam=50)
        Grade.objects.create(student=ben, subject=math, term='first_term', homework=3, class_work=7, project=4, first_test=7, midterm_test=7, exam=42)
        Grade.objects.create(student=ben, subject=english, term='second_term', homework=2, class_work=6, project=3, first_test=6, midterm_test=6, exam=35)
        self.client.login(username='teacher', password='pass12345')

        response = self.client.get(reverse('class_analytics'), {'class': 'Basic 5'})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'grades/class_analytics.html')
        self.assertContains(response, 'Class Analytics')
        self.assertContains(response, 'Subject Averages')
        self.assertContains(response, 'Grade Distribution')
        self.assertContains(response, 'Top 5 Students')
        self.assertContains(response, 'Bottom 5 Students')
        self.assertContains(response, 'Current Term vs Previous Terms')
        self.assertContains(response, 'Mathematics')
        self.assertContains(response, 'Ada King')
        self.assertContains(response, 'Ben Stone')


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
 
        self.teacher_user = User.objects.create_user(username='basic5teacher', password='pass12345')
        self.teacher_user.profile.role = Profile.ROLE_CLASS_TEACHER
        self.teacher_user.profile.assigned_class = 'Basic 5'
        self.teacher_user.profile.save()
 
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
 
        # A second student who will NOT be selected for promotion
        self.student2 = Student.objects.create(
            student_id='CIA/B52026/0002',
            first_name='Jane',
            last_name='Fail',
            class_name='Basic 5',
        )
        self.student2.subjects.add(self.old_subject)
 
    def test_promote_class_requires_post(self):
        self.client.login(username='admin', password='pass12345')
 
        response = self.client.get(reverse('promote_class'))
 
        self.assertEqual(response.status_code, 405)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')
 
    def test_promote_class_requires_confirmation(self):
        self.client.login(username='basic5teacher', password='pass12345')
 
        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'Basic 5',
            'student_pks': [self.student.pk],
            # 'confirm' intentionally omitted
        })
 
        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')
        self.assertFalse(ClassPromotionRequest.objects.exists())
 
    def test_promote_class_requires_at_least_one_student(self):
        self.client.login(username='basic5teacher', password='pass12345')
 
        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'Basic 5',
            'confirm': 'yes',
            # no student_pks
        })
 
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClassPromotionRequest.objects.exists())
 
    def test_class_teacher_requests_selected_students_promotion(self):
        self.client.login(username='basic5teacher', password='pass12345')
 
        # Teacher selects only student1 (student2 failed)
        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'Basic 5',
            'confirm': 'yes',
            'student_pks': [self.student.pk],
        })
 
        self.assertEqual(response.status_code, 302)
        # Students not moved yet — request is pending
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')
        request = ClassPromotionRequest.objects.get()
        self.assertEqual(request.from_class, 'Basic 5')
        self.assertEqual(request.to_class, 'Basic 6')
        self.assertEqual(request.status, ClassPromotionRequest.STATUS_PENDING)
        self.assertEqual(request.student_count, 1)
        self.assertIn(self.student.pk, request.student_pks)
        self.assertNotIn(self.student2.pk, request.student_pks)
 
    def test_class_teacher_cannot_request_another_class_promotion(self):
        self.client.login(username='basic5teacher', password='pass12345')
 
        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'Basic 4',
            'confirm': 'yes',
            'student_pks': [self.student.pk],
        })
 
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClassPromotionRequest.objects.exists())
 
    def test_admin_approval_moves_only_selected_students(self):
        """Only student1 was selected — student2 must stay in Basic 5."""
        promotion_request = ClassPromotionRequest.objects.create(
            from_class='Basic 5',
            to_class='Basic 6',
            requested_by=self.teacher_user,
            student_count=1,
            student_pks=[self.student.pk],   # only student1
        )
        self.client.login(username='admin', password='pass12345')
 
        response = self.client.post(reverse('approve_class_promotion', args=[promotion_request.pk]))
 
        self.assertEqual(response.status_code, 302)
 
        self.student.refresh_from_db()
        self.student2.refresh_from_db()
        promotion_request.refresh_from_db()
 
        # student1 promoted
        self.assertEqual(self.student.class_name, 'Basic 6')
        # student2 NOT promoted
        self.assertEqual(self.student2.class_name, 'Basic 5')
 
        self.assertEqual(promotion_request.status, ClassPromotionRequest.STATUS_APPROVED)
        self.assertEqual(promotion_request.approved_by, self.staff_user)
 
        # student1 re-enrolled in Basic 6 subjects
        self.assertCountEqual(
            self.student.subjects.values_list('code', flat=True),
            ['ENG B61', 'MAT B61']
        )
        # student2's subjects unchanged
        self.assertIn(self.old_subject, self.student2.subjects.all())
 
    def test_promote_class_rejects_class_without_progression(self):
        self.client.login(username='admin', password='pass12345')
 
        response = self.client.post(reverse('promote_class'), data={
            'from_class': 'SSS 3',
            'confirm': 'yes',
            'student_pks': [self.student.pk],
        })
 
        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.class_name, 'Basic 5')
        self.assertFalse(ClassPromotionRequest.objects.exists())
 
    def test_duplicate_pending_request_is_rejected(self):
        ClassPromotionRequest.objects.create(
            from_class='Basic 5',
            to_class='Basic 6',
            requested_by=self.teacher_user,
            student_count=1,
            student_pks=[self.student.pk],
        )
        self.client.login(username='basic5teacher', password='pass12345')
 
        self.client.post(reverse('promote_class'), data={
            'from_class': 'Basic 5',
            'confirm': 'yes',
            'student_pks': [self.student.pk],
        })
 