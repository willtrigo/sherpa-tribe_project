"""
Celery configuration for the Enterprise Task Management System.

This module configures Celery with Redis as broker and result backend,
implements proper error handling, monitoring, and follows Django best practices.
"""

import os
import logging
from typing import Dict, Any, Optional

from celery import Celery, signals
from celery.schedules import crontab
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.docker')

# Configure logging for Celery
logger = logging.getLogger('celery')

# Initialize Celery app instance
app = Celery('task_management_system')


class CeleryConfig:
    """Celery configuration class with enterprise-grade settings."""
    
    # Broker settings
    broker_url: str = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
    result_backend: str = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
    
    # Serialization settings
    task_serializer: str = 'json'
    result_serializer: str = 'json'
    accept_content: list = ['json']
    
    # Timezone configuration
    timezone: str = 'UTC'
    enable_utc: bool = True
    
    # Task execution settings
    task_always_eager: bool = os.environ.get('CELERY_ALWAYS_EAGER', 'False').lower() == 'true'
    task_eager_propagates: bool = True
    task_ignore_result: bool = False
    task_store_eager_result: bool = True
    
    # Worker settings
    worker_prefetch_multiplier: int = 1
    worker_max_tasks_per_child: int = 1000
    worker_disable_rate_limits: bool = False
    worker_log_format: str = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
    worker_task_log_format: str = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'
    
    # Result backend settings
    result_expires: int = 3600  # 1 hour
    result_compression: str = 'gzip'
    result_backend_max_retries: int = 10
    result_backend_retry_delay: float = 0.1
    
    # Task routing
    task_routes: Dict[str, Dict[str, str]] = {
        'celery_app.tasks.send_task_notification': {'queue': 'notifications'},
        'celery_app.tasks.generate_daily_summary': {'queue': 'reports'},
        'celery_app.tasks.check_overdue_tasks': {'queue': 'monitoring'},
        'celery_app.tasks.cleanup_archived_tasks': {'queue': 'maintenance'},
    }
    
    # Queue configuration
    task_default_queue: str = 'default'
    task_default_exchange: str = 'default'
    task_default_routing_key: str = 'default'
    
    # Retry settings
    task_acks_late: bool = True
    task_reject_on_worker_lost: bool = True
    task_soft_time_limit: int = 300  # 5 minutes
    task_time_limit: int = 600  # 10 minutes
    
    # Monitoring and logging
    worker_send_task_events: bool = True
    task_send_sent_event: bool = True
    
    # Security settings
    task_always_eager: bool = False
    task_store_eager_result: bool = True
    
    # Beat scheduler settings
    beat_scheduler: str = 'django_celery_beat.schedulers:DatabaseScheduler'
    beat_schedule: Dict[str, Dict[str, Any]] = {
        'generate-daily-summary': {
            'task': 'celery_app.tasks.generate_daily_summary',
            'schedule': crontab(hour=8, minute=0),  # Every day at 8:00 AM
            'options': {
                'queue': 'reports',
                'priority': 5,
            },
        },
        'check-overdue-tasks': {
            'task': 'celery_app.tasks.check_overdue_tasks',
            'schedule': crontab(minute='*/30'),  # Every 30 minutes
            'options': {
                'queue': 'monitoring',
                'priority': 8,
            },
        },
        'cleanup-archived-tasks': {
            'task': 'celery_app.tasks.cleanup_archived_tasks',
            'schedule': crontab(hour=2, minute=0, day_of_week=1),  # Every Monday at 2:00 AM
            'options': {
                'queue': 'maintenance',
                'priority': 2,
            },
        },
    }
    
    # Error handling
    task_annotations: Dict[str, Dict[str, Any]] = {
        '*': {
            'rate_limit': '100/m',
            'time_limit': 600,
            'soft_time_limit': 300,
        },
        'apps.tasks.tasks.send_task_notification': {
            'rate_limit': '50/m',
            'max_retries': 3,
            'default_retry_delay': 60,
        },
        'apps.tasks.tasks.generate_daily_summary': {
            'rate_limit': '10/h',
            'max_retries': 2,
            'default_retry_delay': 300,
        },
    }


# Configure Celery app with the configuration class
app.config_from_object(CeleryConfig)

# Auto-discover tasks from Django apps
app.autodiscover_tasks()


@signals.setup_logging.connect
def setup_celery_logging(**kwargs) -> None:
    """Configure logging for Celery workers."""
    import logging.config
    from django.conf import settings
    
    if hasattr(settings, 'LOGGING'):
        logging.config.dictConfig(settings.LOGGING)


@signals.worker_ready.connect
def worker_ready_handler(sender=None, **kwargs) -> None:
    """Handle worker ready signal."""
    logger.info(f"Worker {sender.hostname} is ready to process tasks")


@signals.worker_shutdown.connect
def worker_shutdown_handler(sender=None, **kwargs) -> None:
    """Handle worker shutdown signal."""
    logger.info(f"Worker {sender.hostname} is shutting down")


@signals.task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds) -> None:
    """Log task execution start."""
    logger.info(f"Task {task.name}[{task_id}] started with args={args}, kwargs={kwargs}")


@signals.task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, 
                        retval=None, state=None, **kwds) -> None:
    """Log task execution completion."""
    logger.info(f"Task {task.name}[{task_id}] completed with state={state}")


@signals.task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **kwds) -> None:
    """Handle task failures."""
    logger.error(
        f"Task {sender.name}[{task_id}] failed: {exception}",
        extra={
            'task_id': task_id,
            'task_name': sender.name,
            'exception': str(exception),
            'traceback': traceback,
        },
        exc_info=einfo
    )


@signals.task_retry.connect
def task_retry_handler(sender=None, task_id=None, reason=None, einfo=None, **kwds) -> None:
    """Handle task retries."""
    logger.warning(
        f"Task {sender.name}[{task_id}] retry: {reason}",
        extra={
            'task_id': task_id,
            'task_name': sender.name,
            'reason': str(reason),
        }
    )


@app.task(bind=True)
def debug_task(self) -> str:
    """Debug task for testing Celery configuration."""
    return f'Request: {self.request!r}'


@app.task(bind=True, name='celery.ping')
def ping_task(self) -> Dict[str, Any]:
    """Health check task for monitoring."""
    return {
        'status': 'ok',
        'timestamp': self.request.called_directly,
        'worker': self.request.hostname,
        'task_id': self.request.id,
    }


def get_celery_worker_status() -> Dict[str, Any]:
    """Get Celery worker status for health checks."""
    try:
        inspect = app.control.inspect()
        
        # Check if workers are available
        stats = inspect.stats()
        active = inspect.active()
        scheduled = inspect.scheduled()
        
        return {
            'status': 'healthy' if stats else 'unhealthy',
            'workers': list(stats.keys()) if stats else [],
            'active_tasks': sum(len(tasks) for tasks in (active or {}).values()),
            'scheduled_tasks': sum(len(tasks) for tasks in (scheduled or {}).values()),
            'total_workers': len(stats) if stats else 0,
        }
    except Exception as exc:
        logger.error(f"Failed to get Celery worker status: {exc}")
        return {
            'status': 'error',
            'error': str(exc),
            'workers': [],
            'active_tasks': 0,
            'scheduled_tasks': 0,
            'total_workers': 0,
        }


def revoke_all_tasks(terminate: bool = False) -> Dict[str, Any]:
    """Revoke all active tasks (emergency function)."""
    try:
        inspect = app.control.inspect()
        active_tasks = inspect.active()
        
        if not active_tasks:
            return {'status': 'success', 'message': 'No active tasks to revoke', 'revoked_count': 0}
        
        task_ids = []
        for worker_tasks in active_tasks.values():
            task_ids.extend([task['id'] for task in worker_tasks])
        
        app.control.revoke(task_ids, terminate=terminate)
        
        return {
            'status': 'success',
            'message': f'Revoked {len(task_ids)} tasks',
            'revoked_count': len(task_ids),
            'terminated': terminate,
        }
    except Exception as exc:
        logger.error(f"Failed to revoke tasks: {exc}")
        return {
            'status': 'error',
            'error': str(exc),
            'revoked_count': 0,
        }


# Export the configured Celery app
__all__ = ['app', 'get_celery_worker_status', 'revoke_all_tasks']
