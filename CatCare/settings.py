from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY')

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'CatCare.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'CatCare.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

LANGUAGE_CODE = 'vi'

TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Ho_Chi_Minh')

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# MQTT Settings
MQTT_SETTINGS = {
    'BROKER': os.getenv('MQTT_BROKER', 'broker.emqx.io'),
    'PORT': int(os.getenv('MQTT_PORT', '1883')),
    'CLIENT_ID': os.getenv('MQTT_CLIENT_ID', 'Django_CatCare_Server'),
    'USERNAME': os.getenv('MQTT_USERNAME', ''),
    'PASSWORD': os.getenv('MQTT_PASSWORD', ''),
    'TOPICS': {
        'FEED': os.getenv('MQTT_TOPIC_FEED', 'catcare/feed'),
        'MODE': os.getenv('MQTT_TOPIC_MODE', 'catcare/mode'),
        'STATUS': os.getenv('MQTT_TOPIC_STATUS', 'catcare/status'),
        'IMAGE': os.getenv('MQTT_TOPIC_IMAGE', 'catcare/image'),
        'FEED_LOG': os.getenv('MQTT_TOPIC_FEED_LOG', 'catcare/feed_log'),
        'IMAGE_CHUNK': os.getenv('MQTT_TOPIC_IMAGE_CHUNK', 'catcare/image_chunk'),
        'DETECTION': os.getenv('MQTT_TOPIC_DETECTION', 'catcare/detection'),
        'CAMERA_CONTROL': os.getenv('MQTT_TOPIC_CAMERA_CONTROL', 'catcare/camera_control'),
    }
}

# Camera Settings
CAMERA_SETTINGS = {
    'FLIP_HORIZONTAL': os.getenv('CAMERA_FLIP_HORIZONTAL', 'False').lower() == 'true',
    'FLIP_VERTICAL': os.getenv('CAMERA_FLIP_VERTICAL', 'False').lower() == 'true',
    'ROTATE_180': os.getenv('CAMERA_ROTATE_180', 'False').lower() == 'true',
    'DETECTION_ENABLED': os.getenv('CAMERA_DETECTION_ENABLED', 'True').lower() == 'true',
    'DETECTION_INTERVAL': int(os.getenv('CAMERA_DETECTION_INTERVAL', '5')),  # seconds
    'DETECTION_CONFIDENCE_THRESHOLD': float(os.getenv('DETECTION_CONFIDENCE_THRESHOLD', '0.5')),
}


# ESP32 Settings
ESP32_IP = os.getenv('ESP32_IP', '192.168.100.141')
ESP32_STREAM_URL = f"http://{ESP32_IP}/stream"