from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.contrib.auth.models import User
from django import forms
from .forms import CLASS_CHOICES
from .models import Student, Subject, Grade, BehavioralGrade, TermSetting, Profile, ClassPromotionRequest

admin.site.index_template = 'admin/portal_index.html'


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['student_id', 'first_name', 'last_name', 'class_name', 'nationality', 'state_of_origin', 'enrollment_date']
    list_filter = ['enrollment_date', 'nationality', 'state_of_origin', 'sport_house', 'class_name']
    search_fields = ['student_id', 'first_name', 'last_name', 'state_of_origin', 'class_name']
    readonly_fields = ['enrollment_date']
    fieldsets = (
        ('Personal Information', {
            'fields': ('student_id', 'first_name', 'last_name', 'class_name', 'nationality', 'state_of_origin')
        }),
        ('School Activities', {
            'fields': ('club_and_society', 'sport_house', 'subjects'),
            'classes': ('collapse',)
        }),
        ('Additional Info', {
            'fields': ('date_of_birth', 'enrollment_date'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'credit_hours']
    list_filter = ['credit_hours']
    search_fields = ['code', 'name']
    ordering = ['code']


@admin.register(TermSetting)
class TermSettingAdmin(admin.ModelAdmin):
    list_display = ['current_term', 'updated_at']
    fields = ['current_term', 'updated_at']
    readonly_fields = ['updated_at']
    ordering = ['-updated_at']

    def has_delete_permission(self, request, obj=None):
        return False


# class ProfileInline(admin.StackedInline):
#     model = Profile
#     can_delete = False
#     verbose_name_plural = 'profile'
#     fk_name = 'user'
#     # We will set a custom form below for the inline


class ProfileAdminForm(forms.ModelForm):
    assigned_class = forms.ChoiceField(choices=[('', '---------')] + CLASS_CHOICES, required=False)

    class Meta:
        model = Profile
        fields = '__all__'


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'profile'
    fk_name = 'user'
    form = ProfileAdminForm


class CustomUserAdmin(DefaultUserAdmin):
    inlines = (ProfileInline,)


try:
    admin.site.unregister(User)
except Exception:
    pass

admin.site.register(User, CustomUserAdmin)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    form = ProfileAdminForm
    list_display = ['user', 'role', 'assigned_class']
    list_filter = ['role', 'assigned_class']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    filter_horizontal = ('assigned_subjects',)


@admin.register(ClassPromotionRequest)
class ClassPromotionRequestAdmin(admin.ModelAdmin):
    list_display = ['from_class', 'to_class', 'student_count', 'status', 'requested_by', 'approved_by', 'created_at', 'reviewed_at']
    list_filter = ['status', 'from_class', 'to_class', 'created_at']
    search_fields = ['from_class', 'to_class', 'requested_by__username', 'approved_by__username']
    readonly_fields = ['created_at', 'reviewed_at']


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ['student', 'subject', 'marks', 'letter_grade', 'term']
    list_filter = ['term', 'letter_grade', 'subject']
    search_fields = ['student__first_name', 'student__last_name', 'student__student_id', 'subject__code']
    readonly_fields = ['marks', 'letter_grade', 'date_recorded', 'last_updated']
    fieldsets = (
        ('Student & Subject', {
            'fields': ('student', 'subject', 'term')
        }),
        ('Grades', {
            'fields': ('marks', 'letter_grade')
        }),
        ('Additional Info', {
            'fields': ('remarks', 'date_recorded', 'last_updated'),
            'classes': ('collapse',)
        }),
    )
    
    def get_list_display(self, request):
        """Customize list display based on context"""
        return ['student', 'subject', 'marks', 'letter_grade', 'term', 'last_updated']


@admin.register(BehavioralGrade)
class BehavioralGradeAdmin(admin.ModelAdmin):
    list_display = ['student', 'term', 'punctuality', 'relationship_with_staff', 'politeness', 'times_present']
    list_filter = ['term', 'punctuality', 'relationship_with_staff', 'politeness', 'neatness']
    search_fields = ['student__first_name', 'student__last_name', 'student__student_id']
    readonly_fields = ['date_recorded', 'last_updated']
    fieldsets = (
        ('Student & Term', {
            'fields': ('student', 'term')
        }),
        ('Behavioral Traits', {
            'fields': (
                ('punctuality', 'relationship_with_staff'),
                ('politeness', 'neatness'),
                ('co_operation', 'obedience'),
                ('attentiveness', 'adjustment_in_school'),
                ('relationship_with_peers',)
            ),
            'classes': ('collapse',)
        }),
        ('Attendance', {
            'fields': ('times_present',),
        }),
        ('Additional Info', {
            'fields': ('remarks', 'date_recorded', 'last_updated'),
            'classes': ('collapse',)
        }),
    )


class CustomUserAdmin(DefaultUserAdmin):
    inlines = (ProfileInline,)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, Profile):
                # get_or_create to avoid collision with the post_save signal
                # which already created a Profile when the User was saved
                obj, _ = Profile.objects.get_or_create(user=instance.user)
                obj.role = instance.role
                obj.assigned_class = instance.assigned_class
                obj.save()

                # Handle assigned_subjects M2M manually on the saved obj,
                # NOT via formset.save_m2m() which would try to use the
                # unsaved instance (no id) and raise ValueError
                for inline_form in formset.forms:
                    if 'assigned_subjects' in inline_form.cleaned_data:
                        obj.assigned_subjects.set(
                            inline_form.cleaned_data['assigned_subjects']
                        )
            else:
                instance.save()

        # Only call save_m2m for non-Profile formsets (e.g. permissions).
        # Profile M2M is already handled above.
        for inline_form in formset.forms:
            if not isinstance(inline_form.instance, Profile):
                inline_form.save_m2m()
try:
    admin.site.unregister(User)
except Exception:
    pass

admin.site.register(User, CustomUserAdmin)
