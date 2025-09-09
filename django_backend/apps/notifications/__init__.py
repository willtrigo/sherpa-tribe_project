"""
Notifications Application Module

This module handles all notification-related functionality for the Enterprise Task Management System.
It provides comprehensive notification management including email notifications, webhook notifications,
notification preferences, templates, and delivery tracking.

The notification system is designed to be:
- Extensible: Easy to add new notification types and channels
- Reliable: Includes retry mechanisms and delivery tracking
- Configurable: Per-user notification preferences
- Auditable: Complete delivery and failure tracking
- Template-based: Reusable notification templates with variable substitution

Key Components:
- NotificationManager: Core notification orchestration
- NotificationChannel: Abstract base for different delivery methods
- NotificationTemplate: Template system for consistent messaging
- NotificationPreference: User-specific notification settings
- NotificationDelivery: Delivery tracking and retry logic

Integration Points:
- Celery: Asynchronous notification processing
- Django Signals: Automatic notification triggering
- Task Management: Task lifecycle notifications
- User Management: User activity notifications
"""

default_app_config = 'apps.notifications.apps.NotificationsConfig'

__version__ = '1.0.0'
__author__ = 'Enterprise Task Management System'
__email__ = 'dev@taskmanagement.com'

# Notification Types Registry
NOTIFICATION_TYPES = {
    'TASK_CREATED': 'task_created',
    'TASK_ASSIGNED': 'task_assigned',
    'TASK_UPDATED': 'task_updated',
    'TASK_COMPLETED': 'task_completed',
    'TASK_OVERDUE': 'task_overdue',
    'TASK_COMMENTED': 'task_commented',
    'TASK_STATUS_CHANGED': 'task_status_changed',
    'TASK_PRIORITY_CHANGED': 'task_priority_changed',
    'TASK_DUE_DATE_REMINDER': 'task_due_date_reminder',
    'TASK_ESCALATED': 'task_escalated',
    'USER_MENTIONED': 'user_mentioned',
    'TEAM_INVITATION': 'team_invitation',
    'DAILY_SUMMARY': 'daily_summary',
    'SYSTEM_ALERT': 'system_alert',
}

# Notification Channels Registry
NOTIFICATION_CHANNELS = {
    'EMAIL': 'email',
    'WEBHOOK': 'webhook',
    'IN_APP': 'in_app',
    'SLACK': 'slack',
    'TEAMS': 'teams',
    'SMS': 'sms',
}

# Notification Priorities
NOTIFICATION_PRIORITIES = {
    'LOW': 1,
    'NORMAL': 2,
    'HIGH': 3,
    'CRITICAL': 4,
    'URGENT': 5,
}

# Delivery Status Constants
DELIVERY_STATUS = {
    'PENDING': 'pending',
    'PROCESSING': 'processing',
    'SENT': 'sent',
    'DELIVERED': 'delivered',
    'FAILED': 'failed',
    'RETRY': 'retry',
    'CANCELLED': 'cancelled',
    'BOUNCED': 'bounced',
}

# Template Context Processors
TEMPLATE_CONTEXT_PROCESSORS = [
    'apps.notifications.context_processors.notification_context',
    'apps.notifications.context_processors.user_preferences_context',
]

# Default Configuration
DEFAULT_NOTIFICATION_SETTINGS = {
    'MAX_RETRY_ATTEMPTS': 3,
    'RETRY_DELAY_MINUTES': [5, 15, 60],  # Progressive delay
    'BATCH_SIZE': 100,
    'RATE_LIMIT_PER_MINUTE': 60,
    'TEMPLATE_CACHE_TIMEOUT': 3600,  # 1 hour
    'CLEANUP_DAYS': 30,  # Days to keep delivery logs
    'DEFAULT_FROM_EMAIL': 'noreply@taskmanagement.com',
    'DEFAULT_WEBHOOK_TIMEOUT': 30,  # seconds
}

# Notification Event Registry for Django Signals
NOTIFICATION_EVENTS = {
    'post_save': [
        'apps.tasks.models.Task',
        'apps.tasks.models.Comment',
        'apps.users.models.User',
    ],
    'post_delete': [
        'apps.tasks.models.Task',
    ],
    'm2m_changed': [
        'apps.tasks.models.Task.assigned_to.through',
        'apps.tasks.models.Task.tags.through',
    ],
}

# Export public API
__all__ = [
    'NOTIFICATION_TYPES',
    'NOTIFICATION_CHANNELS', 
    'NOTIFICATION_PRIORITIES',
    'DELIVERY_STATUS',
    'DEFAULT_NOTIFICATION_SETTINGS',
    'NOTIFICATION_EVENTS',
]
