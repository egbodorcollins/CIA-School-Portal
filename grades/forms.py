from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Student, Subject, Grade, BehavioralGrade, TermSetting


class StudentSignUpForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    class_name = forms.CharField(max_length=50, required=False, help_text="Student's class (e.g., JSS1A, SS2B)")
    nationality = forms.CharField(max_length=50, required=False, initial='Nigeria')
    state_of_origin = forms.CharField(max_length=50, required=False)
    club_and_society = forms.CharField(max_length=100, required=False)
    sport_house = forms.CharField(max_length=50, required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password1', 'password2')

    def clean_date_of_birth(self):
        date_of_birth = self.cleaned_data.get('date_of_birth')
        if date_of_birth and date_of_birth > timezone.now().date():
            raise ValidationError("Date of birth cannot be in the future.")
        return date_of_birth


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
