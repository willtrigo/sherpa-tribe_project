"""
Notification system choices and constants.

This module defines all choice constants used throughout the notification system,
including notification types, delivery methods, priorities, and status tracking.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationType(models.TextChoices):
    """
    Defines the various types of notifications that can be sent within the system.
    
    These choices determine the notification content, template selection,
    and routing logic for different business events.
    """
    # Task-related notifications
    TASK_CREATED = "task_created", _("Task Created")
    TASK_UPDATED = "task_updated", _("Task Updated")
    TASK_ASSIGNED = "task_assigned", _("Task Assigned")
    TASK_UNASSIGNED = "task_unassigned", _("Task Unassigned")
    TASK_STATUS_CHANGED = "task_status_changed", _("Task Status Changed")
    TASK_PRIORITY_CHANGED = "task_priority_changed", _("Task Priority Changed")
    TASK_DUE_DATE_CHANGED = "task_due_date_changed", _("Task Due Date Changed")
    TASK_COMPLETED = "task_completed", _("Task Completed")
    TASK_ARCHIVED = "task_archived", _("Task Archived")
    TASK_DELETED = "task_deleted", _("Task Deleted")
    TASK_COMMENT_ADDED = "task_comment_added", _("Task Comment Added")
    
    # Time-sensitive notifications
    TASK_DUE_SOON = "task_due_soon", _("Task Due Soon")
    TASK_OVERDUE = "task_overdue", _("Task Overdue")
    TASK_DEADLINE_APPROACHING = "task_deadline_approaching", _("Task Deadline Approaching")
    
    # Workflow and automation notifications
    TASK_ESCALATED = "task_escalated", _("Task Escalated")
    TASK_AUTO_ASSIGNED = "task_auto_assigned", _("Task Auto-Assigned")
    WORKFLOW_COMPLETED = "workflow_completed", _("Workflow Completed")
    SLA_BREACH_WARNING = "sla_breach_warning", _("SLA Breach Warning")
    SLA_BREACHED = "sla_breached", _("SLA Breached")
    
    # Team and collaboration notifications
    TEAM_MEMBER_ADDED = "team_member_added", _("Team Member Added")
    TEAM_MEMBER_REMOVED = "team_member_removed", _("Team Member Removed")
    TEAM_WORKLOAD_ALERT = "team_workload_alert", _("Team Workload Alert")
    
    # System notifications
    SYSTEM_MAINTENANCE = "system_maintenance", _("System Maintenance")
    SYSTEM_UPDATE = "system_update", _("System Update")
    DAILY_SUMMARY = "daily_summary", _("Daily Summary")
    WEEKLY_REPORT = "weekly_report", _("Weekly Report")
    DATA_EXPORT_READY = "data_export_ready", _("Data Export Ready")
    BACKUP_COMPLETED = "backup_completed", _("Backup Completed")
    
    # Security and audit notifications
    SECURITY_ALERT = "security_alert", _("Security Alert")
    LOGIN_ANOMALY = "login_anomaly", _("Login Anomaly")
    PASSWORD_CHANGED = "password_changed", _("Password Changed")
    ACCOUNT_LOCKED = "account_locked", _("Account Locked")


class NotificationDeliveryMethod(models.TextChoices):
    """
    Defines the available delivery channels for notifications.
    
    Each method represents a different communication channel
    with specific delivery characteristics and requirements.
    """
    EMAIL = "email", _("Email")
    SMS = "sms", _("SMS")
    PUSH = "push", _("Push Notification")
    IN_APP = "in_app", _("In-App Notification")
    WEBHOOK = "webhook", _("Webhook")
    SLACK = "slack", _("Slack")
    MICROSOFT_TEAMS = "ms_teams", _("Microsoft Teams")
    DISCORD = "discord", _("Discord")
    
    @classmethod
    def get_real_time_methods(cls) -> list[str]:
        """Return delivery methods that support real-time notifications."""
        return [cls.PUSH, cls.IN_APP, cls.WEBHOOK, cls.SLACK, cls.MICROSOFT_TEAMS]
    
    @classmethod
    def get_async_methods(cls) -> list[str]:
        """Return delivery methods that are processed asynchronously."""
        return [cls.EMAIL, cls.SMS, cls.WEBHOOK]


class NotificationPriority(models.TextChoices):
    """
    Defines priority levels for notification processing and delivery.
    
    Higher priority notifications are processed first and may use
    different delivery mechanisms or retry strategies.
    """
    LOW = "low", _("Low Priority")
    NORMAL = "normal", _("Normal Priority")
    HIGH = "high", _("High Priority")
    URGENT = "urgent", _("Urgent Priority")
    CRITICAL = "critical", _("Critical Priority")
    
    @classmethod
    def get_processing_order(cls) -> list[str]:
        """Return priorities in processing order (highest first)."""
        return [cls.CRITICAL, cls.URGENT, cls.HIGH, cls.NORMAL, cls.LOW]
    
    @classmethod
    def get_immediate_delivery_priorities(cls) -> list[str]:
        """Return priorities that require immediate delivery."""
        return [cls.CRITICAL, cls.URGENT]


class NotificationStatus(models.TextChoices):
    """
    Tracks the lifecycle status of notifications through the delivery process.
    
    These states enable monitoring, debugging, and retry logic
    for the notification delivery system.
    """
    PENDING = "pending", _("Pending")
    QUEUED = "queued", _("Queued for Delivery")
    PROCESSING = "processing", _("Processing")
    SENT = "sent", _("Successfully Sent")
    DELIVERED = "delivered", _("Delivered to Recipient")
    READ = "read", _("Read by Recipient")
    FAILED = "failed", _("Delivery Failed")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")
    RETRYING = "retrying", _("Retrying Delivery")
    
    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """Return statuses indicating active/in-progress notifications."""
        return [cls.PENDING, cls.QUEUED, cls.PROCESSING, cls.RETRYING]
    
    @classmethod
    def get_final_statuses(cls) -> list[str]:
        """Return statuses indicating completed notification lifecycle."""
        return [cls.DELIVERED, cls.READ, cls.FAILED, cls.EXPIRED, cls.CANCELLED]
    
    @classmethod
    def get_successful_statuses(cls) -> list[str]:
        """Return statuses indicating successful delivery."""
        return [cls.SENT, cls.DELIVERED, cls.READ]


class NotificationFrequency(models.TextChoices):
    """
    Defines frequency settings for recurring notifications and user preferences.
    
    Used to control notification batching, digest generation,
    and user subscription management.
    """
    IMMEDIATE = "immediate", _("Immediate")
    HOURLY = "hourly", _("Hourly Digest")
    DAILY = "daily", _("Daily Digest")
    WEEKLY = "weekly", _("Weekly Digest")
    NEVER = "never", _("Never")
    
    @classmethod
    def get_digest_frequencies(cls) -> list[str]:
        """Return frequencies that support digest/batch delivery."""
        return [cls.HOURLY, cls.DAILY, cls.WEEKLY]


class NotificationTemplate(models.TextChoices):
    """
    Defines available notification templates for consistent messaging.
    
    Templates are mapped to notification types and delivery methods
    to ensure proper formatting and localization.
    """
    # Email templates
    EMAIL_TASK_ASSIGNED = "email_task_assigned", _("Email: Task Assigned")
    EMAIL_TASK_DUE = "email_task_due", _("Email: Task Due")
    EMAIL_DAILY_SUMMARY = "email_daily_summary", _("Email: Daily Summary")
    EMAIL_SYSTEM_ALERT = "email_system_alert", _("Email: System Alert")
    
    # In-app templates
    INAPP_TASK_UPDATE = "inapp_task_update", _("In-App: Task Update")
    INAPP_MENTION = "inapp_mention", _("In-App: Mention")
    INAPP_SYSTEM_MESSAGE = "inapp_system_message", _("In-App: System Message")
    
    # Push notification templates
    PUSH_TASK_REMINDER = "push_task_reminder", _("Push: Task Reminder")
    PUSH_URGENT_ALERT = "push_urgent_alert", _("Push: Urgent Alert")
    
    # Webhook templates
    WEBHOOK_TASK_EVENT = "webhook_task_event", _("Webhook: Task Event")
    WEBHOOK_USER_EVENT = "webhook_user_event", _("Webhook: User Event")
    WEBHOOK_SYSTEM_EVENT = "webhook_system_event", _("Webhook: System Event")


class NotificationCategory(models.TextChoices):
    """
    Categorizes notifications for user preference management and filtering.
    
    Categories enable users to customize their notification preferences
    at a granular level while maintaining system flexibility.
    """
    TASK_MANAGEMENT = "task_management", _("Task Management")
    COLLABORATION = "collaboration", _("Team Collaboration")
    DEADLINES = "deadlines", _("Deadlines & Reminders")
    WORKFLOW = "workflow", _("Workflow & Automation")
    SECURITY = "security", _("Security & Account")
    SYSTEM = "system", _("System Updates")
    REPORTS = "reports", _("Reports & Analytics")
    MENTIONS = "mentions", _("Mentions & Comments")


class DeliveryRetryStrategy(models.TextChoices):
    """
    Defines retry strategies for failed notification deliveries.
    
    Different strategies provide varying levels of persistence
    based on notification importance and delivery method characteristics.
    """
    NO_RETRY = "no_retry", _("No Retry")
    LINEAR_BACKOFF = "linear", _("Linear Backoff")
    EXPONENTIAL_BACKOFF = "exponential", _("Exponential Backoff")
    FIXED_INTERVAL = "fixed", _("Fixed Interval")
    CUSTOM = "custom", _("Custom Strategy")


# Constants for notification system configuration
class NotificationConstants:
    """
    System-wide constants for notification processing and delivery.
    
    These constants define operational parameters, limits,
    and configuration values used throughout the notification system.
    """
    
    # Delivery timing constants (in seconds)
    DEFAULT_RETRY_DELAY = 300  # 5 minutes
    MAX_RETRY_ATTEMPTS = 5
    CRITICAL_NOTIFICATION_TIMEOUT = 30  # 30 seconds
    NORMAL_NOTIFICATION_TIMEOUT = 300   # 5 minutes
    BATCH_PROCESSING_INTERVAL = 60      # 1 minute
    
    # Rate limiting constants
    MAX_NOTIFICATIONS_PER_USER_HOUR = 50
    MAX_EMAIL_NOTIFICATIONS_PER_USER_DAY = 20
    MAX_SMS_NOTIFICATIONS_PER_USER_DAY = 5
    
    # Template and content constants
    MAX_SUBJECT_LENGTH = 200
    MAX_BODY_LENGTH = 10000
    MAX_METADATA_SIZE = 5000  # bytes
    
    # Cleanup and archival constants
    NOTIFICATION_RETENTION_DAYS = 90
    READ_NOTIFICATION_CLEANUP_DAYS = 30
    FAILED_NOTIFICATION_CLEANUP_DAYS = 7


# Utility mappings for business logic
PRIORITY_MAPPING = {
    NotificationPriority.CRITICAL: {
        'queue_priority': 1,
        'retry_attempts': 5,
        'timeout_seconds': 30,
        'required_methods': [NotificationDeliveryMethod.EMAIL, NotificationDeliveryMethod.IN_APP]
    },
    NotificationPriority.URGENT: {
        'queue_priority': 2,
        'retry_attempts': 4,
        'timeout_seconds': 60,
        'required_methods': [NotificationDeliveryMethod.EMAIL, NotificationDeliveryMethod.IN_APP]
    },
    NotificationPriority.HIGH: {
        'queue_priority': 3,
        'retry_attempts': 3,
        'timeout_seconds': 120,
        'required_methods': [NotificationDeliveryMethod.IN_APP]
    },
    NotificationPriority.NORMAL: {
        'queue_priority': 4,
        'retry_attempts': 2,
        'timeout_seconds': 300,
        'required_methods': []
    },
    NotificationPriority.LOW: {
        'queue_priority': 5,
        'retry_attempts': 1,
        'timeout_seconds': 600,
        'required_methods': []
    }
}

TYPE_CATEGORY_MAPPING = {
    NotificationType.TASK_CREATED: NotificationCategory.TASK_MANAGEMENT,
    NotificationType.TASK_UPDATED: NotificationCategory.TASK_MANAGEMENT,
    NotificationType.TASK_ASSIGNED: NotificationCategory.COLLABORATION,
    NotificationType.TASK_COMMENT_ADDED: NotificationCategory.MENTIONS,
    NotificationType.TASK_DUE_SOON: NotificationCategory.DEADLINES,
    NotificationType.TASK_OVERDUE: NotificationCategory.DEADLINES,
    NotificationType.TASK_ESCALATED: NotificationCategory.WORKFLOW,
    NotificationType.SECURITY_ALERT: NotificationCategory.SECURITY,
    NotificationType.DAILY_SUMMARY: NotificationCategory.REPORTS,
    NotificationType.SYSTEM_MAINTENANCE: NotificationCategory.SYSTEM,
}

DEFAULT_PRIORITY_BY_TYPE = {
    NotificationType.SECURITY_ALERT: NotificationPriority.CRITICAL,
    NotificationType.SLA_BREACHED: NotificationPriority.CRITICAL,
    NotificationType.TASK_OVERDUE: NotificationPriority.URGENT,
    NotificationType.TASK_ESCALATED: NotificationPriority.URGENT,
    NotificationType.TASK_ASSIGNED: NotificationPriority.HIGH,
    NotificationType.TASK_DUE_SOON: NotificationPriority.HIGH,
    NotificationType.TASK_COMMENT_ADDED: NotificationPriority.NORMAL,
    NotificationType.DAILY_SUMMARY: NotificationPriority.LOW,
    NotificationType.SYSTEM_MAINTENANCE: NotificationPriority.NORMAL,
}
