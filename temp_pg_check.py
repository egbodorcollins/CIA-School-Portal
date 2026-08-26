import psycopg2
from decouple import config
DATABASE_URL = config('DATABASE_URL')
print('DB URL', DATABASE_URL)
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='grades_announcement' ORDER BY ordinal_position")
rows = cur.fetchall()
print('columns:')
for row in rows:
    print(row)
cur.close()
conn.close()
