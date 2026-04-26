from django.contrib import admin
from .models import Student, Subject, Grade, BehavioralGrade


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['student_id', 'first_name', 'last_name', 'nationality', 'state_of_origin', 'enrollment_date']
    list_filter = ['enrollment_date', 'nationality', 'state_of_origin', 'sport_house']
    search_fields = ['student_id', 'first_name', 'last_name', 'state_of_origin']
    readonly_fields = ['enrollment_date']
    fieldsets = (
        ('Personal Information', {
            'fields': ('student_id', 'first_name', 'last_name', 'nationality', 'state_of_origin')
        }),
        ('School Activities', {
            'fields': ('club_and_society', 'sport_house'),
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


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ['student', 'subject', 'marks', 'letter_grade', 'term']
    list_filter = ['term', 'letter_grade', 'subject']
    search_fields = ['student__first_name', 'student__last_name', 'student__student_id', 'subject__code']
    readonly_fields = ['letter_grade', 'date_recorded', 'last_updated']
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
