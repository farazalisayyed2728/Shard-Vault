import os
from pathlib import Path
import environ

# --------------------------------------------------
# BASE CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Load .env only when available (local development)
env_file = BASE_DIR / ".env"

if env_file.exists():
    environ.Env.read_env(env_file)


# --------------------------------------------------
# SECURITY
# --------------------------------------------------

DEBUG = False

SECRET_KEY = env(
    "SECRET_KEY",
    default=None
)

if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required.")

HMAC_SECRET = env(
    "HMAC_SECRET",
    default=SECRET_KEY
)

FILE_ENCRYPTION_KEY = env(
    "FILE_ENCRYPTION_KEY",
    default=None
)

if not FILE_ENCRYPTION_KEY:
    raise ValueError("FILE_ENCRYPTION_KEY is required.")

ALLOWED_HOSTS = [
    host.strip()
    for host in env(
        "DJANGO_ALLOWED_HOSTS",
        default=".vercel.app"
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in env(
        "CSRF_TRUSTED_ORIGINS",
        default=""
    ).split(",")
    if origin.strip()
]

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https"
)

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"


# --------------------------------------------------
# APPLICATIONS
# --------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "django_celery_beat",
    "axes",

    "apps.accounts",
    "apps.files",
    "apps.audit",

    "rest_framework",
    "drf_spectacular",
]


# --------------------------------------------------
# MIDDLEWARE
# --------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "axes.middleware.AxesMiddleware",
]


# --------------------------------------------------
# URL CONFIGURATION
# --------------------------------------------------

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"


# --------------------------------------------------
# TEMPLATES
# --------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --------------------------------------------------
# DATABASE - NEON POSTGRESQL
# --------------------------------------------------

DATABASE_URL = env("DATABASE_URL")

DATABASES = {
    "default": env.db_url_config(
        DATABASE_URL,
        engine="django.db.backends.postgresql"
    )
}

DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["OPTIONS"] = {
    **DATABASES["default"].get("OPTIONS", {}),
    "sslmode": "require",
}


# --------------------------------------------------
# CACHE & SESSIONS
# --------------------------------------------------

REDIS_URL = env("REDIS_URL", default=None)

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient"
            }
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "shardvault-cache",
        }
    }

SESSION_ENGINE = "django.contrib.sessions.backends.db"


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"
    },
]

LOGIN_REDIRECT_URL = "/files/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"


# --------------------------------------------------
# STATIC FILES
# --------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static"
]


# --------------------------------------------------
# GENERAL
# --------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"

USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------
# EMAIL
# --------------------------------------------------

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# --------------------------------------------------
# CELERY
# --------------------------------------------------

CELERY_BROKER_URL = REDIS_URL or "redis://127.0.0.1:6379/1"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"


# --------------------------------------------------
# SECURITY - AXES & CSP
# --------------------------------------------------

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_TEMPLATE = "errors/429.html"

CSP_DEFAULT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
CSP_SCRIPT_SRC = ("'self'",)


# --------------------------------------------------
# REST FRAMEWORK
# --------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}


SPECTACULAR_SETTINGS = {
    "TITLE": "ShardVault API",
    "DESCRIPTION": "Distributed File Storage System API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
