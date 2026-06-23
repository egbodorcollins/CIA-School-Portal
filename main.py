import os

import psycopg2
from dotenv import load_dotenv


# Load environment variables from this project's .env.
load_dotenv(override=True)

# Fetch variables.
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL is not set in .env')

# Connect to the database.
connection = psycopg2.connect(DATABASE_URL, sslmode='require')

print('Connected to Supabase PostgreSQL successfully.')
connection.close()
