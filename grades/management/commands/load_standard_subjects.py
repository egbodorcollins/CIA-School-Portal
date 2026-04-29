from django.core.management.base import BaseCommand
from django.db import transaction

from grades.models import Subject
from grades.subject_map import STANDARD_SUBJECTS, CLASS_NAME_BY_CODE


class Command(BaseCommand):
    help = 'Create standardized Subject entries per class and per term (and session subjects)'

    def add_arguments(self, parser):
        parser.add_argument('--class', dest='class_code', help='Optional class code to limit (e.g., B1, J2)')
        parser.add_argument('--force', action='store_true', help='Force update name/description if subject exists')

    def handle(self, *args, **options):
        class_code = options.get('class_code')
        force = options.get('force', False)

        keys = [class_code] if class_code else list(STANDARD_SUBJECTS.keys())
        created = 0
        updated = 0

        for key in keys:
            if key not in STANDARD_SUBJECTS:
                self.stdout.write(self.style.WARNING(f'Skipping unknown class code: {key}'))
                continue

            subjects = STANDARD_SUBJECTS[key]
            class_name = CLASS_NAME_BY_CODE.get(key, key)

            for abbr, full_name in subjects:
                # per-term subjects
                for term_digit, term_name in (('1', 'First Term'), ('2', 'Second Term'), ('3', 'Third Term')):
                    code = f"{abbr} {key}{term_digit}"
                    description = f'Auto-generated for {class_name} — {term_name}'
                    with transaction.atomic():
                        subj, created_flag = Subject.objects.get_or_create(
                            code=code,
                            defaults={'name': full_name, 'description': description}
                        )
                        if created_flag:
                            created += 1
                        elif force:
                            subj.name = full_name
                            subj.description = description
                            subj.save()
                            updated += 1

                # session aggregate subject
                session_code = f"{abbr} {key}S"
                session_desc = f'Session aggregate for {class_name}'
                with transaction.atomic():
                    subj_s, created_flag = Subject.objects.get_or_create(
                        code=session_code,
                        defaults={'name': full_name, 'description': session_desc}
                    )
                    if created_flag:
                        created += 1
                    elif force:
                        subj_s.name = full_name
                        subj_s.description = session_desc
                        subj_s.save()
                        updated += 1

        self.stdout.write(self.style.SUCCESS(f'Finished. Created: {created}, Updated: {updated}'))
