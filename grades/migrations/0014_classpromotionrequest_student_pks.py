from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0013_classpromotionrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='classpromotionrequest',
            name='student_pks',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text='Primary keys of individual students selected for promotion',
            ),
        ),
    ]
