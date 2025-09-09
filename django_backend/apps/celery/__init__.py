"""
Celery application configuration and initialization.

This module configures the Celery application instance for the task management system,
including broker configuration, task discovery, and beat schedule setup.
"""

import os
from celery import Celery
from django.conf import settings
from kombu import Queue, Exchange

# Set default Django settings module for 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.docker')

# Create Celery application instance
app = Celery('task_management_system')

# Configure Celery using Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered Django apps
app.autodiscover_tasks()

# Task routing configuration
app.conf.task_routes = {
    'celery_app.tasks.send_task_notification': {'queue': 'notifications'},
    'celery_app.tasks.generate_daily_summary': {'queue': 'reports'},
    'celery_app.tasks.check_overdue_tasks': {'queue': 'monitoring'},
    'celery_app.tasks.cleanup_archived_tasks': {'queue': 'maintenance'},
    'celery_app.tasks.process_task_workflow': {'queue': 'workflows'},
    'celery_app.tasks.calculate_team_metrics': {'queue': 'analytics'},
    'celery_app.tasks.send_bulk_notifications': {'queue': 'bulk_operations'},
    'celery_app.tasks.export_task_data': {'queue': 'exports'},
}

# Queue configuration with different priorities and settings
app.conf.task_queues = (
    Queue('default', Exchange('default'), routing_key='default'),
    Queue('notifications', Exchange('notifications', type='direct'), 
          routing_key='notifications', delivery_mode=2),
    Queue('reports', Exchange('reports', type='direct'), 
          routing_key='reports', delivery_mode=2),
    Queue('monitoring', Exchange('monitoring', type='direct'), 
          routing_key='monitoring', delivery_mode=2),
    Queue('maintenance', Exchange('maintenance', type='direct'), 
          routing_key='maintenance', delivery_mode=2),
    Queue('workflows', Exchange('workflows', type='direct'), 
          routing_key='workflows', delivery_mode=2),
    Queue('analytics', Exchange('analytics', type='direct'), 
          routing_key='analytics', delivery_mode=2),
    Queue('bulk_operations', Exchange('bulk_operations', type='direct'), 
          routing_key='bulk_operations', delivery_mode=2),
    Queue('exports', Exchange('exports', type='direct'), 
          routing_key='exports', delivery_mode=2),
)

# Celery Beat schedule configuration
app.conf.beat_schedule = {
    'generate-daily-summary': {
        'task': 'celery_app.tasks.generate_daily_summary',
        'schedule': 86400.0,  # 24 hours in seconds
        'options': {
            'queue': 'reports',
            'priority': 7,
        }
    },
    'check-overdue-tasks': {
        'task': 'celery_app.tasks.check_overdue_tasks',
        'schedule': 3600.0,  # 1 hour in seconds
        'options': {
            'queue': 'monitoring',
            'priority': 8,
        }
    },
    'cleanup-archived-tasks': {
        'task': 'celery_app.tasks.cleanup_archived_tasks',
        'schedule': 604800.0,  # 1 week in seconds
        'options': {
            'queue': 'maintenance',
            'priority': 3,
        }
    },
    'calculate-team-metrics': {
        'task': 'celery_app.tasks.calculate_team_metrics',
        'schedule': 3600.0,  # 1 hour in seconds
        'options': {
            'queue': 'analytics',
            'priority': 5,
        }
    },
    'process-pending-workflows': {
        'task': 'celery_app.tasks.process_pending_workflows',
        'schedule': 300.0,  # 5 minutes in seconds
        'options': {
            'queue': 'workflows',
            'priority': 9,
        }
    },
}

# Additional Celery configuration
app.conf.update(
    # Task serialization
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    
    # Timezone configuration
    timezone=settings.TIME_ZONE,
    enable_utc=True,
    
    # Task execution configuration
    task_always_eager=False,
    task_eager_propagates=True,
    task_ignore_result=False,
    task_store_eager_result=True,
    
    # Task retry configuration
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Worker configuration
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,
    
    # Result backend configuration
    result_expires=3600,  # 1 hour
    result_persistent=True,
    
    # Task compression
    task_compression='gzip',
    result_compression='gzip',
    
    # Security configuration
    task_always_eager=getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False),
    
    # Monitoring and logging
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    # Beat configuration
    beat_schedule_filename='celerybeat-schedule',
    beat_scheduler='django_celery_beat.schedulers:DatabaseScheduler',
)

# Task annotations for specific task configurations
app.conf.task_annotations = {
    'celery_app.tasks.send_task_notification': {
        'rate_limit': '100/m',
        'priority': 8,
        'routing_key': 'notifications',
    },
    'celery_app.tasks.generate_daily_summary': {
        'rate_limit': '1/h',
        'priority': 7,
        'routing_key': 'reports',
    },
    'celery_app.tasks.check_overdue_tasks': {
        'rate_limit': '1/h',
        'priority': 8,
        'routing_key': 'monitoring',
    },
    'celery_app.tasks.cleanup_archived_tasks': {
        'rate_limit': '1/d',
        'priority': 3,
        'routing_key': 'maintenance',
    },
    'celery_app.tasks.send_bulk_notifications': {
        'rate_limit': '10/m',
        'priority': 6,
        'routing_key': 'bulk_operations',
    },
    'celery_app.tasks.export_task_data': {
        'rate_limit': '5/m',
        'priority': 4,
        'routing_key': 'exports',
        'soft_time_limit': 300,  # 5 minutes
        'time_limit': 600,       # 10 minutes
    },
}


@app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery configuration."""
    print(f'Request: {self.request!r}')
    return {'status': 'success', 'worker_id': self.request.id}


# Error handling for Celery startup
@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Setup additional periodic tasks after Celery configuration."""
    try:
        # Add any additional periodic tasks here if needed
        sender.add_periodic_task(
            30.0,  # Every 30 seconds
            debug_task.s(),
            name='debug-task-every-30s',
            options={'queue': 'default'}
        )
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error setting up periodic tasks: {exc}')


# Ensure proper worker shutdown
@app.on_after_finalize.connect
def setup_worker_signals(sender, **kwargs):
    """Setup worker signal handlers for graceful shutdown."""
    import signal
    import logging
    
    logger = logging.getLogger(__name__)
    
    def signal_handler(signum, frame):
        logger.info(f'Received signal {signum}, shutting down gracefully...')
        sender.control.shutdown()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
