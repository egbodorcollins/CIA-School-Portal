from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import AUTO_STUDENT_PASSWORD, StudentSignUpForm, generate_student_id
from .models import BehavioralGrade, ClassPromotionRequest, Grade, Profile, ResultPublication, Student, Subject, TermSetting
from .views import _head_teacher_comment


class LoginTests(TestCase):
    def test_username_login_is_case_insensitive(self):
        User.objects.create_user(username='CIA/J12026/0001', password='pass12345')

        response = self.client.post(
            reverse('login'),
            {'username': 'cia/j12026/0001', 'password': 'pass12345'},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), User.objects.get(username='CIA/J12026/0001').pk)

    def test_default_password_login_redirects_to_password_change(self):
        User.objects.create_user(username='CIA/B52026/0001', password=AUTO_STUDENT_PASSWORD)

        response = self.client.post(
            reverse('login'),
            {'username': 'CIA/B52026/0001', 'password': AUTO_STUDENT_PASSWORD},
        )

        self.assertRedirects(response, reverse('password_change'))

    def test_non_default_password_login_redirects_home(self):
        User.objects.create_user(username='teacher', password='pass12345')

        response = self.client.post(
            reverse('login'),
            {'username': 'teacher', 'password': 'pass12345'},
        )

        self.assertRedirects(response, reverse('home'))


class StudentRegistrationTests(TestCase):
    def setUp(self):
        self.form_data = {
            'first_name': 'Jane',
            'other_names': 'Amaka',
            'last_name': 'Doe',
            'class_name': 'Nursery 2',
            'nationality': 'Nigeria',
            'state_of_origin': 'Abuja',
            'club_and_society': '',
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
        self.assertTrue(Student.objects.filter(student_id='CIA/N22026/0001', class_name='Nursery 2', other_names='Amaka').exists())

    @patch('grades.forms.timezone.now')
    def test_student_names_are_saved_in_sentence_case(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        form = StudentSignUpForm(data={
            **self.form_data,
            'first_name': 'jOHN',
            'other_names': 'mARY aNNE',
            'last_name': 'doe',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        student = Student.objects.get(student_id=user.username)
        self.assertEqual(student.first_name, 'John')
        self.assertEqual(student.other_names, 'Mary Anne')
        self.assertEqual(student.last_name, 'Doe')

    def test_duplicate_student_name_in_same_class_is_rejected(self):
        Student.objects.create(
            student_id='CIA/N22026/0001',
            first_name='John',
            last_name='Doe',
            class_name='Nursery 2',
        )

        form = StudentSignUpForm(data={
            **self.form_data,
            'first_name': 'john',
            'last_name': 'doe',
            'class_name': 'Nursery 2',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)
        self.assertEqual(Student.objects.filter(first_name='John', last_name='Doe', class_name='Nursery 2').count(), 1)

    def test_student_signup_form_collects_other_names_not_sport_house(self):
        form = StudentSignUpForm()

        self.assertIn('other_names', form.fields)
        self.assertFalse(form.fields['other_names'].required)
        self.assertNotIn('sport_house', form.fields)

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

    @patch('grades.forms.timezone.now')
    def test_preschool_class_teacher_can_register_student(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        teacher = User.objects.create_user(username='preschoolteacher', password='pass12345')
        teacher.profile.role = Profile.ROLE_CLASS_TEACHER
        teacher.profile.assigned_class = 'Pre-School'
        teacher.profile.save()
        self.client.login(username='preschoolteacher', password='pass12345')

        response = self.client.post(reverse('register_student'), data={
            'first_name': 'Tomi',
            'last_name': 'Ade',
            'nationality': 'Nigeria',
            'state_of_origin': 'Abuja',
            'club_and_society': '',
            'date_of_birth': '2021-05-01',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Student profile created successfully')
        self.assertTrue(Student.objects.filter(
            student_id='CIA/PS2026/0001',
            first_name='Tomi',
            last_name='Ade',
            class_name='Pre-School',
        ).exists())


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

    def test_portal_admin_header_links_to_result_releases(self):
        admin_user = User.objects.create_user(username='portaladmin', password='pass12345')
        admin_user.profile.role = Profile.ROLE_ADMIN
        admin_user.profile.save()
        self.client.login(username='portaladmin', password='pass12345')

        response = self.client.get(reverse('result_publications'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Result Releases')
        self.assertContains(response, reverse('result_publications'))
        self.assertNotContains(response, reverse('admin:index'))

    def test_result_release_page_updates_fee_and_approval(self):
        admin_user = User.objects.create_user(username='portaladmin', password='pass12345')
        admin_user.profile.role = Profile.ROLE_ADMIN
        admin_user.profile.save()
        student = Student.objects.create(
            student_id='CIA/B52026/0001',
            first_name='Gabriel',
            last_name='Zion',
            class_name='Basic 5',
        )
        self.client.login(username='portaladmin', password='pass12345')

        response = self.client.post(reverse('result_publications'), {
            'academic_year': '2025/2026',
            'term': 'second_term',
            'class': 'Basic 5',
            'student_pks': [student.pk],
            f'fee_cleared_{student.pk}': 'on',
            f'results_approved_{student.pk}': 'on',
        }, follow=True)

        publication = ResultPublication.objects.get(
            student=student,
            academic_year='2025/2026',
            term='second_term',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Result release settings updated for 1 student')
        self.assertTrue(publication.is_fee_cleared)
        self.assertTrue(publication.is_results_approved)
        self.assertEqual(publication.approved_by, admin_user)
        self.assertIsNotNone(publication.approved_at)
        self.assertTrue(publication.is_available)

    def test_student_cannot_access_result_release_page(self):
        student_user = User.objects.create_user(username='CIA/B52026/0001', password='pass12345')
        student_user.profile.role = Profile.ROLE_STUDENT
        student_user.profile.save()
        self.client.login(username='CIA/B52026/0001', password='pass12345')

        response = self.client.get(reverse('result_publications'))

        self.assertEqual(response.status_code, 302)

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

    @override_settings(DEBUG=True)
    def test_127_home_redirects_to_localhost(self):
        response = self.client.get('/', HTTP_HOST='127.0.0.1:8000')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'http://localhost:8000/')

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
        self.assertContains(response, 'Class Teacher Comment')
        self.assertNotContains(response, 'behavioral_score')

    def test_head_teacher_comment_is_based_on_average_grade(self):
        self.assertEqual(_head_teacher_comment(95), 'Excellent result. Keep up the outstanding performance.')
        self.assertEqual(_head_teacher_comment(85), 'Very good result. Keep working hard for excellence.')
        self.assertEqual(_head_teacher_comment(75), 'Good result. More consistent effort will bring higher achievement.')
        self.assertEqual(_head_teacher_comment(65), 'Satisfactory result. Greater focus and regular study are needed.')
        self.assertEqual(_head_teacher_comment(55), 'Fair result. Please improve study habits and seek support.')
        self.assertEqual(_head_teacher_comment(45), 'Poor result. Urgent improvement and close guidance are required.')

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

    def test_subject_teacher_dashboard_only_shows_subject_tools_and_rosters(self):
        math = Subject.objects.create(code='MAT B51', name='Mathematics')
        english = Subject.objects.create(code='ENG B51', name='English Studies')
        ada = Student.objects.create(student_id='CIA/B52026/0001', first_name='Ada', last_name='King', class_name='Basic 5')
        ben = Student.objects.create(student_id='CIA/B52026/0002', first_name='Ben', last_name='Stone', class_name='Basic 5')
        ada.subjects.add(math)
        ben.subjects.add(english)
        subject_teacher = User.objects.create_user(username='mathteacher', password='pass12345')
        subject_teacher.profile.role = Profile.ROLE_SUBJECT_TEACHER
        subject_teacher.profile.save()
        subject_teacher.profile.assigned_subjects.add(math)
        self.client.login(username='mathteacher', password='pass12345')

        response = self.client.get(reverse('teacher_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Subject Analytics')
        self.assertContains(response, 'Subject Rosters')
        self.assertContains(response, 'Mathematics')
        self.assertContains(response, 'Ada King')
        self.assertNotContains(response, 'Register New Student')
        self.assertNotContains(response, 'Enter Behavioral Assessments')
        self.assertNotContains(response, 'Manage Students')
        self.assertNotContains(response, 'Class Analytics')
        self.assertNotContains(response, 'Ben Stone')

    def test_subject_teacher_score_entry_is_limited_to_selected_subject_students(self):
        TermSetting.objects.create(current_term='first_term')
        math = Subject.objects.create(code='MAT B51', name='Mathematics')
        english = Subject.objects.create(code='ENG B51', name='English Studies')
        ada = Student.objects.create(student_id='CIA/B52026/0001', first_name='Ada', last_name='King', class_name='Basic 5')
        ben = Student.objects.create(student_id='CIA/B52026/0002', first_name='Ben', last_name='Stone', class_name='Basic 5')
        ada.subjects.add(math)
        ben.subjects.add(english)
        subject_teacher = User.objects.create_user(username='mathteacher', password='pass12345')
        subject_teacher.profile.role = Profile.ROLE_SUBJECT_TEACHER
        subject_teacher.profile.save()
        subject_teacher.profile.assigned_subjects.add(math)
        self.client.login(username='mathteacher', password='pass12345')

        response = self.client.get(reverse('enter_academic_scores'), {'subject': math.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select Subject')
        self.assertContains(response, 'Selected Subject')
        self.assertContains(response, 'Mathematics')
        self.assertContains(response, 'Ada King')
        self.assertNotContains(response, 'Ben Stone')
        self.assertNotContains(response, 'English Studies')

    def test_subject_teacher_analytics_uses_subject_scope(self):
        TermSetting.objects.create(current_term='first_term')
        math = Subject.objects.create(code='MAT B51', name='Mathematics')
        english = Subject.objects.create(code='ENG B51', name='English Studies')
        ada = Student.objects.create(student_id='CIA/B52026/0001', first_name='Ada', last_name='King', class_name='Basic 5')
        ben = Student.objects.create(student_id='CIA/B52026/0002', first_name='Ben', last_name='Stone', class_name='Basic 5')
        ada.subjects.add(math, english)
        ben.subjects.add(english)
        Grade.objects.create(student=ada, subject=math, term='first_term', homework=5, class_work=10, project=5, first_test=10, midterm_test=10, exam=55)
        Grade.objects.create(student=ben, subject=english, term='first_term', homework=3, class_work=7, project=4, first_test=7, midterm_test=7, exam=42)
        subject_teacher = User.objects.create_user(username='mathteacher', password='pass12345')
        subject_teacher.profile.role = Profile.ROLE_SUBJECT_TEACHER
        subject_teacher.profile.save()
        subject_teacher.profile.assigned_subjects.add(math)
        self.client.login(username='mathteacher', password='pass12345')

        response = self.client.get(reverse('class_analytics'), {'subject': math.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Subject Analytics')
        self.assertContains(response, 'Class Averages')
        self.assertContains(response, 'Subject Average')
        self.assertContains(response, 'Ada King')
        self.assertNotContains(response, 'Class Analytics')
        self.assertNotContains(response, 'Ben Stone')

    def test_student_dashboard_blocks_results_until_fee_and_approval_are_ready(self):
        TermSetting.objects.create(current_academic_year='2025/2026', current_term='second_term')
        student_user = User.objects.create_user(username='CIA/B52026/0001', password='pass12345')
        student_user.profile.role = Profile.ROLE_STUDENT
        student_user.profile.save()
        student = Student.objects.create(
            student_id='CIA/B52026/0001',
            first_name='Gabriel',
            last_name='Zion',
            class_name='Basic 5',
            nationality='Nigeria',
        )
        Subject.objects.create(code='MAT B52', name='Mathematics')
        self.client.login(username='CIA/B52026/0001', password='pass12345')

        response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Results are currently locked')
        self.assertNotContains(response, 'Academic Grades')

    def test_student_report_pdf_generates_printable_result(self):
        TermSetting.objects.create(current_academic_year='2025/2026', current_term='second_term')
        student_user = User.objects.create_user(username='CIA/B52026/0001', password='pass12345')
        student_user.profile.role = Profile.ROLE_STUDENT
        student_user.profile.save()
        student = Student.objects.create(
            student_id='CIA/B52026/0001',
            first_name='Gabriel',
            last_name='Zion',
            class_name='Basic 5',
            nationality='Nigeria',
            state_of_origin='Kogi State',
            club_and_society='Home Makers Club',
        )
        math = Subject.objects.create(code='MAT B52', name='Mathematics')
        english = Subject.objects.create(code='ENG B52', name='English Studies')
        Grade.objects.create(
            student=student,
            subject=math,
            academic_year='2025/2026',
            term='second_term',
            homework=5,
            class_work=10,
            project=5,
            first_test=10,
            midterm_test=10,
            exam=58,
        )
        Grade.objects.create(
            student=student,
            subject=english,
            academic_year='2025/2026',
            term='second_term',
            homework=5,
            class_work=10,
            project=5,
            first_test=10,
            midterm_test=10,
            exam=55,
        )
        BehavioralGrade.objects.create(
            student=student,
            academic_year='2025/2026',
            term='second_term',
            punctuality='A',
            relationship_with_staff='A',
            politeness='A',
            neatness='A',
            co_operation='A',
            obedience='B',
            attentiveness='B',
            adjustment_in_school='A',
            relationship_with_peers='A',
            times_present=108,
            remarks='Keep improving.',
        )
        ResultPublication.objects.create(
            student=student,
            academic_year='2025/2026',
            term='second_term',
            is_fee_cleared=True,
            is_results_approved=True,
        )
        self.client.login(username='CIA/B52026/0001', password='pass12345')

        response = self.client.get(reverse('report_card_pdf'), {
            'academic_year': '2025/2026',
            'term': 'second_term',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('CIA-B52026-0001_2025-2026_second_term_report.pdf', response['Content-Disposition'])


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
 
