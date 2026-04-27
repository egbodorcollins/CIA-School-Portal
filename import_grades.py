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
                
                marks = float(row['marks'])
                if not (0 <= marks <= 100):
                    errors.append(f"Row {index + 1}: Marks {marks} out of range (0-100)")
                    continue
                
                term = row.get('term', 'first_term')
                if term not in ['first_term', 'second_term', 'third_term']:
                    errors.append(f"Row {index + 1}: Invalid term '{term}'")
                    continue
                
                grade, created = Grade.objects.update_or_create(
                    student=student,
                    subject=subject,
                    term=term,
                    defaults={
                        'marks': marks,
                        'remarks': row.get('remarks', '')
                    }
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
