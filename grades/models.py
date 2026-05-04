from django.db import IntegrityError, models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import datetime
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

TERM_CHOICES = [
    ('first_term', 'First Term'),
    ('second_term', 'Second Term'),
    ('third_term', 'Third Term'),
    ('session', 'Session Average'),
]

TERM_MAP = {
    '1': 'First Term',
    '2': 'Second Term',
    '3': 'Third Term',
}


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
    subjects = models.ManyToManyField('Subject', blank=True, related_name='students', help_text='Subjects the student is enrolled in for the current term')
    
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

    # Component breakdown (weights: HW=5, C.W.=10, PROJ=5, 1st TEST=10, MID=10, EXAM=60)
    homework = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        default=0,
        help_text="Home work (max 5)"
    )
    class_work = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        default=0,
        help_text="Class work (max 10)"
    )
    project = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        default=0,
        help_text="Project (max 5)"
    )
    first_test = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        default=0,
        help_text="1st test (max 10)"
    )
    midterm_test = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        default=0,
        help_text="Mid-term test (max 10)"
    )
    exam = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(60)],
        default=0,
        help_text="Exams (max 60)"
    )

    # Total marks (computed from components)
    marks = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        default=0,
        help_text="Total marks out of 100",
        editable=False,
    )
    letter_grade = models.CharField(max_length=2, choices=GRADE_CHOICES)
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
        """Compute total from components, then assign letter grade."""
        total = (
            (self.homework or 0) +
            (self.class_work or 0) +
            (self.project or 0) +
            (self.first_test or 0) +
            (self.midterm_test or 0) +
            (self.exam or 0)
        )
        # Clamp to [0, 100]
        total = max(0, min(100, total))
        self.marks = total

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
    relationship_with_staff = models.CharField(verbose_name='Relationship with Staff', max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    politeness = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    neatness = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    co_operation = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    obedience = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    attentiveness = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    adjustment_in_school = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    relationship_with_peers = models.CharField(max_length=1, choices=BEHAVIORAL_GRADES, default='C')
    
    # Number of times present (numeric field)
    times_present = models.PositiveIntegerField(verbose_name='Times Present', default=0, help_text="Number of times present during the term")
    
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


class Profile(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_CLASS_TEACHER = 'class_teacher'
    ROLE_SUBJECT_TEACHER = 'subject_teacher'
    ROLE_STUDENT = 'student'

    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_CLASS_TEACHER, 'Class Teacher'),
        (ROLE_SUBJECT_TEACHER, 'Subject Teacher'),
        (ROLE_STUDENT, 'Student'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    assigned_class = models.CharField(max_length=50, blank=True, null=True, help_text="Class assigned to class teacher (e.g., Basic 1)")
    assigned_subjects = models.ManyToManyField(Subject, blank=True, related_name='assigned_teachers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'


class ClassPromotionRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    from_class = models.CharField(max_length=50)
    to_class = models.CharField(max_length=50)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='promotion_requests')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_promotion_requests')
    student_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'from_class']),
        ]

    def __str__(self):
        return f'{self.from_class} to {self.to_class} ({self.get_status_display()})'


class Activity(models.Model):
    ACTION_GRADE_CREATED = 'grade_created'
    ACTION_GRADE_UPDATED = 'grade_updated'
    ACTION_BEHAVIORAL_CREATED = 'behavioral_created'
    ACTION_BEHAVIORAL_UPDATED = 'behavioral_updated'
    ACTION_STUDENT_REGISTERED = 'student_registered'
    ACTION_TEACHER_REGISTERED = 'teacher_registered'

    ACTION_CHOICES = [
        (ACTION_GRADE_CREATED, 'Grade created'),
        (ACTION_GRADE_UPDATED, 'Grade updated'),
        (ACTION_BEHAVIORAL_CREATED, 'Behavioral created'),
        (ACTION_BEHAVIORAL_UPDATED, 'Behavioral updated'),
        (ACTION_STUDENT_REGISTERED, 'Student registered'),
        (ACTION_TEACHER_REGISTERED, 'Teacher registered'),
    ]

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES)
    target_student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    target_subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        actor = self.actor.get_full_name() or (self.actor.username if self.actor else 'System')
        return f"{actor} - {self.get_action_type_display()} ({self.created_at:%Y-%m-%d %H:%M})"


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    # Ignore raw imports (like loading data from a backup/fixture)
    if kwargs.get('raw', False):
        return

    if created:
        # 'atomic' ensures this block is treated as a single unit
        with transaction.atomic():
            try:
                # get_or_create is the "first line of defense"
                Profile.objects.get_or_create(user=instance)
            except IntegrityError:
                # If a race condition happened and it exists, just exit quietly
                pass
