from .base import *  # noqa: F403
from django.core.exceptions import ImproperlyConfigured

DEBUG = False
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])  # noqa: F405
FILE_ENCRYPTION_KEY = env('FILE_ENCRYPTION_KEY', default='')  # noqa: F405
if len(SECRET_KEY) < 50 or SECRET_KEY == 'unsafe-secret':  # noqa: F405
    raise ImproperlyConfigured('Set a strong SECRET_KEY in production.')
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured('Set ALLOWED_HOSTS in production.')
if len(HMAC_SECRET) < 32 or HMAC_SECRET == 'dev-hmac-secret-do-not-use-in-prod':  # noqa: F405
    raise ImproperlyConfigured('Set a strong HMAC_SECRET in production.')
if (
    len(FILE_ENCRYPTION_KEY) < 32
    or FILE_ENCRYPTION_KEY == SECRET_KEY  # noqa: F405
):
    raise ImproperlyConfigured(
        'Set a distinct FILE_ENCRYPTION_KEY of at least 32 characters in production.'
    )
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000