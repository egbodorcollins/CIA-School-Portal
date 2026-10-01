import psycopg2
from decouple import config
DATABASE_URL = config('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='grades_student_subjects' ORDER BY ordinal_position")
print('columns:')
for row in cur.fetchall():
    print(row)
cur.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'grades_student_subjects'::regclass")
print('constraints:')
for row in cur.fetchall():
    print(row)
cur.close(); conn.close()
