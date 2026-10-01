from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('grades', '0020_remove_sport_house'),
    ]

    operations = [
        migrations.CreateModel(
            name='Announcement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('body', models.TextField()),
                ('audience', models.CharField(choices=[('everyone', 'Everyone'), ('staff', 'All Staff'), ('class_teachers', 'Class Teachers'), ('subject_teachers', 'Subject Teachers'), ('students', 'Students'), ('classes', 'Specific Classes'), ('individuals', 'Specific Individuals')], default='everyone', max_length=30)),
                ('target_classes', models.JSONField(blank=True, default=list)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_announcements', to=settings.AUTH_USER_MODEL)),
                ('target_users', models.ManyToManyField(blank=True, related_name='targeted_announcements', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='announcement',
            index=models.Index(fields=['audience', 'is_active'], name='grades_anno_audienc_cba1cd_idx'),
        ),
        migrations.AddIndex(
            model_name='announcement',
            index=models.Index(fields=['created_at'], name='grades_anno_created_521ac5_idx'),
        ),
    ]
