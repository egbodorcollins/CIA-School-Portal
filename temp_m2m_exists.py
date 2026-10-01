import psycopg2
from decouple import config
DATABASE_URL = config('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name='grades_announcement_target_users'")
print(cur.fetchone())
cur.close()
conn.close()
