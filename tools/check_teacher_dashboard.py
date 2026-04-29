import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_portal.settings')
import django
django.setup()
from django.test.client import Client
from django.contrib.auth.models import User
from django.urls import reverse

# Cleanup any existing user
User.objects.filter(username='teacher').delete()

u = User.objects.create_user(username='teacher', password='pass12345', first_name='Grace', last_name='Hopper')
u.is_staff = True
u.save()

c = Client()
logged = c.login(username='teacher', password='pass12345')
print('logged:', logged)
res = c.get(reverse('teacher_dashboard'))
print('status:', res.status_code)
print('redirect_chain:', res.redirect_chain)
print('url (if redirect):', getattr(res, 'url', None))
print('location header:', res.get('Location'))
print('content snippet:')
print(res.content.decode('utf-8')[:2000])
