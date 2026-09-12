"""Django settings for the Karaoke POS project."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-insecure-secret-key-change-me-in-production",
)

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "inventory",
    "tables",
    "tabs",
    "orders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Thermal printer (ESC/POS) — kitchen tickets (#228)
# Every value comes from the environment so the machine sitting next to the
# printer can be configured without touching code. See the README for the full
# description of each variable.

# CUPS queue name (Linux) or Windows printer name. When set, it is tried before
# the list of default names.
KARAOKE_PRINTER_NAME = os.getenv("KARAOKE_PRINTER_NAME", "")

# Path to the device directly (e.g. /dev/usb/lp0 on Linux, COM3 on Windows).
KARAOKE_PRINTER_DEVICE = os.getenv("KARAOKE_PRINTER_DEVICE", "")

# In development there is no printer: write the ticket to disk instead of
# failing, so the kitchen screen can still be exercised end to end.
KARAOKE_PRINTER_DRY_RUN = os.getenv("KARAOKE_PRINTER_DRY_RUN", "").lower() in {
    "1",
    "true",
    "yes",
}
KARAOKE_PRINTER_DUMP_DIR = Path(
    os.getenv("KARAOKE_PRINTER_DUMP_DIR", str(BASE_DIR / "receipts_out"))
)

# Paper width in characters. 48 = 80mm roll (Elgin i9 / Bematech). The left
# margin pushes the text off the very edge of the paper; the content then
# occupies KARAOKE_RECEIPT_WIDTH - KARAOKE_RECEIPT_LEFT_MARGIN columns.
KARAOKE_RECEIPT_WIDTH = int(os.getenv("KARAOKE_RECEIPT_WIDTH", "48"))
KARAOKE_RECEIPT_LEFT_MARGIN = int(os.getenv("KARAOKE_RECEIPT_LEFT_MARGIN", "2"))

# Authentication
# The site root URL ("/") doubles as the branded landing/login page, so
# unauthenticated visitors of any protected page are redirected there.
# A successful login lands on the logged-in home page stub.
LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:login"