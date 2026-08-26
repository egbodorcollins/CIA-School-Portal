import sqlite3, os
path = os.path.join(os.getcwd(),'db.sqlite3')
print('DB exists', os.path.exists(path), path)
conn = sqlite3.connect(path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='grades_announcement'")
print('table exists', cur.fetchone())
cur.execute('PRAGMA table_info(grades_announcement)')
rows = cur.fetchall()
print('columns:')
for row in rows:
    print(row)
conn.close()
