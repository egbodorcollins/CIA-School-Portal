"""
Utility script for importing student grades from Excel files
Usage: python manage.py shell < import_grades.py
"""

import pandas as pd
from datetime import datetime
from grades.models import Student, Subject, Grade

def import_grades_from_excel(file_path):
    """
    Import grades from an Excel file.
    
    Expected Excel columns:
    - student_id: Student ID (must exist in database)
    - subject_code: Subject code (must exist in database)
    - marks: Marks (0-100)
    - term: Term ('first_term', 'second_term', or 'third_term')
    """
    try:
        df = pd.read_excel(file_path)
        
        imported_count = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                student = Student.objects.get(student_id=row['student_id'])
                subject = Subject.objects.get(code=row['subject_code'])
                
                # Prefer component columns if present, otherwise fall back to 'marks'
                term = row.get('term', 'first_term')
                if term not in ['first_term', 'second_term', 'third_term']:
                    errors.append(f"Row {index + 1}: Invalid term '{term}'")
                    continue

                comp_cols = ['homework', 'class_work', 'project', 'first_test', 'midterm_test', 'exam']
                has_components = all(col in df.columns for col in comp_cols)

                if has_components:
                    try:
                        hw = float(row.get('homework', 0) or 0)
                        cw = float(row.get('class_work', 0) or 0)
                        proj = float(row.get('project', 0) or 0)
                        t1 = float(row.get('first_test', 0) or 0)
                        mid = float(row.get('midterm_test', 0) or 0)
                        exam = float(row.get('exam', 0) or 0)
                    except Exception:
                        errors.append(f"Row {index + 1}: Invalid component value")
                        continue

                    total = hw + cw + proj + t1 + mid + exam
                    if not (0 <= total <= 100):
                        errors.append(f"Row {index + 1}: Component total {total} out of range (0-100)")
                        continue

                    defaults = {
                        'homework': hw,
                        'class_work': cw,
                        'project': proj,
                        'first_test': t1,
                        'midterm_test': mid,
                        'exam': exam,
                        'remarks': row.get('remarks', '')
                    }
                else:
                    try:
                        marks = float(row['marks'])
                    except Exception:
                        errors.append(f"Row {index + 1}: Invalid marks value")
                        continue

                    if not (0 <= marks <= 100):
                        errors.append(f"Row {index + 1}: Marks {marks} out of range (0-100)")
                        continue

                    # Assign as exam component for older sheets, keep other components zero
                    defaults = {
                        'homework': 0,
                        'class_work': 0,
                        'project': 0,
                        'first_test': 0,
                        'midterm_test': 0,
                        'exam': marks,
                        'remarks': row.get('remarks', '')
                    }

                grade, created = Grade.objects.update_or_create(
                    student=student,
                    subject=subject,
                    term=term,
                    defaults=defaults
                )
                imported_count += 1
                
            except Student.DoesNotExist:
                errors.append(f"Row {index + 1}: Student {row['student_id']} not found")
            except Subject.DoesNotExist:
                errors.append(f"Row {index + 1}: Subject {row['subject_code']} not found")
            except ValueError:
                errors.append(f"Row {index + 1}: Invalid marks value")
            except Exception as e:
                errors.append(f"Row {index + 1}: {str(e)}")
        
        print(f"\n✓ Successfully imported {imported_count} grades")
        if errors:
            print(f"\n✗ Errors encountered ({len(errors)}):")
            for error in errors:
                print(f"  - {error}")
        return imported_count, errors
        
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
    except Exception as e:
        print(f"Error reading Excel file: {str(e)}")


# Example usage - uncomment to use:
# import_grades_from_excel('grades_data.xlsx')
