import gzip
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.management import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Create a timestamped JSON backup of portal data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default='backups',
            help='Directory where backup files are written. Defaults to ./backups.',
        )
        parser.add_argument(
            '--filename',
            help='Optional backup filename. Defaults to portal_backup_<timestamp>.json.gz.',
        )
        parser.add_argument(
            '--plain',
            action='store_true',
            help='Write plain JSON instead of gzipped JSON.',
        )
        parser.add_argument(
            '--keep',
            type=int,
            default=30,
            help='Number of newest backups to keep in the output directory. Use 0 to keep all.',
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        if not output_dir.is_absolute():
            output_dir = settings.BASE_DIR / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')
        default_suffix = '.json' if options['plain'] else '.json.gz'
        filename = options['filename'] or f'portal_backup_{timestamp}{default_suffix}'
        backup_path = output_dir / filename

        if backup_path.exists():
            raise CommandError(f'Backup file already exists: {backup_path}')
        temp_path = backup_path.with_name(f'.{backup_path.name}.tmp')
        if temp_path.exists():
            temp_path.unlink()

        objects = []
        model_labels = [
            'auth.Group',
            'auth.User',
            *[
                model._meta.label
                for model in apps.get_app_config('grades').get_models()
            ],
        ]

        for model_label in model_labels:
            if options['verbosity'] >= 1:
                self.stdout.write(f'Collecting {model_label}...')
            model = apps.get_model(model_label)
            queryset = model._default_manager.all().order_by(model._meta.pk.name)
            objects.extend(list(queryset))

        open_file = open if options['plain'] else gzip.open
        try:
            with open_file(temp_path, 'wt', encoding='utf-8') as backup_file:
                serializers.serialize(
                    'json',
                    objects,
                    stream=backup_file,
                    indent=2,
                    use_natural_foreign_keys=True,
                    use_natural_primary_keys=True,
                )
            temp_path.replace(backup_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        self._prune_old_backups(output_dir, options['keep'])

        size_kb = backup_path.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f'Backup created: {backup_path} ({size_kb:.1f} KB)'))
        self.stdout.write('Restore with: python manage.py loaddata <backup-file>')

    def _prune_old_backups(self, output_dir, keep):
        if keep <= 0:
            return

        backups = sorted(
            output_dir.glob('portal_backup_*.json*'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_backup in backups[keep:]:
            old_backup.unlink()
