"""
Celery Beat Schedule Configuration

This module defines the periodic task schedules for the Django application using Celery Beat.
All scheduled tasks are configured here with their respective timing and arguments.

Author: Task Management System
Version: 1.0.0
"""

from datetime import timedelta
from typing import Dict, Any

from celery.schedules import crontab
from django.conf import settings


class ScheduleConfig:
    """
    Configuration class for Celery Beat schedules.
    
    This class centralizes all schedule configurations and provides
    a clean interface for managing periodic task schedules.
    """
    
    # Schedule intervals as class constants for maintainability
    DAILY_SUMMARY_HOUR = 8  # 8 AM daily
    OVERDUE_CHECK_INTERVAL_MINUTES = 60  # Every hour
    CLEANUP_DAY_OF_WEEK = 0  # Monday (0=Monday, 6=Sunday)
    CLEANUP_HOUR = 2  # 2 AM
    HEALTH_CHECK_INTERVAL_MINUTES = 30  # Every 30 minutes
    
    @classmethod
    def get_beat_schedule(cls) -> Dict[str, Dict[str, Any]]:
        """
        Generate the complete Celery Beat schedule configuration.
        
        Returns:
            Dict[str, Dict[str, Any]]: Complete schedule configuration for Celery Beat
            
        Note:
            All times are in UTC. Adjust CELERY_TIMEZONE in settings for local time.
        """
        return {
            # Daily summary generation task
            'generate-daily-summary': {
                'task': 'celery_app.tasks.generate_daily_summary',
                'schedule': crontab(
                    hour=cls.DAILY_SUMMARY_HOUR,
                    minute=0
                ),
                'options': {
                    'expires': 3600,  # Expire after 1 hour if not executed
                    'retry': True,
                    'retry_policy': {
                        'max_retries': 3,
                        'interval_start': 0,
                        'interval_step': 0.2,
                        'interval_max': 0.2,
                    }
                },
                'kwargs': {
                    'notification_enabled': True,
                    'include_metrics': True
                }
            },
            
            # Hourly overdue tasks check
            'check-overdue-tasks': {
                'task': 'celery_app.tasks.check_overdue_tasks',
                'schedule': timedelta(minutes=cls.OVERDUE_CHECK_INTERVAL_MINUTES),
                'options': {
                    'expires': 1800,  # Expire after 30 minutes
                    'retry': True,
                    'retry_policy': {
                        'max_retries': 2,
                        'interval_start': 0,
                        'interval_step': 0.1,
                        'interval_max': 0.1,
                    }
                },
                'kwargs': {
                    'send_notifications': True,
                    'escalate_critical': True
                }
            },
            
            # Weekly cleanup of archived tasks
            'cleanup-archived-tasks': {
                'task': 'celery_app.tasks.cleanup_archived_tasks',
                'schedule': crontab(
                    day_of_week=cls.CLEANUP_DAY_OF_WEEK,
                    hour=cls.CLEANUP_HOUR,
                    minute=0
                ),
                'options': {
                    'expires': 7200,  # Expire after 2 hours
                    'retry': True,
                    'retry_policy': {
                        'max_retries': 1,
                        'interval_start': 0,
                        'interval_step': 0.5,
                        'interval_max': 0.5,
                    }
                },
                'kwargs': {
                    'retention_days': getattr(settings, 'ARCHIVED_TASKS_RETENTION_DAYS', 30),
                    'batch_size': 100,
                    'dry_run': False
                }
            },
            
            # System health check
            'system-health-check': {
                'task': 'celery_app.tasks.system_health_check',
                'schedule': timedelta(minutes=cls.HEALTH_CHECK_INTERVAL_MINUTES),
                'options': {
                    'expires': 900,  # Expire after 15 minutes
                    'retry': False,  # Don't retry health checks
                },
                'kwargs': {
                    'check_database': True,
                    'check_redis': True,
                    'check_disk_space': True
                }
            },
            
            # Generate weekly reports
            'generate-weekly-reports': {
                'task': 'celery_app.tasks.generate_weekly_reports',
                'schedule': crontab(
                    day_of_week=1,  # Tuesday
                    hour=9,
                    minute=0
                ),
                'options': {
                    'expires': 10800,  # Expire after 3 hours
                    'retry': True,
                    'retry_policy': {
                        'max_retries': 2,
                        'interval_start': 0,
                        'interval_step': 1.0,
                        'interval_max': 1.0,
                    }
                },
                'kwargs': {
                    'include_charts': True,
                    'send_email': True,
                    'export_formats': ['pdf', 'csv']
                }
            },
            
            # Cache warming for frequently accessed data
            'warm-cache': {
                'task': 'celery_app.tasks.warm_cache',
                'schedule': crontab(minute='*/15'),  # Every 15 minutes
                'options': {
                    'expires': 600,  # Expire after 10 minutes
                    'retry': False,
                },
                'kwargs': {
                    'cache_keys': [
                        'active_tasks_count',
                        'user_stats',
                        'priority_distribution'
                    ]
                }
            },
            
            # Sync external integrations (if applicable)
            'sync-external-systems': {
                'task': 'celery_app.tasks.sync_external_systems',
                'schedule': crontab(minute=0),  # Every hour at minute 0
                'options': {
                    'expires': 2700,  # Expire after 45 minutes
                    'retry': True,
                    'retry_policy': {
                        'max_retries': 3,
                        'interval_start': 0,
                        'interval_step': 0.3,
                        'interval_max': 0.3,
                    }
                },
                'kwargs': {
                    'sync_users': True,
                    'sync_teams': True,
                    'update_metadata': True
                }
            }
        }


class DevelopmentScheduleConfig(ScheduleConfig):
    """
    Development-specific schedule configuration.
    
    Extends the base configuration with development-friendly intervals
    for faster testing and debugging.
    """
    
    # Override intervals for development
    OVERDUE_CHECK_INTERVAL_MINUTES = 5  # Every 5 minutes in development
    HEALTH_CHECK_INTERVAL_MINUTES = 10  # Every 10 minutes in development
    
    @classmethod
    def get_beat_schedule(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get development-specific beat schedule with shorter intervals.
        
        Returns:
            Dict[str, Dict[str, Any]]: Development schedule configuration
        """
        schedule = super().get_beat_schedule()
        
        # Modify specific schedules for development
        if getattr(settings, 'DEBUG', False):
            # Run daily summary every 30 minutes in development
            schedule['generate-daily-summary']['schedule'] = timedelta(minutes=30)
            
            # Run cleanup every hour in development (with dry_run=True)
            schedule['cleanup-archived-tasks']['schedule'] = timedelta(hours=1)
            schedule['cleanup-archived-tasks']['kwargs']['dry_run'] = True
            
            # Add development-specific task
            schedule['development-debug-task'] = {
                'task': 'celery_app.tasks.debug_task',
                'schedule': timedelta(minutes=15),
                'options': {'expires': 600},
                'kwargs': {'environment': 'development'}
            }
        
        return schedule


class ProductionScheduleConfig(ScheduleConfig):
    """
    Production-specific schedule configuration.
    
    Extends the base configuration with production-optimized settings
    for better performance and reliability.
    """
    
    @classmethod
    def get_beat_schedule(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get production-specific beat schedule with optimized settings.
        
        Returns:
            Dict[str, Dict[str, Any]]: Production schedule configuration
        """
        schedule = super().get_beat_schedule()
        
        # Add production-specific optimizations
        for task_name, task_config in schedule.items():
            # Increase expiration times in production
            if 'expires' in task_config.get('options', {}):
                task_config['options']['expires'] *= 2
            
            # Add monitoring and alerting options
            task_config['options'].update({
                'track_started': True,
                'send_events': True,
            })
        
        # Add production-specific monitoring task
        schedule['monitor-system-performance'] = {
            'task': 'celery_app.tasks.monitor_system_performance',
            'schedule': timedelta(minutes=5),
            'options': {
                'expires': 300,
                'retry': False,
                'track_started': True,
                'send_events': True,
            },
            'kwargs': {
                'collect_metrics': True,
                'alert_thresholds': {
                    'cpu_usage': 80,
                    'memory_usage': 85,
                    'queue_length': 1000
                }
            }
        }
        
        return schedule


def get_schedule_config() -> Dict[str, Dict[str, Any]]:
    """
    Factory function to get the appropriate schedule configuration based on environment.
    
    Returns:
        Dict[str, Dict[str, Any]]: Environment-specific schedule configuration
        
    Raises:
        ImportError: If Django settings are not properly configured
    """
    try:
        environment = getattr(settings, 'ENVIRONMENT', 'development').lower()
        
        if environment == 'production':
            return ProductionScheduleConfig.get_beat_schedule()
        elif environment == 'development':
            return DevelopmentScheduleConfig.get_beat_schedule()
        else:
            # Default to base configuration for other environments
            return ScheduleConfig.get_beat_schedule()
            
    except Exception as exc:
        # Fallback to base configuration if settings are not available
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to load environment-specific schedule: {exc}")
        return ScheduleConfig.get_beat_schedule()


# Export the main schedule configuration
# This is what Celery Beat will use
CELERY_BEAT_SCHEDULE = get_schedule_config()

# Timezone configuration for Celery Beat
CELERY_TIMEZONE = getattr(settings, 'CELERY_TIMEZONE', 'UTC')

# Additional Beat configuration
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_SCHEDULE_FILENAME = 'celerybeat-schedule'
