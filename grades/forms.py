from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Student, Subject, Grade, BehavioralGrade, TermSetting, Profile
from .subject_map import STANDARD_SUBJECTS


AUTO_STUDENT_PASSWORD = 'CIA@123456'


CLASS_CODE_MAP = {
    'Pre-School': 'PS',
    'NURSERY1': 'N1',
    'NURSERY2': 'N2',
    'NURSERY3': 'N3',
    'PS': 'PS',
    'N1': 'N1',
    'N2': 'N2',
    'N3': 'N3',
    'BASIC1': 'B1',
    'BASIC2': 'B2',
    'BASIC3': 'B3',
    'BASIC4': 'B4',
    'BASIC5': 'B5',
    'BASIC6': 'B6',
    'B1': 'B1',
    'B2': 'B2',
    'B3': 'B3',
    'B4': 'B4',
    'B5': 'B5',
    'B6': 'B6',
    'JSS1': 'J1',
    'JSS2': 'J2',
    'JSS3': 'J3',
    'J1': 'J1',
    'J2': 'J2',
    'J3': 'J3',
    'SSS1': 'S1',
    'SSS2': 'S2',
    'SSS3': 'S3',
    'S1': 'S1',
    'S2': 'S2',
    'S3': 'S3',
}

CLASS_CHOICES = [
    ('Pre-School', 'Pre-School'),
    ('Nursery 1', 'Nursery 1'),
    ('Nursery 2', 'Nursery 2'),
    ('Nursery 3', 'Nursery 3'),
    ('Basic 1', 'Basic 1'),
    ('Basic 2', 'Basic 2'),
    ('Basic 3', 'Basic 3'),
    ('Basic 4', 'Basic 4'),
    ('Basic 5', 'Basic 5'),
    ('Basic 6', 'Basic 6'),
    ('JSS 1', 'JSS 1'),
    ('JSS 2', 'JSS 2'),
    ('JSS 3', 'JSS 3'),
    ('SSS 1', 'SSS 1'),
    ('SSS 2', 'SSS 2'),
    ('SSS 3', 'SSS 3'),
]


def normalize_class_name(class_name):
    return ''.join(character for character in str(class_name).upper() if character.isalnum())


def get_class_code(class_name):
    return CLASS_CODE_MAP.get(normalize_class_name(class_name))


def generate_student_id(class_name):
    class_code = get_class_code(class_name)
    if not class_code:
        raise ValidationError('Please select a valid class name before creating the student account.')

    registration_year = timezone.now().year
    prefix = f'CIA/{class_code}{registration_year}/'
    latest_sequence = 0

    # Check existing Student records
    for student_id in Student.objects.filter(student_id__startswith=prefix).values_list('student_id', flat=True):
        suffix = student_id.rsplit('/', 1)[-1]
        try:
            latest_sequence = max(latest_sequence, int(suffix, 16))
        except ValueError:
            continue

    # Also check User model to catch orphaned accounts where
    # the Student record was deleted but the User account remains
    for username in User.objects.filter(username__startswith=prefix).values_list('username', flat=True):
        suffix = username.rsplit('/', 1)[-1]
        try:
            latest_sequence = max(latest_sequence, int(suffix, 16))
        except ValueError:
            continue

    return f'{prefix}{latest_sequence + 1:04X}'


def enroll_student_in_standard_subjects(student, class_name=None, term=None, clear_existing=False):
    class_code = get_class_code(class_name or student.class_name)
    current_term = term or TermSetting.get_current_term()
    term_digit = {'first_term': '1', 'second_term': '2', 'third_term': '3'}.get(current_term, '1')

    if clear_existing:
        student.subjects.clear()

    if not class_code or class_code not in STANDARD_SUBJECTS:
        return 0

    abbrs = [abbr for abbr, _ in STANDARD_SUBJECTS.get(class_code, [])]
    codes = [f"{abbr} {class_code}{term_digit}" for abbr in abbrs]
    subjects_qs = Subject.objects.filter(code__in=codes)

    if clear_existing:
        student.subjects.add(*subjects_qs)
    else:
        student.subjects.set(subjects_qs)

    return subjects_qs.count()


class StudentSignUpForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    class_name = forms.ChoiceField(choices=CLASS_CHOICES, required=True, help_text="Select the student's class so the portal can generate the student ID.")
    nationality = forms.CharField(max_length=50, required=False, initial='Nigeria')
    state_of_origin = forms.CharField(max_length=50, required=False)
    club_and_society = forms.CharField(max_length=100, required=False)
    sport_house = forms.CharField(max_length=50, required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # If a Class Teacher is logged in, hide the class field and pre-fill it
        if self.user and hasattr(self.user, 'profile'):
            profile = self.user.profile
            if profile.role == Profile.ROLE_CLASS_TEACHER:
                self.fields['class_name'].widget = forms.HiddenInput()
                self.fields['class_name'].initial = profile.assigned_class
                self.fields['class_name'].required = False

    def clean_class_name(self):
        if self.user and hasattr(self.user, 'profile') and self.user.profile.role == Profile.ROLE_CLASS_TEACHER:
            return self.user.profile.assigned_class

        class_name = self.cleaned_data.get('class_name', '').strip()
        if not get_class_code(class_name):
            raise ValidationError('Please choose a supported class name.')
        return class_name

    def clean_date_of_birth(self):
        date_of_birth = self.cleaned_data.get('date_of_birth')
        if date_of_birth and date_of_birth > timezone.now().date():
            raise ValidationError("Date of birth cannot be in the future.")
        return date_of_birth

    def save(self, commit=True):
        generated_username = generate_student_id(self.cleaned_data['class_name'])
        user = User(username=generated_username)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.set_password(AUTO_STUDENT_PASSWORD)

        student = Student(
            student_id=generated_username,
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name'],
            class_name=self.cleaned_data['class_name'],
            nationality=self.cleaned_data.get('nationality') or 'Nigeria',
            state_of_origin=self.cleaned_data.get('state_of_origin') or '',
            club_and_society=self.cleaned_data.get('club_and_society') or '',
            sport_house=self.cleaned_data.get('sport_house') or '',
            date_of_birth=self.cleaned_data.get('date_of_birth'),
        )

        if commit:
            user.save()
            student.save()
            
            # The signal creates the profile, we just need to update it
            profile, _ = Profile.objects.get_or_create(user=user)
            profile = user.profile
            profile.role = Profile.ROLE_STUDENT
            profile.save()

            # Auto-enroll the student into standard subjects for their class for the active term
            try:
                enroll_student_in_standard_subjects(student, self.cleaned_data['class_name'])
            except Exception:
                # non-fatal: if auto-enroll fails, continue without blocking registration
                pass

        return user


class GradeEntryForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = [
            'student', 'subject',
            'homework', 'class_work', 'project', 'first_test', 'midterm_test', 'exam',
            'remarks'
        ]
        widgets = {
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned = super().clean()
        hw = cleaned.get('homework') or 0
        cw = cleaned.get('class_work') or 0
        proj = cleaned.get('project') or 0
        t1 = cleaned.get('first_test') or 0
        mid = cleaned.get('midterm_test') or 0
        exam = cleaned.get('exam') or 0

        total = hw + cw + proj + t1 + mid + exam
        if total < 0 or total > 100:
            raise ValidationError('Total of components must be between 0 and 100.')

        return cleaned


class BehavioralGradeEntryForm(forms.ModelForm):
    class Meta:
        model = BehavioralGrade
        fields = [
            'student', 'punctuality', 'relationship_with_staff', 'politeness',
            'neatness', 'co_operation', 'obedience', 'attentiveness',
            'adjustment_in_school', 'relationship_with_peers', 'times_present', 'remarks'
        ]
        widgets = {
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_times_present(self):
        times_present = self.cleaned_data.get('times_present')
        if times_present is None or times_present < 0:
            raise ValidationError('Times present cannot be negative.')
        return times_present


class TermSettingForm(forms.ModelForm):
    class Meta:
        model = TermSetting
        fields = ['current_academic_year', 'current_term']


class TeacherCreationForm(forms.Form):
    username = forms.CharField(max_length=150, required=True, help_text="Login username for the teacher")
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES, required=True)
    assigned_class = forms.ChoiceField(choices=[('', '---------')] + CLASS_CHOICES, required=False)
    assigned_subjects = forms.ModelMultipleChoiceField(queryset=Subject.objects.all(), required=False, widget=forms.SelectMultiple)
    password = forms.CharField(required=False, widget=forms.PasswordInput, help_text='Optional initial password; defaults to the portal default if left blank')

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username and User.objects.filter(username=username).exists():
            raise ValidationError('A user with this username already exists.')
        return username

    def save(self, commit=True):
        username = self.cleaned_data.get('username')
        user = User(username=username)
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.email = self.cleaned_data.get('email', '')
        password = self.cleaned_data.get('password') or AUTO_STUDENT_PASSWORD
        user.set_password(password)
        if commit:
            user.save()
            # Update the profile created by the signal
            profile, _ = Profile.objects.get_or_create(user=user)
            profile = user.profile
            profile.role = self.cleaned_data.get('role')
            profile.assigned_class = self.cleaned_data.get('assigned_class') or ''
            profile.save()
            
            subjects = self.cleaned_data.get('assigned_subjects')
            if subjects:
                profile.assigned_subjects.set(subjects)
        return user
