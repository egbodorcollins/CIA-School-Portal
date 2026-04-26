from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import datetime


class Student(models.Model):
    """Model for storing student information"""
    student_id = models.CharField(max_length=20, unique=True, help_text="Unique student ID")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    enrollment_date = models.DateField(default=datetime.today)
    
    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = "Student"
        verbose_name_plural = "Students"
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.student_id})"


class Subject(models.Model):
    """Model for storing subject/course information"""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    credit_hours = models.IntegerField(default=3)
    
    class Meta:
        ordering = ['code']
        verbose_name = "Subject"
        verbose_name_plural = "Subjects"
    
    def __str__(self):
        return f"{self.code} - {self.name}"


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
