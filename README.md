# CIA School Portal - Student Grade Management System

A Django-based school portal for managing student records and grades.

## Features

- **Student Management**: Store and manage student information (ID, name, contact, enrollment date)
- **Subject Management**: Create and organize courses/subjects with credit hours
- **Grade Tracking**: Record and manage student grades with automatic letter grade assignment
- **Admin Interface**: User-friendly Django admin panel for easy data management
- **Excel Integration**: Import/export grades from Excel files
- **Data Validation**: Automatic validation of marks and term tracking

## Project Structure

```
CIA School Portal/
├── school_portal/          # Django project configuration
│   ├── settings.py         # Project settings
│   ├── urls.py            # URL routing
│   └── wsgi.py            # WSGI configuration
├── grades/                 # Main app for grade management
│   ├── models.py          # Student, Subject, Grade models
│   ├── admin.py           # Django admin configuration
│   ├── views.py           # Views (for future development)
│   └── migrations/        # Database migrations
├── venv/                  # Virtual environment
├── manage.py              # Django management script
├── requirements.txt       # Python dependencies
└── import_grades.py       # Excel import utility
```

## Setup Instructions

### 1. Activate Virtual Environment
```bash
.\venv\Scripts\activate
```

### 2. Run Development Server
```bash
python manage.py runserver
```
Access the portal at: `http://127.0.0.1:8000/admin`

### 3. Admin Login
- **Username**: admin
- **Password**: Set your password with:
  ```bash
  python manage.py changepassword admin
  ```

## Database Models

### Student
- `student_id`: Unique identifier (e.g., "STU001")
- `first_name`, `last_name`: Student name
- `email`: Student email (unique)
- `phone`: Contact number
- `date_of_birth`: Birth date
- `enrollment_date`: Date of enrollment

### Subject
- `code`: Course code (e.g., "CS101")
- `name`: Course name
- `description`: Course description
- `credit_hours`: Credit hours for the course

### Grade
- `student`: Foreign key to Student
- `subject`: Foreign key to Subject
- `marks`: Numeric grade (0-100)
- `letter_grade`: Automatic letter grade (A, B, C, D, E, F)
- `term`: Term identifier ('first_term', 'second_term', 'third_term')
- `remarks`: Additional notes
- `date_recorded`: Timestamp of record creation
- `last_updated`: Timestamp of last update

## Grading Scale
- A: 90-100
- B: 80-89
- C: 70-79
- D: 60-69
- E: 50-59
- F: Below 50

## Importing Grades from Excel

Prepare an Excel file with columns:
- `student_id`: Student ID (must exist in database)
- `subject_code`: Subject code (must exist in database)
- `marks`: Marks (0-100)
- `term`: Term ('first_term', 'second_term', or 'third_term')
- `remarks`: (Optional) Additional comments

Then run:
```bash
python manage.py shell
>>> exec(open('import_grades.py').read())
>>> import_grades_from_excel('your_file.xlsx')
```

## Common Admin Tasks

### Adding a Student
1. Go to Admin Panel → Students → Add Student
2. Fill in student ID, name, email, and enrollment date
3. Click Save

### Adding a Subject
1. Go to Admin Panel → Subjects → Add Subject
2. Enter course code, name, and credit hours
3. Click Save

### Recording Grades
1. Go to Admin Panel → Grades → Add Grade
2. Select Student and Subject
3. Enter marks (0-100) - letter grade auto-calculates
4. Select term
5. Click Save

## Future Enhancements

- REST API for programmatic access
- Web-based interface for students to view grades
- Term statistics and class reports
- GPA calculation
- Export reports to PDF
- Attendance tracking (currently out of scope)

## Requirements

- Python 3.8+
- Django 6.0.4
- PostgreSQL (optional, SQLite is default)
- pandas, openpyxl for Excel support

## Database

Currently uses SQLite (default Django). To switch to PostgreSQL:

1. Update `DATABASES` in `settings.py`
2. Install: `pip install psycopg2-binary`
3. Run migrations again

## Support

For issues or feature requests, contact the development team.
