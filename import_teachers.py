import pandas as pd
from django.contrib.auth.models import User
from django.db import transaction
from grades.models import Profile, Subject
from grades.forms import AUTO_STUDENT_PASSWORD

def import_teachers_from_excel(file_path):
    """
    Imports teacher accounts from an Excel file.
    Expected columns: Timestamp, Username, First Name, Last Name, Email, Role, Assigned Class, Subject Codes
    """
    try:
        df = pd.read_excel(file_path)
        success_count = 0
        errors = []

        for index, row in df.iterrows():
            try:
                # Mapping based on Google Form column order (ignoring Timestamp at index 0)
                username = str(row.iloc[1]).strip()
                first_name = str(row.iloc[2]).strip()
                last_name = str(row.iloc[3]).strip()
                email = str(row.iloc[4]).strip()
                role = str(row.iloc[5]).strip().lower()
                assigned_class = str(row.iloc[6]).strip() if pd.notna(row.iloc[6]) else ""
                subject_codes_str = str(row.iloc[7]).strip() if pd.notna(row.iloc[7]) else ""

                with transaction.atomic():
                    # 1. Create or Update User
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults={
                            'first_name': first_name,
                            'last_name': last_name,
                            'email': email,
                            'is_staff': True # Teachers need staff access for the dashboard
                        }
                    )
                    
                    if created:
                        user.set_password(AUTO_STUDENT_PASSWORD)
                        user.save()

                    # 2. Configure Profile
                    profile, _ = Profile.objects.get_or_create(user=user)
                    profile.role = role
                    profile.assigned_class = assigned_class
                    profile.save()

                    # 3. Assign Subjects (Many-to-Many)
                    if subject_codes_str:
                        codes = [c.strip() for c in subject_codes_str.split(',') if c.strip()]
                        subjects = Subject.objects.filter(code__in=codes)
                        profile.assigned_subjects.set(subjects)
                        
                        missing_codes = set(codes) - set(subjects.values_list('code', flat=True))
                        if missing_codes:
                            errors.append(f"Row {index+2}: Subjects not found: {', '.join(missing_codes)}")

                success_count += 1
                print(f"Processed: {username} ({role})")

            except Exception as e:
                errors.append(f"Row {index+2}: {str(e)}")

        print(f"\nSuccessfully created/updated {success_count} teacher accounts.")
        if errors:
            print("\nErrors encountered:")
            for err in errors:
                print(f" - {err}")

    except Exception as e:
        print(f"Critical Error: {str(e)}")

if __name__ == "__main__":
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_portal.settings')
    django.setup()
    # Usage: python import_teachers.py
    file = input("Enter path to Excel file: ")
    import_teachers_from_excel(file)