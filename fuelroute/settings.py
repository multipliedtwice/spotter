import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'local-development-only')
DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
INSTALLED_APPS = ['django.contrib.contenttypes', 'planner']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware']
ROOT_URLCONF = 'fuelroute.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True}]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
OSRM_BASE_URL = os.environ.get('OSRM_BASE_URL', 'https://router.project-osrm.org').rstrip('/')
OSRM_PROFILE = os.environ.get('OSRM_PROFILE', 'driving')
OSRM_DATASET_VERSION = os.environ.get('OSRM_DATASET_VERSION', 'default')
OSRM_TIMEOUT = float(os.environ.get('OSRM_TIMEOUT', '20'))
OSRM_ENDPOINT_RADIUS_METERS = float(os.environ.get('OSRM_ENDPOINT_RADIUS_METERS', '1000'))
OSRM_STOP_RADIUS_METERS = float(os.environ.get('OSRM_STOP_RADIUS_METERS', '100'))
FUEL_CORRIDOR_MILES = float(os.environ.get('FUEL_CORRIDOR_MILES', '5'))
