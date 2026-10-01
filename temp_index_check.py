import psycopg2
from decouple import config
DATABASE_URL = config('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='grades_announcement'")
for row in cur.fetchall():
    print(row)
cur.close()
conn.close()
