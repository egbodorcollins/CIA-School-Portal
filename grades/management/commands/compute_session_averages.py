from django.core.management.base import BaseCommand
from django.db import transaction

from grades.models import Student, Subject, Grade, TermSetting
from grades.subject_map import STANDARD_SUBJECTS, CLASS_NAME_BY_CODE


class Command(BaseCommand):
    help = 'Compute session averages (across 3 terms) and store as Grades for session subjects'

    def add_arguments(self, parser):
        parser.add_argument('--class', dest='class_code', help='Optional class code to limit processing (e.g., B1)')
        parser.add_argument('--academic-year', dest='academic_year', help='Academic year to process (e.g., 2025/2026). Defaults to the active year.')

    def handle(self, *args, **options):
        class_code = options.get('class_code')
        academic_year = options.get('academic_year') or TermSetting.get_current_academic_year()
        keys = [class_code] if class_code else list(STANDARD_SUBJECTS.keys())

        processed_students = 0

        for key in keys:
            if key not in STANDARD_SUBJECTS:
                self.stdout.write(self.style.WARNING(f'Skipping unknown class code: {key}'))
                continue

            class_name = CLASS_NAME_BY_CODE.get(key)
            if not class_name:
                self.stdout.write(self.style.WARNING(f'No class name mapping for {key}; skipping'))
                continue

            students = Student.objects.filter(class_name=class_name)
            subjects = STANDARD_SUBJECTS[key]

            if not students.exists():
                self.stdout.write(self.style.WARNING(f'No students found for {class_name}'))
                continue

            for abbr, _ in subjects:
                # Build per-term subject codes
                term_codes = [f"{abbr} {key}1", f"{abbr} {key}2", f"{abbr} {key}3"]
                session_code = f"{abbr} {key}S"

                try:
                    session_subject = Subject.objects.get(code=session_code)
                except Subject.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f'Session subject {session_code} not found; run load_standard_subjects first.'))
                    continue

                for student in students:
                    marks = []
                    for code in term_codes:
                        try:
                            subj = Subject.objects.get(code=code)
                        except Subject.DoesNotExist:
                            continue
                        grade = Grade.objects.filter(student=student, subject=subj, academic_year=academic_year).first()
                        if grade:
                            marks.append(grade.marks)

                    if not marks:
                        # no term grades found for this subject/student
                        continue

                    avg = sum(marks) / len(marks)

                    with transaction.atomic():
                        # store avg in exam component of session subject; Grade.save will compute marks and letter
                        defaults = {
                            'homework': 0,
                            'class_work': 0,
                            'project': 0,
                            'first_test': 0,
                            'midterm_test': 0,
                            'exam': avg,
                            'remarks': f'Computed average of {len(marks)} term(s)'
                        }
                        Grade.objects.update_or_create(
                            student=student,
                            subject=session_subject,
                            academic_year=academic_year,
                            term='session',
                            defaults=defaults
                        )

                processed_students += students.count()

            self.stdout.write(self.style.SUCCESS(f'Processed class {key}: {students.count()} students'))

        self.stdout.write(self.style.SUCCESS(f'Completed session averaging. Processed students (approx): {processed_students}'))
