from __future__ import unicode_literals

# Django 2.0+ requires the DATABASES dict format instead of the legacy
# DATABASE_ENGINE / DATABASE_NAME flat settings.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Required by Django 3.2+ — suppresses system check warnings about implicit
# primary key types for models that do not declare one explicitly.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Required by Django 3.0+ — used for cryptographic signing (e.g. sessions,
# CSRF tokens). Any non-empty string is acceptable in a test-only context.
SECRET_KEY = 'test-secret-key-not-used-in-production'

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django_digest',
)
