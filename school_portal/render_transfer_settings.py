from pathlib import Path
from urllib.parse import urlparse

from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "temporary-render-transfer-settings"
DEBUG = False
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "school_portal.urls"
STATIC_URL = "static/"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "grades",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [],
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]


def parse_database_url(url):
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username,
        "PASSWORD": parsed.password,
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
        "OPTIONS": {"sslmode": "require"},
    }


DATABASES = {
    "default": parse_database_url(config("DATABASE_URL")),
}
