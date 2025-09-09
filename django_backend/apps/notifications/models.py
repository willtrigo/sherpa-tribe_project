"""
Notification models for the Enterprise Task Management System.

This module defines models for handling various types of notifications
including task events, user activities, and system alerts with delivery
tracking and preference management.
"""

from typing import Optional, Dict, Any, List
from enum import Enum

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel, TimestampedModel
from apps.common.validators import validate_json_schema


User = get_user_model()


class NotificationType(models.TextChoices):
    """Enumeration of notification types for categorization."""
    
    TASK_CREATED = 'task_created', _('Task Created')
    TASK_UPDATED = 'task_updated', _('Task Updated')
    TASK_ASSIGNED = 'task_assigned', _('Task Assigned')
    TASK_COMPLETED = 'task_completed', _('Task Completed')
    TASK_OVERDUE = 'task_overdue', _('Task Overdue')
    TASK_COMMENTED = 'task_commented', _('Task Commented')
    
    USER_MENTIONED = 'user_mentioned', _('User Mentioned')
    USER_FOLLOWED = 'user_followed', _('User Followed')
    
    SYSTEM_MAINTENANCE = 'system_maintenance', _('System Maintenance')
    SYSTEM_ERROR = 'system_error', _('System Error')
    SYSTEM_UPDATE = 'system_update', _('System Update')
    
    WORKFLOW_TRIGGERED = 'workflow_triggered', _('Workflow Triggered')
    WORKFLOW_COMPLETED = 'workflow_completed', _('Workflow Completed')
    
    REPORT_GENERATED = 'report_generated', _('Report Generated')
    EXPORT_COMPLETED = 'export_completed', _('Export Completed')


class NotificationPriority(models.TextChoices):
    """Priority levels for notifications."""
    
    LOW = 'low', _('Low')
    NORMAL = 'normal', _('Normal')
    HIGH = 'high', _('High')
    CRITICAL = 'critical', _('Critical')


class DeliveryChannel(models.TextChoices):
    """Available notification delivery channels."""
    
    EMAIL = 'email', _('Email')
    WEBHOOK = 'webhook', _('Webhook')
    IN_APP = 'in_app', _('In-App')
    SMS = 'sms', _('SMS')
    PUSH = 'push', _('Push Notification')


class DeliveryStatus(models.TextChoices):
    """Status of notification delivery attempts."""
    
    PENDING = 'pending', _('Pending')
    SENT = 'sent', _('Sent')
    DELIVERED = 'delivered', _('Delivered')
    READ = 'read', _('Read')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')


class NotificationManager(models.Manager):
    """Custom manager for Notification model with query optimizations."""
    
    def get_queryset(self):
        """Optimize default queryset with select_related."""
        return (
            super()
            .get_queryset()
            .select_related(
                'recipient',
                'triggered_by',
                'content_type'
            )
        )
    
    def for_user(self, user: User):
        """Filter notifications for specific user."""
        return self.filter(recipient=user)
    
    def unread(self):
        """Filter unread notifications."""
        return self.filter(read_at__isnull=True)
    
    def by_type(self, notification_type: str):
        """Filter by notification type."""
        return self.filter(notification_type=notification_type)
    
    def by_priority(self, priority: str):
        """Filter by priority level."""
        return self.filter(priority=priority)
    
    def recent(self, days: int = 7):
        """Get recent notifications within specified days."""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff_date)


class Notification(TimestampedModel):
    """
    Core notification model for all system notifications.
    
    Supports generic foreign keys for flexible content association,
    delivery tracking, and user preferences integration.
    """
    
    # Core notification fields
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True,
        help_text=_('User who will receive this notification')
    )
    
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_notifications',
        help_text=_('User who triggered this notification')
    )
    
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        db_index=True,
        help_text=_('Type of notification for categorization')
    )
    
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        db_index=True,
        help_text=_('Priority level of the notification')
    )
    
    # Message content
    title = models.CharField(
        max_length=255,
        help_text=_('Short notification title')
    )
    
    message = models.TextField(
        help_text=_('Detailed notification message')
    )
    
    # Generic content association
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text=_('Content type of the related object')
    )
    
    object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_('ID of the related object')
    )
    
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Metadata and context
    context_data = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_json_schema({
            'type': 'object',
            'properties': {
                'action_url': {'type': 'string'},
                'action_text': {'type': 'string'},
                'metadata': {'type': 'object'}
            }
        })],
        help_text=_('Additional context data for notification rendering')
    )
    
    # Action and interaction
    action_url = models.URLField(
        blank=True,
        validators=[URLValidator()],
        help_text=_('URL for notification action button')
    )
    
    action_text = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('Text for notification action button')
    )
    
    # Status tracking
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_('Whether notification has been read')
    )
    
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when notification was read')
    )
    
    is_archived = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_('Whether notification is archived')
    )
    
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when notification was archived')
    )
    
    # Expiration
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When notification expires and should be cleaned up')
    )
    
    # Custom manager
    objects = NotificationManager()
    
    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['recipient', 'is_read', 'created_at'],
                name='notification_user_status_idx'
            ),
            models.Index(
                fields=['notification_type', 'priority'],
                name='notification_type_priority_idx'
            ),
            models.Index(
                fields=['expires_at'],
                name='notification_expires_idx',
                condition=models.Q(expires_at__isnull=False)
            )
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(expires_at__gt=models.F('created_at')),
                name='notification_expires_after_created'
            )
        ]
    
    def __str__(self) -> str:
        return f'{self.get_notification_type_display()} for {self.recipient.username}'
    
    def mark_as_read(self) -> None:
        """Mark notification as read with timestamp."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def archive(self) -> None:
        """Archive notification with timestamp."""
        if not self.is_archived:
            self.is_archived = True
            self.archived_at = timezone.now()
            self.save(update_fields=['is_archived', 'archived_at'])
    
    def is_expired(self) -> bool:
        """Check if notification has expired."""
        return (
            self.expires_at is not None and 
            timezone.now() > self.expires_at
        )
    
    def get_context_value(self, key: str, default: Any = None) -> Any:
        """Get value from context_data safely."""
        return self.context_data.get(key, default)
    
    def clean(self) -> None:
        """Custom validation for notification model."""
        super().clean()
        
        # Validate expiration date
        if self.expires_at and self.expires_at <= timezone.now():
            raise ValidationError({
                'expires_at': _('Expiration date must be in the future')
            })
        
        # Validate action fields consistency
        if self.action_url and not self.action_text:
            raise ValidationError({
                'action_text': _('Action text is required when action URL is provided')
            })


class NotificationPreferenceManager(models.Manager):
    """Custom manager for NotificationPreference model."""
    
    def for_user(self, user: User):
        """Get preferences for specific user."""
        return self.filter(user=user)
    
    def get_user_preference(
        self, 
        user: User, 
        notification_type: str, 
        channel: str
    ) -> bool:
        """
        Get user preference for specific notification type and channel.
        Returns True if enabled, False otherwise.
        """
        try:
            preference = self.get(
                user=user,
                notification_type=notification_type,
                channel=channel
            )
            return preference.is_enabled
        except self.model.DoesNotExist:
            return True  # Default to enabled
    
    def get_or_create_defaults(self, user: User) -> List['NotificationPreference']:
        """Create default preferences for a user."""
        preferences = []
        
        for notification_type, _ in NotificationType.choices:
            for channel, _ in DeliveryChannel.choices:
                preference, created = self.get_or_create(
                    user=user,
                    notification_type=notification_type,
                    channel=channel,
                    defaults={'is_enabled': self._get_default_setting(notification_type, channel)}
                )
                preferences.append(preference)
        
        return preferences
    
    @staticmethod
    def _get_default_setting(notification_type: str, channel: str) -> bool:
        """Get default setting for notification type and channel combination."""
        # Critical notifications enabled by default
        if notification_type in [
            NotificationType.TASK_OVERDUE,
            NotificationType.SYSTEM_ERROR
        ]:
            return True
        
        # In-app notifications generally enabled
        if channel == DeliveryChannel.IN_APP:
            return True
        
        # Email for important task events
        if (channel == DeliveryChannel.EMAIL and 
            notification_type in [
                NotificationType.TASK_ASSIGNED,
                NotificationType.TASK_COMPLETED
            ]):
            return True
        
        return False


class NotificationPreference(TimestampedModel):
    """
    User preferences for notification delivery by type and channel.
    
    Allows granular control over which notifications are delivered
    through which channels for each user.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences',
        help_text=_('User these preferences belong to')
    )
    
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        help_text=_('Type of notification this preference applies to')
    )
    
    channel = models.CharField(
        max_length=20,
        choices=DeliveryChannel.choices,
        help_text=_('Delivery channel this preference applies to')
    )
    
    is_enabled = models.BooleanField(
        default=True,
        help_text=_('Whether notifications of this type are enabled for this channel')
    )
    
    # Custom manager
    objects = NotificationPreferenceManager()
    
    class Meta:
        db_table = 'notification_preferences'
        unique_together = [['user', 'notification_type', 'channel']]
        indexes = [
            models.Index(
                fields=['user', 'notification_type'],
                name='notification_pref_user_type_idx'
            )
        ]
    
    def __str__(self) -> str:
        status = 'enabled' if self.is_enabled else 'disabled'
        return f'{self.user.username} - {self.get_notification_type_display()} via {self.get_channel_display()} ({status})'


class NotificationTemplateManager(models.Manager):
    """Custom manager for NotificationTemplate model."""
    
    def for_type_and_channel(self, notification_type: str, channel: str):
        """Get template for specific type and channel."""
        return self.filter(
            notification_type=notification_type,
            channel=channel
        ).first()
    
    def active_templates(self):
        """Get only active templates."""
        return self.filter(is_active=True)


class NotificationTemplate(TimestampedModel):
    """
    Templates for rendering notifications across different channels.
    
    Supports template variables and different formats for each
    delivery channel (email, webhook, etc.).
    """
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_('Unique template name for identification')
    )
    
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        db_index=True,
        help_text=_('Type of notification this template is for')
    )
    
    channel = models.CharField(
        max_length=20,
        choices=DeliveryChannel.choices,
        help_text=_('Delivery channel this template is for')
    )
    
    # Template content
    subject_template = models.CharField(
        max_length=255,
        blank=True,
        help_text=_('Template for notification subject/title')
    )
    
    body_template = models.TextField(
        help_text=_('Template for notification body/content')
    )
    
    html_template = models.TextField(
        blank=True,
        help_text=_('HTML template for rich content notifications')
    )
    
    # Template configuration
    variables = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_json_schema({
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'description': {'type': 'string'},
                    'required': {'type': 'boolean'}
                },
                'required': ['name']
            }
        })],
        help_text=_('List of available template variables with descriptions')
    )
    
    # Status and metadata
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_('Whether this template is active and should be used')
    )
    
    version = models.PositiveSmallIntegerField(
        default=1,
        help_text=_('Template version for change tracking')
    )
    
    # Custom manager
    objects = NotificationTemplateManager()
    
    class Meta:
        db_table = 'notification_templates'
        unique_together = [['notification_type', 'channel']]
        indexes = [
            models.Index(
                fields=['notification_type', 'channel', 'is_active'],
                name='notification_template_lookup_idx'
            )
        ]
    
    def __str__(self) -> str:
        return f'{self.name} ({self.get_notification_type_display()} - {self.get_channel_display()})'
    
    def render(self, context: Dict[str, Any]) -> Dict[str, str]:
        """
        Render template with provided context.
        
        Args:
            context: Dictionary of variables to substitute in template
            
        Returns:
            Dictionary with rendered subject and body
        """
        from django.template import Context, Template
        
        # Render subject
        subject = ''
        if self.subject_template:
            subject_tmpl = Template(self.subject_template)
            subject = subject_tmpl.render(Context(context))
        
        # Render body
        body_tmpl = Template(self.body_template)
        body = body_tmpl.render(Context(context))
        
        # Render HTML if available
        html = ''
        if self.html_template:
            html_tmpl = Template(self.html_template)
            html = html_tmpl.render(Context(context))
        
        return {
            'subject': subject,
            'body': body,
            'html': html
        }
    
    def validate_context(self, context: Dict[str, Any]) -> List[str]:
        """
        Validate that required template variables are provided.
        
        Args:
            context: Context dictionary to validate
            
        Returns:
            List of missing required variables
        """
        missing_variables = []
        
        for variable in self.variables:
            if variable.get('required', False):
                if variable['name'] not in context:
                    missing_variables.append(variable['name'])
        
        return missing_variables


class NotificationDeliveryManager(models.Manager):
    """Custom manager for NotificationDelivery model."""
    
    def get_queryset(self):
        """Optimize default queryset."""
        return (
            super()
            .get_queryset()
            .select_related('notification', 'notification__recipient')
        )
    
    def for_notification(self, notification: Notification):
        """Get deliveries for specific notification."""
        return self.filter(notification=notification)
    
    def by_status(self, status: str):
        """Filter by delivery status."""
        return self.filter(status=status)
    
    def failed_deliveries(self):
        """Get failed deliveries that can be retried."""
        return self.filter(
            status=DeliveryStatus.FAILED,
            retry_count__lt=models.F('max_retries')
        )
    
    def pending_deliveries(self):
        """Get pending deliveries ready to be sent."""
        return self.filter(
            status=DeliveryStatus.PENDING,
            scheduled_at__lte=timezone.now()
        )


class NotificationDelivery(TimestampedModel):
    """
    Tracking model for notification delivery attempts across channels.
    
    Provides delivery status, retry logic, and performance metrics
    for notification reliability and debugging.
    """
    
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='deliveries',
        help_text=_('Notification being delivered')
    )
    
    channel = models.CharField(
        max_length=20,
        choices=DeliveryChannel.choices,
        help_text=_('Channel used for delivery')
    )
    
    status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
        help_text=_('Current delivery status')
    )
    
    # Delivery details
    recipient_address = models.CharField(
        max_length=255,
        blank=True,
        help_text=_('Recipient address (email, webhook URL, etc.)')
    )
    
    external_id = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('External service delivery ID for tracking')
    )
    
    # Scheduling and timing
    scheduled_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text=_('When delivery was scheduled')
    )
    
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When delivery was actually sent')
    )
    
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When delivery was confirmed')
    )
    
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When notification was read (if trackable)')
    )
    
    # Retry logic
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text=_('Number of delivery attempts made')
    )
    
    max_retries = models.PositiveSmallIntegerField(
        default=3,
        help_text=_('Maximum number of retry attempts allowed')
    )
    
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When next retry attempt should be made')
    )
    
    # Error tracking
    error_message = models.TextField(
        blank=True,
        help_text=_('Last error message if delivery failed')
    )
    
    error_code = models.CharField(
        max_length=50,
        blank=True,
        help_text=_('Error code from delivery service')
    )
    
    # Performance metrics
    response_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Response data from delivery service')
    )
    
    delivery_duration = models.DurationField(
        null=True,
        blank=True,
        help_text=_('Time taken for delivery attempt')
    )
    
    # Custom manager
    objects = NotificationDeliveryManager()
    
    class Meta:
        db_table = 'notification_deliveries'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['status', 'scheduled_at'],
                name='notification_delivery_processing_idx'
            ),
            models.Index(
                fields=['notification', 'channel'],
                name='notification_delivery_lookup_idx'
            ),
            models.Index(
                fields=['next_retry_at'],
                name='notification_delivery_retry_idx',
                condition=models.Q(next_retry_at__isnull=False)
            )
        ]
    
    def __str__(self) -> str:
        return f'{self.notification.title} via {self.get_channel_display()} - {self.get_status_display()}'
    
    def mark_sent(self, external_id: Optional[str] = None) -> None:
        """Mark delivery as sent with timestamp and optional external ID."""
        self.status = DeliveryStatus.SENT
        self.sent_at = timezone.now()
        if external_id:
            self.external_id = external_id
        self.save(update_fields=['status', 'sent_at', 'external_id'])
    
    def mark_delivered(self) -> None:
        """Mark delivery as successfully delivered."""
        self.status = DeliveryStatus.DELIVERED
        self.delivered_at = timezone.now()
        self.save(update_fields=['status', 'delivered_at'])
    
    def mark_read(self) -> None:
        """Mark notification as read by recipient."""
        self.status = DeliveryStatus.READ
        self.read_at = timezone.now()
        self.save(update_fields=['status', 'read_at'])
        
        # Also mark the main notification as read
        self.notification.mark_as_read()
    
    def mark_failed(self, error_message: str, error_code: str = '') -> None:
        """Mark delivery as failed with error details."""
        self.status = DeliveryStatus.FAILED
        self.error_message = error_message
        self.error_code = error_code
        self.retry_count += 1
        
        # Schedule retry if under retry limit
        if self.retry_count < self.max_retries:
            self.schedule_retry()
        
        self.save(update_fields=[
            'status', 'error_message', 'error_code', 'retry_count', 'next_retry_at'
        ])
    
    def schedule_retry(self) -> None:
        """Schedule next retry attempt with exponential backoff."""
        if self.retry_count < self.max_retries:
            # Exponential backoff: 1min, 5min, 25min
            delay_minutes = 5 ** self.retry_count
            self.next_retry_at = timezone.now() + timezone.timedelta(minutes=delay_minutes)
    
    def can_retry(self) -> bool:
        """Check if delivery can be retried."""
        return (
            self.status == DeliveryStatus.FAILED and
            self.retry_count < self.max_retries and
            self.next_retry_at and
            timezone.now() >= self.next_retry_at
        )
    
    def calculate_delivery_metrics(self) -> Dict[str, Any]:
        """Calculate delivery performance metrics."""
        metrics = {}
        
        if self.sent_at and self.scheduled_at:
            metrics['time_to_send'] = self.sent_at - self.scheduled_at
        
        if self.delivered_at and self.sent_at:
            metrics['delivery_time'] = self.delivered_at - self.sent_at
        
        if self.read_at and self.delivered_at:
            metrics['time_to_read'] = self.read_at - self.delivered_at
        
        metrics['total_attempts'] = self.retry_count + 1
        metrics['success_rate'] = 1.0 if self.status in [
            DeliveryStatus.DELIVERED, 
            DeliveryStatus.READ
        ] else 0.0
        
        return metrics
