from django.db import migrations


def repair_announcement_database_objects(apps, schema_editor):
    connection = schema_editor.connection
    table_names = connection.introspection.table_names()
    if 'grades_announcement' not in table_names:
        return

    Announcement = apps.get_model('grades', 'Announcement')
    through_model = Announcement.target_users.through
    if through_model._meta.db_table not in table_names:
        schema_editor.create_model(through_model)

    columns = {
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(),
            'grades_announcement',
        )
    }

    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            created_at_source = (
                "COALESCE(created_at, published_at, NOW())"
                if 'published_at' in columns
                else "COALESCE(created_at, NOW())"
            )
            updated_at_source = (
                "COALESCE(updated_at, created_at, published_at, NOW())"
                if 'published_at' in columns
                else "COALESCE(updated_at, created_at, NOW())"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                "SET audience = COALESCE(audience, 'everyone') "
                "WHERE audience IS NULL"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                "SET target_classes = COALESCE(target_classes, '[]'::jsonb) "
                "WHERE target_classes IS NULL"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                f"SET created_at = {created_at_source} "
                "WHERE created_at IS NULL"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                f"SET updated_at = {updated_at_source} "
                "WHERE updated_at IS NULL"
            )
            cursor.execute(
                "ALTER TABLE grades_announcement "
                "ALTER COLUMN audience SET NOT NULL"
            )
            cursor.execute(
                "ALTER TABLE grades_announcement "
                "ALTER COLUMN target_classes SET NOT NULL"
            )
            cursor.execute(
                "ALTER TABLE grades_announcement "
                "ALTER COLUMN created_at SET NOT NULL"
            )
            cursor.execute(
                "ALTER TABLE grades_announcement "
                "ALTER COLUMN updated_at SET NOT NULL"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS grades_anno_audienc_2b5283_idx "
                "ON grades_announcement (audience, is_active)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS grades_anno_created_02378e_idx "
                "ON grades_announcement (created_at)"
            )
        elif connection.vendor == 'sqlite':
            created_at_source = (
                "COALESCE(created_at, published_at, CURRENT_TIMESTAMP)"
                if 'published_at' in columns
                else "COALESCE(created_at, CURRENT_TIMESTAMP)"
            )
            updated_at_source = (
                "COALESCE(updated_at, created_at, published_at, CURRENT_TIMESTAMP)"
                if 'published_at' in columns
                else "COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                "SET audience = COALESCE(audience, 'everyone') "
                "WHERE audience IS NULL"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                "SET target_classes = COALESCE(target_classes, '[]') "
                "WHERE target_classes IS NULL"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                f"SET created_at = {created_at_source} "
                "WHERE created_at IS NULL"
            )
            cursor.execute(
                "UPDATE grades_announcement "
                f"SET updated_at = {updated_at_source} "
                "WHERE updated_at IS NULL"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS grades_anno_audienc_2b5283_idx "
                "ON grades_announcement (audience, is_active)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS grades_anno_created_02378e_idx "
                "ON grades_announcement (created_at)"
            )


class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0023_announcement_schema_compatibility'),
    ]

    operations = [
        migrations.RunPython(repair_announcement_database_objects, migrations.RunPython.noop),
    ]
