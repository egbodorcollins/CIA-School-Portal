"""
import_teachers.py
=================
Imports teacher/staff accounts into the CIA School Portal from the
cleaned Excel file (CIA_Teachers_Cleaned.xlsx).

Expected columns (reads by name, not position):
  - Username
  - First Name
  - Last Name
  - Email Address   (blank or "(missing)" is fine — email is optional)
  - Role            (class_teacher | subject_teacher | admin)
  - Assigned Class  (e.g. "Basic 5" — required for class_teacher, blank for others)
  - Assigned Subject (comma-separated subject codes, e.g. "ENG J11, ENG J12")
  - Notes           (ignored during import — for human reference only)

Usage (run from the project root with your virtual environment active):
  python import_teachers.py
  python import_teachers.py --file path/to/other_file.xlsx
  python import_teachers.py --dry-run
  python import_teachers.py --file path/to/file.xlsx --dry-run
"""

import os
import sys
import argparse

# ── Bootstrap Django ──────────────────────────────────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_portal.settings')

import django
django.setup()

# ── Imports (after Django setup) ──────────────────────────────────────────────
import pandas as pd
from django.contrib.auth.models import User  # noqa: E402
from django.db import transaction

from grades.models import Profile, Subject
from grades.forms import AUTO_STUDENT_PASSWORD, CLASS_CHOICES


# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_FILE = 'CIA_Teachers_Cleaned.xlsx'
SHEET_NAME   = 'Clean Import Data'
SKIP_ROWS    = 2          # skip the title + subtitle rows in the cleaned file
NOTES_COL    = 'Notes'   # this column is ignored during import

VALID_ROLES = {r[0] for r in Profile.ROLE_CHOICES if r[0] != Profile.ROLE_STUDENT}

# Build a lookup so "basic 5", "Basic5", "BASIC 5" all map to "Basic 5"
_CLASS_LOOKUP = {c[0].upper().replace(' ', ''): c[0] for c in CLASS_CHOICES}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str(value) -> str:
    """Convert a cell value to a clean string, returning '' for NaN/None."""
    if value is None:
        return ''
    if isinstance(value, float) and value != value:   # NaN check
        return ''
    s = str(value).strip()
    # The cleaned file marks missing emails as "(missing)" — treat as blank
    if s.lower() in ('(missing)', 'nan', 'none', 'n/a'):
        return ''
    return s


def _normalise_class(raw: str) -> str:
    """Return the canonical class name or '' if unrecognised."""
    if not raw:
        return ''
    return _CLASS_LOOKUP.get(raw.upper().replace(' ', ''), '')


def _parse_subjects(raw: str) -> list:
    """Split a comma-separated subject code string into a clean list."""
    if not raw:
        return []
    return [code.strip().upper() for code in raw.split(',') if code.strip()]


def _divider(char='-', width=68):
    print(char * width)


# ── Core import ───────────────────────────────────────────────────────────────

def import_teachers(file_path: str, dry_run: bool = False) -> None:

    # ── Read file ─────────────────────────────────────────────────────────────
    try:
        df = pd.read_excel(file_path, sheet_name=SHEET_NAME, skiprows=SKIP_ROWS)
    except FileNotFoundError:
        print(f'\n[ERROR] File not found: {file_path}')
        print('       Make sure CIA_Teachers_Cleaned.xlsx is in the project root,')
        print('       or pass the correct path with --file.\n')
        sys.exit(1)
    except Exception as exc:
        print(f'\n[ERROR] Could not read the file: {exc}\n')
        sys.exit(1)

    required_cols = {'Username', 'First Name', 'Last Name', 'Email Address',
                     'Role', 'Assigned Class', 'Assigned Subject'}
    missing_cols  = required_cols - set(df.columns)
    if missing_cols:
        print(f'\n[ERROR] Missing columns in the spreadsheet: {missing_cols}')
        print('        Make sure you are using the "Clean Import Data" sheet.\n')
        sys.exit(1)

    # Drop completely empty rows that may exist below the data
    df = df.dropna(how='all')

    _divider('=')
    mode = 'DRY-RUN — no changes will be written' if dry_run else 'LIVE IMPORT'
    print(f'  CIA School Portal — Teacher Import  |  {mode}')
    print(f'  File  : {file_path}')
    print(f'  Rows  : {len(df)}')
    _divider('=')

    created_count = 0
    updated_count = 0
    skipped_count = 0
    warnings      = []
    errors        = []

    for index, row in df.iterrows():
        row_num = index + SKIP_ROWS + 2   # human-readable row number in Excel

        # ── Read all fields ───────────────────────────────────────────────────
        username       = _str(row.get('Username'))
        first_name     = _str(row.get('First Name')).title()
        last_name      = _str(row.get('Last Name')).title()
        email          = _str(row.get('Email Address'))
        role_raw       = _str(row.get('Role')).lower()
        class_raw      = _str(row.get('Assigned Class'))
        subjects_raw   = _str(row.get('Assigned Subject'))

        assigned_class    = _normalise_class(class_raw)
        subject_code_list = _parse_subjects(subjects_raw)

        # ── Validate ──────────────────────────────────────────────────────────
        row_errors = []

        if not username:
            row_errors.append('Username is empty.')

        if role_raw not in VALID_ROLES:
            row_errors.append(
                f'Role "{role_raw}" is invalid. '
                f'Must be one of: {", ".join(sorted(VALID_ROLES))}.'
            )

        if role_raw == Profile.ROLE_CLASS_TEACHER and not assigned_class:
            row_errors.append(
                f'Class teachers must have an Assigned Class. '
                f'"{class_raw}" did not match any known class name.'
            )

        if row_errors:
            label = username or f'row {row_num}'
            for e in row_errors:
                errors.append(f'Row {row_num} ({label}): {e}')
            skipped_count += 1
            print(f'  [SKIP ]  Row {row_num} — {username or "?"} — {" | ".join(row_errors)}')
            continue

        # ── Dry-run preview ───────────────────────────────────────────────────
        if dry_run:
            exists  = User.objects.filter(username=username).exists()
            action  = 'UPDATE' if exists else 'CREATE'
            email_s = email if email else '(no email)'
            class_s = assigned_class if assigned_class else '—'
            print(
                f'  [{action:6}]  {username:<22} | {role_raw:<17} | '
                f'class: {class_s:<12} | email: {email_s}'
            )
            if subject_code_list:
                missing_subj = set(subject_code_list) - set(
                    Subject.objects.filter(
                        code__in=subject_code_list
                    ).values_list('code', flat=True)
                )
                if missing_subj:
                    warnings.append(
                        f'Row {row_num} ({username}): Subject codes not found in DB — '
                        f'{", ".join(sorted(missing_subj))}. '
                        f'Run "python manage.py load_standard_subjects" first.'
                    )
                    print(f'           ⚠  Subjects not in DB: {", ".join(sorted(missing_subj))}')
            if not email:
                warnings.append(f'Row {row_num} ({username}): No email address — password reset will not work.')
            created_count += 1
            continue

        # ── Write to database ─────────────────────────────────────────────────
        try:
            with transaction.atomic():

                # 1. Create or update the User
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        'first_name': first_name,
                        'last_name':  last_name,
                        'email':      email,
                        'is_staff':   True,
                    }
                )

                if created:
                    user.set_password(AUTO_STUDENT_PASSWORD)
                    user.save()
                    action = 'CREATED'
                    created_count += 1
                else:
                    # Keep personal details up-to-date on re-import
                    user.first_name = first_name
                    user.last_name  = last_name
                    if email:             # only overwrite email if we have one
                        user.email = email
                    user.is_staff = True
                    user.save()
                    action = 'UPDATED'
                    updated_count += 1

                # 2. Update the Profile (auto-created by post_save signal)
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role           = role_raw
                profile.assigned_class = assigned_class
                profile.save()

                # 3. Assign subjects (Many-to-Many)
                if subject_code_list:
                    subjects_qs = Subject.objects.filter(code__in=subject_code_list)
                    profile.assigned_subjects.set(subjects_qs)

                    missing_subj = set(subject_code_list) - set(
                        subjects_qs.values_list('code', flat=True)
                    )
                    if missing_subj:
                        warnings.append(
                            f'Row {row_num} ({username}): Subject codes not in DB — '
                            f'{", ".join(sorted(missing_subj))}. '
                            f'Run "python manage.py load_standard_subjects" first.'
                        )
                else:
                    profile.assigned_subjects.clear()

                # 4. Warn about missing email (non-fatal)
                if not email:
                    warnings.append(
                        f'{username}: No email address saved — '
                        f'password reset via email will not work for this account.'
                    )

                email_s = email if email else '(no email)'
                class_s = assigned_class if assigned_class else '—'
                print(
                    f'  [{action:7}]  {username:<22} | {role_raw:<17} | '
                    f'class: {class_s:<12} | email: {email_s}'
                )

        except Exception as exc:
            errors.append(f'Row {row_num} ({username}): Unexpected error — {exc}')
            skipped_count += 1
            print(f'  [ERROR ]  Row {row_num} — {username} — {exc}')

    # ── Summary ───────────────────────────────────────────────────────────────
    _divider('=')
    if dry_run:
        print(f'  DRY-RUN complete.')
        print(f'  Would create/update : {created_count}  |  Would skip : {skipped_count}')
    else:
        print(f'  Import complete.')
        print(f'  Created : {created_count}  |  Updated : {updated_count}  |  Skipped : {skipped_count}')
        if created_count > 0:
            print(f'  Default password for all new accounts : {AUTO_STUDENT_PASSWORD}')

    if warnings:
        _divider()
        print(f'  WARNINGS ({len(warnings)}):')
        for w in warnings:
            print(f'    ⚠  {w}')

    if errors:
        _divider()
        print(f'  ERRORS ({len(errors)}) — these rows were skipped:')
        for e in errors:
            print(f'    ✗  {e}')

    _divider('=')


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Import CIA teacher accounts from the cleaned Excel file.'
    )
    parser.add_argument(
        '--file',
        default=DEFAULT_FILE,
        help=f'Path to the Excel file (default: {DEFAULT_FILE})',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate and preview every row without writing to the database.',
    )
    args = parser.parse_args()
    import_teachers(file_path=args.file, dry_run=args.dry_run)