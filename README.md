# CIA School Portal - Comprehensive Student Grade Management System

## Overview

The CIA School Portal is a robust, Django-based web application designed to streamline student record management, grade tracking, and academic performance analysis for educational institutions. Built with scalability and user-friendliness in mind, it provides administrators, teachers, and students with powerful tools to manage academic data efficiently.

## Key Features

### Student Management
- Comprehensive student profiles with personal and academic information
- Enrollment tracking with date stamps
- Support for diverse student attributes (nationality, state of origin, clubs, sports houses)
- Unique student ID system for easy identification

### Academic Management
- Flexible subject/course management with credit hours
- Multi-term grading system (First Term, Second Term, Third Term)
- Automatic letter grade calculation based on numerical scores
- Behavioral assessment tracking for holistic student evaluation

### Grade Tracking
- Detailed grade recording with component breakdowns (homework, class work, tests, exams)
- Term-based performance analysis
- GPA and average calculations
- Historical grade tracking with timestamps

### Administrative Tools
- Django Admin interface for data management
- Bulk import/export capabilities via Excel
- PDF report generation for grades and analytics
- User authentication and authorization

### Data Integrity
- Automatic validation of marks and term data
- Foreign key relationships ensuring data consistency
- Error handling for import operations

## Technology Stack

- **Backend**: Django 6.0.4 (Python web framework)
- **Database**: SQLite (default), PostgreSQL (production-ready)
- **Data Processing**: Pandas, OpenPyXL
- **PDF Generation**: ReportLab
- **Configuration**: Python-Decouple
- **Monitoring**: Sentry SDK
- **Frontend**: HTML, CSS, JavaScript (Django templates)

## Project Structure

```
CIA School Portal/
├── db.sqlite3                          # SQLite database file
├── db.sqlite3.20260427133053.bak       # Database backup
├── import_grades.py                    # Excel grade import utility
├── import_teachers.py                  # Teacher import utility
├── manage.py                           # Django management script
├── README.md                           # Project documentation
├── requirements.txt                    # Python dependencies
├── register.html                       # Registration template (legacy)
├── cache/                              # Cache directory
│   └── desktop.ini
├── grades/                             # Main Django app for grade management
│   ├── __init__.py
│   ├── admin.py                        # Django admin configuration
│   ├── apps.py                         # App configuration
│   ├── context_processors.py           # Template context processors
│   ├── decorators.py                   # Custom decorators
│   ├── forms.py                        # Django forms
│   ├── models.py                       # Database models (Student, Subject, Grade, etc.)
│   ├── subject_map.py                  # Subject mapping utilities
│   ├── tests.py                        # Unit tests
│   ├── urls.py                         # URL routing for grades app
│   ├── views.py                        # View functions and classes
│   ├── management/                     # Django management commands
│   │   └── commands/
│   │       ├── compute_session_averages.py
│   │       └── load_standard_subjects.py
│   ├── migrations/                     # Database migrations
│   │   ├── __init__.py
│   │   ├── 0001_initial.py
│   │   ├── 0002_alter_grade_letter_grade_alter_grade_semester.py
│   │   ├── 0003_rename_semester_to_term.py
│   │   ├── 0004_remove_student_email_remove_student_phone_and_more.py
│   │   ├── 0005_behavioralgrade.py
│   │   ├── 0006_student_class_name.py
│   │   ├── 0007_termsetting_alter_student_student_id_and_more.py
│   │   ├── 0008_profile.py
│   │   ├── 0009_grade_class_work_grade_exam_grade_first_test_and_more.py
│   │   ├── 0010_student_subjects.py
│   │   ├── 0011_activity.py
│   │   ├── 0012_alter_behavioralgrade_relationship_with_staff_and_more.py
│   │   ├── 0013_classpromotionrequest.py
│   │   ├── 0014_classpromotionrequest_student_pks.py
│   │   ├── 0015_rename_grades_clas_status_246179_idx_grades_clas_status_9b1691_idx_and_more.py
│   │   ├── 0016_alter_behavioralgrade_options_alter_grade_options_and_more.py
│   │   └── 0017_classpromotionrequest_student_pks.py
│   ├── static/                         # Static files (CSS, JS, images)
│   │   └── grades/
│   │       ├── css/
│   │       └── js/
│   ├── templates/                      # HTML templates
│   │   ├── admin/
│   │   │   └── portal_index.html
│   │   └── grades/
│   │       ├── base.html
│   │       ├── class_analytics.html
│   │       ├── enter_academic_scores.html
│   │       ├── enter_behavioral_assessments.html
│   │       ├── home.html
│   │       ├── login.html
│   │       ├── manage_students.html
│   │       ├── password_change_done.html
│   │       ├── password_change_form.html
│   │       ├── register_student_modal.html
│   │       ├── register_student.html
│   │       ├── register_teacher.html
│   │       ├── set_current_term.html
│   │       ├── student_dashboard.html
│   │       └── ...
│   └── templatetags/                   # Custom template tags
│       ├── __init__.py
│       └── custom_filters.py
├── graphic/                            # Graphics and media files
├── logs/                               # Application logs
├── RecycleBin/                         # Recycled files
├── school_portal/                      # Django project configuration
│   ├── __init__.py
│   ├── asgi.py                         # ASGI configuration
│   ├── settings.py                     # Project settings
│   ├── urls.py                         # Main URL routing
│   └── wsgi.py                         # WSGI configuration
└── tools/                              # Utility scripts
    ├── check_teacher_dashboard.py
    └── run_tests_capture.py
```

## Installation and Setup

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Virtual environment tool (venv or virtualenv)
- Git (for cloning the repository)

### Step-by-Step Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/egbodorcollins/CIA-School-Portal.git
   cd CIA-School-Portal
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Database Setup**
   ```bash
   python manage.py migrate
   ```

5. **Create Superuser**
   ```bash
   python manage.py createsuperuser
   ```
   Follow the prompts to set up an admin account.

6. **Run Development Server**
   ```bash
   python manage.py runserver
   ```
   Access the application at `http://127.0.0.1:8000/`

### Configuration

Create a `.env` file in the project root for environment-specific settings:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3  # or PostgreSQL URL
SENTRY_DSN=your-sentry-dsn-here
```

## Usage Guide

### Admin Interface
Access the Django admin at `http://127.0.0.1:8000/admin/` using your superuser credentials.

#### Managing Students
1. Navigate to Students → Add Student
2. Fill in required fields: Student ID, First Name, Last Name, Enrollment Date
3. Optional: Add nationality, state of origin, club memberships, etc.
4. Save the record

#### Managing Subjects
1. Go to Subjects → Add Subject
2. Enter Course Code, Name, Description, and Credit Hours
3. Save

#### Recording Grades
1. Navigate to Grades → Add Grade
2. Select Student and Subject
3. Enter numerical marks (0-100)
4. Choose term and add remarks if needed
5. Save (letter grade auto-calculates)

#### Behavioral Assessments
1. Go to Behavioral Grades → Add Behavioral Grade
2. Select Student and Term
3. Rate each behavioral trait (A-F scale)
4. Enter attendance data
5. Save

### Bulk Operations

#### Importing Grades from Excel
Prepare an Excel file with the following columns:
- `student_id`: Existing student ID
- `subject_code`: Existing subject code
- `marks`: Numerical score (0-100)
- `term`: 'first_term', 'second_term', or 'third_term'
- Optional component columns: `homework`, `class_work`, `project`, `first_test`, `midterm_test`, `exam`

Run the import:
```python
python manage.py shell
>>> exec(open('import_grades.py').read())
>>> import_grades_from_excel('path/to/your/file.xlsx')
```

#### Exporting Reports
Use the admin interface or custom views to export PDF reports of student grades and analytics.

### Database Backups

Create a timestamped backup of users and portal records:

```bash
python manage.py backup_database
```

Backups are written to `backups/` as compressed JSON files. Keep copies outside the project folder too, such as an external drive or cloud storage.

Restore a backup with:

```bash
python manage.py loaddata backups/portal_backup_YYYYMMDD_HHMMSS.json.gz
```

The command keeps the newest 30 backups by default. Change that with:

```bash
python manage.py backup_database --keep 90
```

## Database Schema

### Student Model
- `student_id` (CharField, unique): Unique student identifier
- `first_name` (CharField): Student's first name
- `last_name` (CharField): Student's last name
- `nationality` (CharField, default='Nigeria')
- `state_of_origin` (CharField)
- `club_and_society` (CharField, optional)
- `sport_house` (CharField, optional)
- `date_of_birth` (DateField, optional)
- `enrollment_date` (DateField)
- `class_name` (CharField, optional): Current class

### Subject Model
- `code` (CharField, unique): Course code
- `name` (CharField): Course name
- `description` (TextField, optional)
- `credit_hours` (IntegerField)

### Grade Model
- `student` (ForeignKey to Student)
- `subject` (ForeignKey to Subject)
- `marks` (DecimalField): Overall numerical grade
- `letter_grade` (CharField): Auto-calculated (A-F)
- `term` (CharField): 'first_term', 'second_term', 'third_term'
- `homework`, `class_work`, `project`, `first_test`, `midterm_test`, `exam` (DecimalFields, optional)
- `remarks` (TextField, optional)
- `date_recorded` (DateTimeField, auto)
- `last_updated` (DateTimeField, auto)

### BehavioralGrade Model
- `student` (ForeignKey to Student)
- `term` (CharField)
- Behavioral traits (CharField, A-F): punctuality, relationship_with_staff, politeness, etc.
- `times_present` (IntegerField)
- `remarks` (TextField, optional)
- Timestamps

### Other Models
- `Profile`: User profile extensions
- `Activity`: Student activities
- `ClassPromotionRequest`: Promotion tracking
- `TermSetting`: Term configuration

## Grading System

### Academic Grades
- A: 90-100 (Excellent)
- B: 80-89 (Very Good)
- C: 70-79 (Good)
- D: 60-69 (Satisfactory)
- E: 50-59 (Needs Improvement)
- F: Below 50 (Fail)

### Behavioral Grades
- A: Excellent
- B: Very Good
- C: Good
- D: Satisfactory
- E: Needs Improvement
- F: Poor

## API Endpoints (Future Development)

While currently admin-focused, future versions will include REST APIs for:
- Student data retrieval
- Grade submission
- Report generation
- Integration with third-party systems

## Deployment

### Production Setup
1. Set `DEBUG=False` in settings
2. Use PostgreSQL database
3. Configure static files serving
4. Set up proper logging and monitoring with Sentry
5. Use a WSGI server like Gunicorn

### Docker Deployment (Optional)
Add Dockerfile and docker-compose.yml for containerized deployment.

## Testing

Run tests with:
```bash
python manage.py test
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and add tests
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support, please open an issue on GitHub or contact the development team.

## Changelog

### Version 1.0.0
- Initial release with core student and grade management
- Excel import/export functionality
- PDF report generation
- Behavioral assessment tracking

## Future Roadmap

- Student dashboard for self-service grade viewing
- Mobile-responsive web interface
- Advanced analytics and reporting
- Integration with learning management systems
- API development for external integrations
- Automated notifications and alerts

---

For more information, visit the [GitHub Repository](https://github.com/egbodorcollins/CIA-School-Portal).
