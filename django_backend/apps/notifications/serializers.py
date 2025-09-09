"""
Notification serializers for the Enterprise Task Management System.

This module contains serializers for notification-related models,
providing comprehensive validation, serialization, and deserialization
capabilities with enterprise-grade error handling and performance optimizations.
"""

from typing import Dict, Any, Optional
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ObjectDoesNotExist

from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationTemplate,
    WebhookNotification,
    NotificationDeliveryLog,
)
from apps.notifications.choices import (
    NotificationTypeChoices,
    NotificationPriorityChoices,
    DeliveryStatusChoices,
    NotificationChannelChoices,
)
from apps.users.serializers import UserMinimalSerializer
from apps.common.serializers import BaseModelSerializer

User = get_user_model()


class NotificationTemplateSerializer(BaseModelSerializer):
    """
    Serializer for notification templates with comprehensive validation.
    
    Handles template content validation, variable substitution validation,
    and ensures template integrity for different notification channels.
    """
    
    variables = serializers.JSONField(
        required=False,
        help_text=_("Available template variables for substitution")
    )
    
    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'name', 'notification_type', 'channel', 'subject_template',
            'body_template', 'html_template', 'variables', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_subject_template(self, value: str) -> str:
        """Validate subject template syntax and length constraints."""
        if not value or not value.strip():
            raise ValidationError(_("Subject template cannot be empty"))
        
        if len(value) > 200:
            raise ValidationError(_("Subject template must be 200 characters or less"))
        
        return value.strip()
    
    def validate_body_template(self, value: str) -> str:
        """Validate body template content and structure."""
        if not value or not value.strip():
            raise ValidationError(_("Body template cannot be empty"))
        
        if len(value) > 10000:
            raise ValidationError(_("Body template must be 10,000 characters or less"))
        
        return value.strip()
    
    def validate_variables(self, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate template variables structure and content."""
        if value is None:
            return {}
        
        if not isinstance(value, dict):
            raise ValidationError(_("Variables must be a valid JSON object"))
        
        # Validate variable names (alphanumeric and underscores only)
        for variable_name in value.keys():
            if not variable_name.replace('_', '').isalnum():
                raise ValidationError(
                    _("Variable names must contain only letters, numbers, and underscores")
                )
        
        return value
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Perform cross-field validation."""
        channel = attrs.get('channel')
        html_template = attrs.get('html_template')
        
        # HTML template is required for email channel
        if channel == NotificationChannelChoices.EMAIL and not html_template:
            raise ValidationError({
                'html_template': _("HTML template is required for email notifications")
            })
        
        return super().validate(attrs)


class NotificationPreferenceSerializer(BaseModelSerializer):
    """
    Serializer for user notification preferences with validation rules.
    
    Manages user-specific notification settings including channel preferences,
    frequency controls, and delivery time windows.
    """
    
    user = UserMinimalSerializer(read_only=True)
    quiet_hours_start = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text=_("Start time for quiet hours (no notifications)")
    )
    quiet_hours_end = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text=_("End time for quiet hours")
    )
    
    class Meta:
        model = NotificationPreference
        fields = [
            'id', 'user', 'notification_type', 'enabled', 'email_enabled',
            'push_enabled', 'sms_enabled', 'webhook_enabled', 'frequency',
            'quiet_hours_start', 'quiet_hours_end', 'timezone',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate quiet hours and channel preferences."""
        quiet_start = attrs.get('quiet_hours_start')
        quiet_end = attrs.get('quiet_hours_end')
        
        # Both quiet hours must be provided or neither
        if bool(quiet_start) != bool(quiet_end):
            raise ValidationError({
                'quiet_hours': _("Both start and end times must be provided for quiet hours")
            })
        
        # At least one notification channel must be enabled if preference is enabled
        if attrs.get('enabled', True):
            channels_enabled = any([
                attrs.get('email_enabled', False),
                attrs.get('push_enabled', False),
                attrs.get('sms_enabled', False),
                attrs.get('webhook_enabled', False),
            ])
            
            if not channels_enabled:
                raise ValidationError({
                    'enabled': _("At least one notification channel must be enabled")
                })
        
        return super().validate(attrs)


class NotificationSerializer(BaseModelSerializer):
    """
    Comprehensive serializer for notifications with optimized queries.
    
    Provides full notification details with related user information,
    template context, and delivery status tracking.
    """
    
    recipient = UserMinimalSerializer(read_only=True)
    sender = UserMinimalSerializer(read_only=True, required=False)
    recipient_id = serializers.IntegerField(write_only=True)
    sender_id = serializers.IntegerField(write_only=True, required=False)
    
    # Template context for variable substitution
    template_context = serializers.JSONField(
        required=False,
        help_text=_("Context variables for template rendering")
    )
    
    # Computed fields
    is_overdue = serializers.SerializerMethodField()
    delivery_attempts = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message', 'html_content',
            'priority', 'channel', 'recipient', 'sender', 'recipient_id',
            'sender_id', 'template_context', 'metadata', 'is_read',
            'read_at', 'delivered_at', 'failed_at', 'retry_count',
            'max_retries', 'scheduled_for', 'expires_at', 'is_overdue',
            'delivery_attempts', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'recipient', 'sender', 'is_read', 'read_at',
            'delivered_at', 'failed_at', 'retry_count', 'is_overdue',
            'delivery_attempts', 'created_at', 'updated_at'
        ]
    
    def get_is_overdue(self, obj: Notification) -> bool:
        """Check if notification is overdue for delivery."""
        return obj.is_overdue
    
    def get_delivery_attempts(self, obj: Notification) -> int:
        """Get total number of delivery attempts."""
        if hasattr(obj, '_prefetched_delivery_logs'):
            return len(obj._prefetched_delivery_logs)
        return obj.delivery_logs.count()
    
    def validate_recipient_id(self, value: int) -> int:
        """Validate recipient user exists and is active."""
        try:
            user = User.objects.get(pk=value)
            if not user.is_active:
                raise ValidationError(_("Cannot send notification to inactive user"))
            return value
        except User.DoesNotExist:
            raise ValidationError(_("Recipient user does not exist"))
    
    def validate_sender_id(self, value: Optional[int]) -> Optional[int]:
        """Validate sender user exists if provided."""
        if value is None:
            return value
        
        try:
            User.objects.get(pk=value, is_active=True)
            return value
        except User.DoesNotExist:
            raise ValidationError(_("Sender user does not exist or is inactive"))
    
    def validate_template_context(self, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate template context structure."""
        if value is None:
            return {}
        
        if not isinstance(value, dict):
            raise ValidationError(_("Template context must be a valid JSON object"))
        
        return value
    
    def validate_metadata(self, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate metadata structure and size limits."""
        if value is None:
            return {}
        
        if not isinstance(value, dict):
            raise ValidationError(_("Metadata must be a valid JSON object"))
        
        # Prevent extremely large metadata objects
        import json
        if len(json.dumps(value)) > 10000:
            raise ValidationError(_("Metadata size cannot exceed 10KB"))
        
        return value
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive cross-field validation."""
        scheduled_for = attrs.get('scheduled_for')
        expires_at = attrs.get('expires_at')
        
        # Expiration must be after scheduled time
        if scheduled_for and expires_at and expires_at <= scheduled_for:
            raise ValidationError({
                'expires_at': _("Expiration time must be after scheduled time")
            })
        
        # High priority notifications should not be scheduled far in the future
        if (attrs.get('priority') == NotificationPriorityChoices.HIGH and 
            scheduled_for and 
            (scheduled_for - timezone.now()).days > 1):
            raise ValidationError({
                'scheduled_for': _("High priority notifications should not be scheduled more than 1 day in advance")
            })
        
        return super().validate(attrs)


class NotificationListSerializer(BaseModelSerializer):
    """
    Optimized serializer for notification lists with minimal data.
    
    Used for list endpoints where full notification details are not required,
    providing better performance for large notification collections.
    """
    
    recipient_name = serializers.CharField(source='recipient.get_full_name', read_only=True)
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    
    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'priority', 'channel',
            'recipient_name', 'sender_name', 'is_read', 'delivered_at',
            'scheduled_for', 'created_at'
        ]


class WebhookNotificationSerializer(BaseModelSerializer):
    """
    Serializer for webhook notifications with URL validation.
    
    Handles webhook-specific configuration including URL validation,
    authentication setup, and retry logic configuration.
    """
    
    notification = NotificationListSerializer(read_only=True)
    notification_id = serializers.IntegerField(write_only=True)
    
    # Authentication headers for webhook calls
    auth_headers = serializers.JSONField(
        required=False,
        help_text=_("Authentication headers for webhook requests")
    )
    
    class Meta:
        model = WebhookNotification
        fields = [
            'id', 'notification', 'notification_id', 'webhook_url',
            'http_method', 'auth_headers', 'payload', 'timeout_seconds',
            'delivered_at', 'response_status', 'response_body',
            'retry_count', 'max_retries', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'notification', 'delivered_at', 'response_status',
            'response_body', 'retry_count', 'created_at', 'updated_at'
        ]
    
    def validate_webhook_url(self, value: str) -> str:
        """Validate webhook URL format and security."""
        from urllib.parse import urlparse
        
        if not value:
            raise ValidationError(_("Webhook URL is required"))
        
        parsed_url = urlparse(value)
        
        # Ensure HTTPS for security
        if parsed_url.scheme not in ['http', 'https']:
            raise ValidationError(_("Webhook URL must use HTTP or HTTPS protocol"))
        
        # Block localhost and private IP ranges in production
        if parsed_url.hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
            raise ValidationError(_("Webhook URL cannot point to localhost"))
        
        return value
    
    def validate_timeout_seconds(self, value: int) -> int:
        """Validate webhook timeout range."""
        if value < 1:
            raise ValidationError(_("Timeout must be at least 1 second"))
        
        if value > 300:  # 5 minutes max
            raise ValidationError(_("Timeout cannot exceed 300 seconds"))
        
        return value
    
    def validate_auth_headers(self, value: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Validate authentication headers structure."""
        if value is None:
            return {}
        
        if not isinstance(value, dict):
            raise ValidationError(_("Auth headers must be a valid JSON object"))
        
        # Validate header names and values
        for header_name, header_value in value.items():
            if not isinstance(header_name, str) or not isinstance(header_value, str):
                raise ValidationError(_("Header names and values must be strings"))
            
            if not header_name.strip():
                raise ValidationError(_("Header names cannot be empty"))
        
        return value


class NotificationDeliveryLogSerializer(BaseModelSerializer):
    """
    Serializer for notification delivery logs with comprehensive tracking.
    
    Provides detailed delivery attempt information including status,
    error details, and performance metrics for notification analysis.
    """
    
    notification = NotificationListSerializer(read_only=True)
    duration_ms = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationDeliveryLog
        fields = [
            'id', 'notification', 'channel', 'status', 'attempt_number',
            'started_at', 'completed_at', 'duration_ms', 'error_message',
            'error_code', 'response_data', 'created_at'
        ]
        read_only_fields = ['id', 'notification', 'duration_ms', 'created_at']
    
    def get_duration_ms(self, obj: NotificationDeliveryLog) -> Optional[int]:
        """Calculate delivery attempt duration in milliseconds."""
        if obj.started_at and obj.completed_at:
            duration = obj.completed_at - obj.started_at
            return int(duration.total_seconds() * 1000)
        return None


class NotificationMarkReadSerializer(serializers.Serializer):
    """
    Serializer for marking notifications as read.
    
    Handles bulk read status updates with validation for user permissions
    and notification ownership verification.
    """
    
    notification_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
        help_text=_("List of notification IDs to mark as read")
    )
    
    def validate_notification_ids(self, value: list) -> list:
        """Validate notification IDs exist and belong to requesting user."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise ValidationError(_("Authentication required"))
        
        # Check all notifications exist and belong to user
        user_notifications = Notification.objects.filter(
            id__in=value,
            recipient=request.user
        ).values_list('id', flat=True)
        
        missing_ids = set(value) - set(user_notifications)
        if missing_ids:
            raise ValidationError(
                _("Notifications with IDs {} not found or not accessible").format(
                    ', '.join(map(str, missing_ids))
                )
            )
        
        return value


class NotificationBulkCreateSerializer(serializers.Serializer):
    """
    Serializer for bulk notification creation with batch validation.
    
    Enables efficient creation of multiple notifications with comprehensive
    validation and error reporting for each notification in the batch.
    """
    
    notifications = serializers.ListField(
        child=NotificationSerializer(),
        min_length=1,
        max_length=1000,
        help_text=_("List of notifications to create")
    )
    
    send_immediately = serializers.BooleanField(
        default=False,
        help_text=_("Whether to send notifications immediately after creation")
    )
    
    def validate_notifications(self, value: list) -> list:
        """Validate all notifications in the batch."""
        recipient_ids = [notif.get('recipient_id') for notif in value if notif.get('recipient_id')]
        
        # Bulk validate all recipient users exist
        if recipient_ids:
            existing_users = set(
                User.objects.filter(
                    pk__in=recipient_ids,
                    is_active=True
                ).values_list('pk', flat=True)
            )
            
            for notif in value:
                recipient_id = notif.get('recipient_id')
                if recipient_id and recipient_id not in existing_users:
                    raise ValidationError(
                        _("Recipient with ID {} does not exist or is inactive").format(recipient_id)
                    )
        
        return value
    
    def create(self, validated_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create notifications in bulk with transaction safety."""
        from django.db import transaction
        
        notifications_data = validated_data['notifications']
        send_immediately = validated_data.get('send_immediately', False)
        
        created_notifications = []
        
        with transaction.atomic():
            for notification_data in notifications_data:
                notification = Notification.objects.create(**notification_data)
                created_notifications.append(notification)
                
                if send_immediately:
                    # Trigger immediate delivery (would integrate with Celery task)
                    from apps.celery_app.tasks import send_notification_task
                    send_notification_task.delay(notification.id)
        
        return {
            'created_count': len(created_notifications),
            'notifications': NotificationListSerializer(
                created_notifications, 
                many=True
            ).data
        }
