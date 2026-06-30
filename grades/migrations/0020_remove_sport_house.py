from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0019_resultpublication'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='student',
            name='sport_house',
        ),
    ]
