import psycopg2
from decouple import config
DATABASE_URL = config('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='grades_announcement' ORDER BY ordinal_position")
for row in cur.fetchall():
    print(row)
cur.close()
conn.close()
