import environ
import os

from pathlib import Path
from datetime import timedelta
from celery.schedules import crontab


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Create logs directory if it doesn't exist
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {message}',
            'style': '{',
        },
        'console': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': LOGS_DIR / 'django.log',
            'formatter': 'verbose',
        },
        'chatbot_file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': LOGS_DIR / 'chatbot.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'qa': {
            'handlers': ['console', 'chatbot_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'qa.chatbot_agent': {
            'handlers': ['console', 'chatbot_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'langchain': {
            'handlers': ['chatbot_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'openai': {
            'handlers': ['chatbot_file'],
            'level': 'WARNING',  # Only log warnings/errors from OpenAI
            'propagate': False,
        },
    },
}

# Alternative: Simple console logging for development
if os.getenv('DJANGO_DEBUG', 'False').lower() == 'true':
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    }


# Initialise environment variables
env = environ.Env(
    DEBUG=(bool, False)   # default DEBUG=False
)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

ALLOWED_HOSTS = ['*']

CORS_ALLOW_ALL_ORIGINS = True

# Application definition

INSTALLED_APPS = [
    #Default apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    #Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'storages',
    'corsheaders',
    
    #Local apps
    'accounts',
    'economy',
    'qa',
    'squads',
    'gamification',
    'learning',
    'moderation',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = 'SLN.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': []
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'SLN.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB'),
        'USER': env('POSTGRES_USER'),
        'PASSWORD': env('POSTGRES_PASSWORD'),
        'HOST': env('POSTGRES_HOST'),
        'PORT': env('POSTGRES_PORT'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ]
}

CELERY_IMPORTS = ['accounts.tasks',
                  'qa.tasks'
]

CELERY_TIMEZONE = 'UTC'

CELERY_BEAT_SCHEDULE = {
    # Clean up temp files older than 2 hours, every hour
    'cleanup-orphaned-temp-files': {
        'task': 'qa.tasks.cleanup_orphaned_temp_files',
        'schedule': crontab(minute=0),  # Every hour at minute 0
    },

    # Monitor storage usage daily at 2 AM
    'monitor-s3-storage': {
        'task': 'qa.tasks.monitor_s3_storage_usage',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },

    # Validate permanent attachments weekly
    'validate-permanent-attachments': {
        'task': 'qa.tasks.validate_permanent_attachments',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Weekly on Sunday at 3 AM
    },

    # More aggressive cleanup during peak hours (optional)
    'aggressive-temp-cleanup': {
        'task': 'qa.tasks.cleanup_temp_files_by_age',
        'schedule': crontab(minute='*/30', hour='9-17'),  # Every 30 min during business hours
        'kwargs': {'hours_old': 1}  # Clean files older than 1 hour during peak
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1),   # e.g. 30 minutes
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),      # e.g. 7 days
    "ROTATE_REFRESH_TOKENS": True,                    # optional: new refresh token each time
    "BLACKLIST_AFTER_ROTATION": True,                 # optional: old refresh token becomes invalid
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,                        # usually your Django SECRET_KEY
    "AUTH_HEADER_TYPES": ("Bearer",),                 # e.g. "Authorization: Bearer <token>"
}

AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
AWS_REGION_NAME = env('AWS_REGION_NAME')
AWS_QUERYSTRING_AUTH = False # public URL, no query params

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {},
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        "OPTIONS": {},
    },
}
DEFAULT_FILE_STORAGE = "storages.backends.s3.S3Storage"
STATICFILES_STORAGE = "storages.backends.s3.S3Storage"

CELERY_BROKER_URL = f"redis://{env('REDIS_HOST')}:{env('REDIS_PORT')}/{env('REDIS_DB')}"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{env('REDIS_HOST')}:{env('REDIS_PORT')}/{env('REDIS_DB')}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# --- Twilio / OTP settings ---
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default=None)
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default=None)
TWILIO_FROM_NUMBER = env("TWILIO_FROM_NUMBER", default=None)
TWILIO_VERIFY_SID = env("TWILIO_VERIFY_SID", default=None)

# OpenAI
OPENAI_API_KEY= env("OPENAI_API_KEY", default=None)
EMBEDDING_MODEL= env("EMBEDDING_MODEL", default=None)
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')
OPENAI_API_BASE = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')

#Lang Smith
LANGSMITH_TRACING = os.getenv('LANGSMITH_TRACING', 'false').lower() == 'true'
LANGSMITH_ENDPOINT = os.getenv('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com')
LANGSMITH_API_KEY = os.getenv('LANGSMITH_API_KEY')
LANGSMITH_PROJECT = os.getenv('LANGSMITH_PROJECT', 'SLN')

#Chatbot Config
# Chatbot Configuration
CHATBOT_CONFIG = {
    'TOKEN_LIMITS': {
        'MAX_CONVERSATION_TOKENS': int(os.getenv('CHATBOT_MAX_TOKENS', 12000)),
        'WARNING_TOKENS': int(os.getenv('CHATBOT_WARNING_TOKENS', 10000)),
        'CRITICAL_TOKENS': int(os.getenv('CHATBOT_CRITICAL_TOKENS', 11500)),
        'MAX_SINGLE_MESSAGE_TOKENS': int(os.getenv('CHATBOT_MAX_MESSAGE_TOKENS', 2000)),
    },
    'MODEL_CONFIG': {
        'model': OPENAI_MODEL,
        'temperature': float(os.getenv('CHATBOT_TEMPERATURE', 0)),
        'max_tokens': int(os.getenv('CHATBOT_MAX_RESPONSE_TOKENS', 1000)),
    }
}




