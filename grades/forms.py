from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Student


class StudentSignUpForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    nationality = forms.CharField(max_length=50, required=False, initial='Nigeria')
    state_of_origin = forms.CharField(max_length=50, required=False)
    club_and_society = forms.CharField(max_length=100, required=False)
    sport_house = forms.CharField(max_length=50, required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
            Student.objects.create(
                student_id=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                nationality=self.cleaned_data.get('nationality', 'Nigeria'),
                state_of_origin=self.cleaned_data.get('state_of_origin', ''),
                club_and_society=self.cleaned_data.get('club_and_society', ''),
                sport_house=self.cleaned_data.get('sport_house', ''),
                date_of_birth=self.cleaned_data.get('date_of_birth'),
            )
        return user


class TeacherSignUpForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.is_staff = True
        if commit:
            user.save()
        return user
