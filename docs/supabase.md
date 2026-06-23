# Supabase Setup

This project uses Supabase as a managed PostgreSQL database through Django's normal database connection.

## 1. Create or Open a Supabase Project

Open Supabase, create a project, and wait until the database is ready.

## 2. Copy the Database URL

In Supabase, go to **Project Settings > Database** and copy the PostgreSQL connection string. Use the pooler connection string if Supabase recommends it for your hosting provider.

It will look similar to this:

```env
DATABASE_URL=postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
```

Replace `[YOUR-PASSWORD]` with the database password you set in Supabase.

## 3. Update `.env`

Add these values to `.env`:

```env
DATABASE_URL=postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
DATABASE_CONN_MAX_AGE=600
DATABASE_SSL_REQUIRE=True
```

Keep `DEBUG=True` for local development. Use `DEBUG=False` when deploying.

## 4. Apply Django Migrations

After setting `DATABASE_URL`, run:

```powershell
.\venv\Scripts\python.exe manage.py migrate
```

## 5. Verify the Connection

Run:

```powershell
.\venv\Scripts\python.exe manage.py check_supabase
```

If the command reports the PostgreSQL version, Django is connected to Supabase.

## 6. Move Existing SQLite Data

If you want to copy the current local SQLite data into Supabase:

```powershell
.\venv\Scripts\python.exe manage.py dumpdata --exclude contenttypes --exclude auth.Permission --indent 2 > sqlite_export_for_supabase.json
.\venv\Scripts\python.exe manage.py loaddata sqlite_export_for_supabase.json
```

Run `loaddata` only after `.env` points to Supabase and migrations have completed there.
