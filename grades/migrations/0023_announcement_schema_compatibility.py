from django.db import migrations


def repair_announcement_columns(apps, schema_editor):
    connection = schema_editor.connection
    table_names = connection.introspection.table_names()
    if 'grades_announcement' not in table_names:
        return

    columns = {
        column.name: column
        for column in connection.introspection.get_table_description(
            connection.cursor(),
            'grades_announcement',
        )
    }

    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            if 'audience' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN audience varchar(30) DEFAULT 'everyone'"
                )
            if 'target_classes' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN target_classes jsonb"
                )
            if 'created_at' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN created_at timestamptz"
                )
            if 'updated_at' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN updated_at timestamptz"
                )
            if 'published_at' in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ALTER COLUMN published_at DROP NOT NULL"
                )
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
        elif connection.vendor == 'sqlite':
            if 'audience' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN audience varchar(30) DEFAULT 'everyone'"
                )
            if 'target_classes' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN target_classes text"
                )
            if 'created_at' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN created_at datetime"
                )
            if 'updated_at' not in columns:
                cursor.execute(
                    "ALTER TABLE grades_announcement "
                    "ADD COLUMN updated_at datetime"
                )
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


class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0022_rename_grades_anno_audienc_cba1cd_idx_grades_anno_audienc_2b5283_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_announcement_columns, migrations.RunPython.noop),
    ]
