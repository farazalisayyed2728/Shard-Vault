import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

app = Celery('shardvault')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'check-node-health': {
        'task': 'apps.files.tasks.check_node_health',
        'schedule': 10.0,
    },
    'repair-replicas': {
        'task': 'apps.files.tasks.repair_replicas',
        'schedule': 60.0,
    },
    'scrub-replicas': {
        'task': 'apps.files.tasks.scrub_replicas',
        'schedule': crontab(minute='0'),
    },
    'cleanup-stale-uploads': {
        'task': 'apps.files.tasks.cleanup_stale_uploads',
        'schedule': crontab(hour='*/12', minute='0'),
    },
    'garbage-collect-trash': {
        'task': 'apps.files.tasks.garbage_collect_trash',
        'schedule': crontab(hour='3', minute='0'),
    },
}
