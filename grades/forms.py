from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Student, Subject, Grade, BehavioralGrade, TermSetting


CLASS_CODE_MAP = {
    'NURSERY1': 'N1',
    'NURSERY2': 'N2',
    'NURSERY3': 'N3',
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

    for student_id in Student.objects.filter(student_id__startswith=prefix).values_list('student_id', flat=True):
        suffix = student_id.rsplit('/', 1)[-1]
        try:
            latest_sequence = max(latest_sequence, int(suffix, 16))
        except ValueError:
            continue

    return f'{prefix}{latest_sequence + 1:04X}'


class StudentSignUpForm(UserCreationForm):
    username = forms.CharField(required=False, widget=forms.HiddenInput())
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    class_name = forms.CharField(max_length=50, required=True, help_text="Student's class (e.g., Nursery 2, Basic 5, SSS 3)")
    nationality = forms.CharField(max_length=50, required=False, initial='Nigeria')
    state_of_origin = forms.CharField(max_length=50, required=False)
    club_and_society = forms.CharField(max_length=100, required=False)
    sport_house = forms.CharField(max_length=50, required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password1', 'password2')

    def clean_class_name(self):
        class_name = self.cleaned_data.get('class_name', '').strip()
        if not get_class_code(class_name):
            raise ValidationError('Please choose a supported class name.')
        return class_name

    def clean(self):
        cleaned_data = super().clean()
        class_name = cleaned_data.get('class_name')
        if class_name:
            cleaned_data['username'] = generate_student_id(class_name)
        return cleaned_data

    def clean_date_of_birth(self):
        date_of_birth = self.cleaned_data.get('date_of_birth')
        if date_of_birth and date_of_birth > timezone.now().date():
            raise ValidationError("Date of birth cannot be in the future.")
        return date_of_birth

    def save(self, commit=True):
        user = super().save(commit=False)
        generated_username = self.cleaned_data['username']

        user.username = generated_username
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']

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

        return user


class GradeEntryForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ['student', 'subject', 'marks', 'term', 'remarks']
        widgets = {
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_marks(self):
        marks = self.cleaned_data.get('marks')
        if marks is None or marks < 0 or marks > 100:
            raise ValidationError('Marks must be between 0 and 100.')
        return marks


class BehavioralGradeEntryForm(forms.ModelForm):
    class Meta:
        model = BehavioralGrade
        fields = [
            'student', 'term', 'punctuality', 'relationship_with_staff', 'politeness',
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
        fields = ['current_term']
