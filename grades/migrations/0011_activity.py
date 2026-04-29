# Generated migration for Activity model
from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0010_student_subjects'),
    ]

    operations = [
        migrations.CreateModel(
            name='Activity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(choices=[('grade_created', 'Grade created'), ('grade_updated', 'Grade updated'), ('behavioral_created', 'Behavioral created'), ('behavioral_updated', 'Behavioral updated'), ('student_registered', 'Student registered'), ('teacher_registered', 'Teacher registered')], max_length=50)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activities', to=settings.AUTH_USER_MODEL)),
                ('target_student', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activities', to='grades.student')),
                ('target_subject', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activities', to='grades.subject')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
