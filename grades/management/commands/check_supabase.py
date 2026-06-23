from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Checks the configured database connection, including Supabase Postgres.'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute('select version()')
            version = cursor.fetchone()[0]

        vendor = connection.vendor
        database_name = connection.settings_dict.get('NAME')
        self.stdout.write(self.style.SUCCESS(f'Database connection ok ({vendor}): {database_name}'))
        self.stdout.write(version)
