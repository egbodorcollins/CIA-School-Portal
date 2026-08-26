import psycopg2
from decouple import config
DATABASE_URL = config('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
print('tables:')
for row in cur.fetchall():
    print(row[0])
cur.execute("SELECT app, name FROM django_migrations WHERE app='grades' ORDER BY applied")
print('grades migrations:')
for row in cur.fetchall():
    print(row)
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE '%announcement%'")
print('announcement tables:')
for row in cur.fetchall():
    print(row[0])
cur.close()
conn.close()
