from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import datetime

TERM_CHOICES = [
    ('first_term', 'First Term'),
    ('second_term', 'Second Term'),
    ('third_term', 'Third Term'),
]


class Student(models.Model):
    """Model for storing student information"""
    student_id = models.CharField(max_length=20, unique=True, db_index=True, help_text="Unique student ID")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    class_name = models.CharField(max_length=50, blank=True, null=True, help_text="Student's class (e.g., JSS1A, SS2B)")
    nationality = models.CharField(max_length=50, default='Nigeria')
    state_of_origin = models.CharField(max_length=50, blank=True, null=True)
    club_and_society = models.CharField(max_length=100, blank=True, null=True)
    sport_house = models.CharField(max_length=50, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    enrollment_date = models.DateField(default=datetime.today)
    
    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = "Student"
        verbose_name_plural = "Students"
        indexes = [
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['class_name']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.student_id})"


class Subject(models.Model):
    """Model for storing subject/course information"""
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    credit_hours = models.IntegerField(default=3)
    
    class Meta:
        ordering = ['code']
        verbose_name = "Subject"
        verbose_name_plural = "Subjects"
    
    def __str__(self):
        return f"{self.code} - {self.name}"


class TermSetting(models.Model):
    current_term = models.CharField(
        max_length=20,
        choices=TERM_CHOICES,
        default='first_term',
        help_text='Set the currently active academic term for the portal'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Term Setting'
        verbose_name_plural = 'Term Settings'

    def save(self, *args, **kwargs):
        TermSetting.objects.exclude(pk=self.pk).delete()
        super().save(*args, **kwargs)

    @classmethod
    def get_current_term(cls):
        term_setting = cls.objects.order_by('-updated_at').first()
        return term_setting.current_term if term_setting else 'first_term'

    def __str__(self):
        return f'Current Term: {self.get_current_term_display()}'


class Grade(models.Model):
    """Model for storing student grades for each subject"""
    GRADE_CHOICES = [
        ('A', 'A (90-100)'),
        ('B', 'B (80-89)'),
        ('C', 'C (70-79)'),
        ('D', 'D (60-69)'),
        ('E', 'E (50-59)'),
        ('F', 'F (Below 50)'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='grades')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='grades')
    marks = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Marks out of 100"
    )
    letter_grade = models.CharField(max_length=2, choices=GRADE_CHOICES)
    TERM_CHOICES = [
        ('first_term', 'First Term'),
        ('second_term', 'Second Term'),
        ('third_term', 'Third Term'),
    ]
    term = models.CharField(
        max_length=20,
        choices=TERM_CHOICES,
        default='first_term',
        help_text="Academic term for the grade"
    )
    date_recorded = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    remarks = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-term', 'student', 'subject']
        verbose_name = "Grade"
        verbose_name_plural = "Grades"
        # Ensure one grade per student per subject per term
        unique_together = ['student', 'subject', 'term']
        indexes = [
            models.Index(fields=['student', 'term']),
            models.Index(fields=['subject', 'term']),
            models.Index(fields=['letter_grade']),
        ]
    
    def __str__(self):
        return f"{self.student} - {self.subject} ({self.term}): {self.letter_grade}"
    
    def save(self, *args, **kwargs):
        """Automatically assign letter grade based on marks"""
        if self.marks >= 90:
            self.letter_grade = 'A'
        elif self.marks >= 80:
            self.letter_grade = 'B'
        elif self.marks >= 70:
            self.letter_grade = 'C'
        elif self.marks >= 60:
            self.letter_grade = 'D'
        elif self.marks >= 50:
            self.letter_grade = 'E'
        else:
            self.letter_grade = 'F'
        super().save(*args, **kwargs)


class BehavioralGrade(models.Model):
    """Model for storing student behavioral/character grades"""
    BEHAVIORAL_GRADES = [
        ('A', 'A - Excellent'),
        ('B', 'B - Very Good'),
        ('C', 'C - Good'),
        ('D', 'D - Satisfactory'),
        ('E', 'E - Needs Improvement'),
        ('F', 'F - Poor'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='behavioral_grades')
    term = models.CharField(
        max_length=20,
        choices=TERM_CHOICES,
        default='first_term',
        help_text="Academic term for the behavioral assessment"
    )
    
    # Behavioral traits graded A-F
    punctuality = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    relationship_with_staff = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    politeness = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    neatness = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    co_operation = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    obedience = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    attentiveness = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    adjustment_in_school = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    relationship_with_peers = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    
    # Number of times present (numeric field)
    times_present = models.PositiveIntegerField(default=0, help_text="Number of times present during the term")
    
    date_recorded = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    remarks = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-term', 'student']
        verbose_name = "Behavioral Grade"
        verbose_name_plural = "Behavioral Grades"
        # Ensure one behavioral assessment per student per term
        unique_together = ['student', 'term']
        indexes = [
            models.Index(fields=['student', 'term']),
        ]
    
    def __str__(self):
        return f"{self.student} - Behavioral Assessment ({self.term})"
