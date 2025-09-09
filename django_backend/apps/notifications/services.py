"""
Notification services for the Task Management System.

This module provides comprehensive notification capabilities including:
- Email notifications with template rendering
- Webhook notifications with retry logic
- Notification preference management
- Delivery tracking and retry mechanisms
- Template management and variable substitution
"""

import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.template import Context, Template
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from celery import current_app as celery_app

from .models import (
    Notification, NotificationTemplate, NotificationPreference,
    WebhookEndpoint, NotificationDelivery
)
from .choices import (
    NotificationStatus, NotificationChannel, NotificationType,
    DeliveryStatus, Priority
)
from ..common.exceptions import NotificationServiceError
from ..common.utils import get_client_ip, generate_uuid

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationChannelType(Enum):
    """Notification channel types enumeration."""
    EMAIL = "email"
    WEBHOOK = "webhook"
    IN_APP = "in_app"
    SMS = "sms"  # Future implementation
    PUSH = "push"  # Future implementation


@dataclass
class NotificationContext:
    """Data class for notification context variables."""
    user: Optional[Dict[str, Any]] = None
    task: Optional[Dict[str, Any]] = None
    team: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for template rendering."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class DeliveryResult:
    """Result of a notification delivery attempt."""
    success: bool
    message: str
    status_code: Optional[int] = None
    response_data: Optional[Dict[str, Any]] = None
    delivery_time: Optional[datetime] = None
    error_details: Optional[str] = None


class NotificationTemplateService:
    """Service for managing notification templates."""
    
    @staticmethod
    def render_template(
        template_id: str,
        context: NotificationContext,
        channel: NotificationChannelType = NotificationChannelType.EMAIL
    ) -> Dict[str, str]:
        """
        Render notification template with context variables.
        
        Args:
            template_id: Template identifier
            context: Context variables for rendering
            channel: Notification channel type
            
        Returns:
            Dictionary containing rendered subject and body
            
        Raises:
            NotificationServiceError: If template not found or rendering fails
        """
        try:
            template = NotificationTemplate.objects.get(
                template_id=template_id,
                channel=channel.value,
                is_active=True
            )
        except NotificationTemplate.DoesNotExist:
            raise NotificationServiceError(f"Template '{template_id}' not found for channel '{channel.value}'")
        
        try:
            # Prepare context data
            template_context = Context(context.to_dict())
            
            # Render subject
            subject_template = Template(template.subject_template)
            rendered_subject = subject_template.render(template_context).strip()
            
            # Render body
            body_template = Template(template.body_template)
            rendered_body = body_template.render(template_context)
            
            # Render HTML body if available
            rendered_html_body = None
            if template.html_template:
                html_template = Template(template.html_template)
                rendered_html_body = html_template.render(template_context)
            
            return {
                'subject': rendered_subject,
                'body': rendered_body,
                'html_body': rendered_html_body,
                'template_id': template_id,
                'channel': channel.value
            }
            
        except Exception as e:
            logger.error(f"Template rendering failed for {template_id}: {str(e)}")
            raise NotificationServiceError(f"Template rendering failed: {str(e)}")
    
    @staticmethod
    def create_template(
        template_id: str,
        name: str,
        subject_template: str,
        body_template: str,
        channel: NotificationChannelType,
        html_template: Optional[str] = None,
        variables: Optional[List[str]] = None,
        description: Optional[str] = None
    ) -> NotificationTemplate:
        """Create a new notification template."""
        template = NotificationTemplate.objects.create(
            template_id=template_id,
            name=name,
            subject_template=subject_template,
            body_template=body_template,
            html_template=html_template,
            channel=channel.value,
            variables=variables or [],
            description=description or "",
            is_active=True
        )
        logger.info(f"Created notification template: {template_id}")
        return template


class NotificationPreferenceService:
    """Service for managing user notification preferences."""
    
    @staticmethod
    def get_user_preferences(user_id: int) -> Dict[str, Any]:
        """
        Get user notification preferences.
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary of user preferences by notification type and channel
        """
        preferences = NotificationPreference.objects.filter(
            user_id=user_id,
            is_active=True
        ).values(
            'notification_type', 'channel', 'is_enabled', 
            'delivery_window_start', 'delivery_window_end',
            'frequency_limit', 'metadata'
        )
        
        # Group preferences by notification type and channel
        grouped_preferences = {}
        for pref in preferences:
            notif_type = pref['notification_type']
            channel = pref['channel']
            
            if notif_type not in grouped_preferences:
                grouped_preferences[notif_type] = {}
            
            grouped_preferences[notif_type][channel] = {
                'enabled': pref['is_enabled'],
                'delivery_window': {
                    'start': pref['delivery_window_start'],
                    'end': pref['delivery_window_end']
                },
                'frequency_limit': pref['frequency_limit'],
                'metadata': pref['metadata']
            }
        
        return grouped_preferences
    
    @staticmethod
    def is_notification_allowed(
        user_id: int,
        notification_type: str,
        channel: NotificationChannelType
    ) -> bool:
        """
        Check if notification is allowed based on user preferences.
        
        Args:
            user_id: User ID
            notification_type: Type of notification
            channel: Notification channel
            
        Returns:
            True if notification is allowed, False otherwise
        """
        try:
            preference = NotificationPreference.objects.get(
                user_id=user_id,
                notification_type=notification_type,
                channel=channel.value,
                is_active=True
            )
            
            # Check if notification is enabled
            if not preference.is_enabled:
                return False
            
            # Check delivery window
            if preference.delivery_window_start and preference.delivery_window_end:
                current_time = timezone.now().time()
                if not (preference.delivery_window_start <= current_time <= preference.delivery_window_end):
                    logger.debug(f"Notification blocked by delivery window for user {user_id}")
                    return False
            
            # Check frequency limit
            if preference.frequency_limit and preference.frequency_limit > 0:
                recent_count = NotificationDelivery.objects.filter(
                    notification__recipient_id=user_id,
                    notification__notification_type=notification_type,
                    channel=channel.value,
                    created_at__gte=timezone.now() - timedelta(hours=24),
                    status__in=[DeliveryStatus.DELIVERED, DeliveryStatus.PENDING]
                ).count()
                
                if recent_count >= preference.frequency_limit:
                    logger.debug(f"Notification blocked by frequency limit for user {user_id}")
                    return False
            
            return True
            
        except NotificationPreference.DoesNotExist:
            # Default behavior: allow notifications if no preference is set
            return True
    
    @staticmethod
    def update_preferences(
        user_id: int,
        preferences: Dict[str, Dict[str, Any]]
    ) -> None:
        """
        Update user notification preferences.
        
        Args:
            user_id: User ID
            preferences: Dictionary of preferences to update
        """
        with transaction.atomic():
            for notification_type, channels in preferences.items():
                for channel, settings_data in channels.items():
                    NotificationPreference.objects.update_or_create(
                        user_id=user_id,
                        notification_type=notification_type,
                        channel=channel,
                        defaults={
                            'is_enabled': settings_data.get('enabled', True),
                            'delivery_window_start': settings_data.get('delivery_window', {}).get('start'),
                            'delivery_window_end': settings_data.get('delivery_window', {}).get('end'),
                            'frequency_limit': settings_data.get('frequency_limit'),
                            'metadata': settings_data.get('metadata', {}),
                            'is_active': True
                        }
                    )
        
        logger.info(f"Updated notification preferences for user {user_id}")


class EmailNotificationService:
    """Service for handling email notifications."""
    
    @staticmethod
    def send_email_notification(
        recipient_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_email: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> DeliveryResult:
        """
        Send email notification.
        
        Args:
            recipient_email: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            html_body: Email body (HTML)
            from_email: Sender email address
            attachments: List of attachments
            headers: Additional email headers
            
        Returns:
            DeliveryResult with send status
        """
        try:
            from_email = from_email or settings.DEFAULT_FROM_EMAIL
            
            if html_body:
                # Send multipart email
                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=body,
                    from_email=from_email,
                    to=[recipient_email],
                    headers=headers
                )
                msg.attach_alternative(html_body, "text/html")
                
                # Add attachments if provided
                if attachments:
                    for attachment in attachments:
                        msg.attach(
                            attachment['filename'],
                            attachment['content'],
                            attachment.get('mimetype')
                        )
                
                msg.send()
            else:
                # Send plain text email
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=from_email,
                    recipient_list=[recipient_email],
                    fail_silently=False
                )
            
            return DeliveryResult(
                success=True,
                message="Email sent successfully",
                delivery_time=timezone.now()
            )
            
        except Exception as e:
            logger.error(f"Email send failed to {recipient_email}: {str(e)}")
            return DeliveryResult(
                success=False,
                message=f"Email send failed: {str(e)}",
                error_details=str(e)
            )


class WebhookNotificationService:
    """Service for handling webhook notifications."""
    
    @staticmethod
    def send_webhook_notification(
        webhook_url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        secret: Optional[str] = None,
        timeout: int = 30,
        verify_ssl: bool = True
    ) -> DeliveryResult:
        """
        Send webhook notification with retry logic.
        
        Args:
            webhook_url: Webhook endpoint URL
            payload: JSON payload to send
            headers: Additional HTTP headers
            secret: Secret for signature verification
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            
        Returns:
            DeliveryResult with delivery status
        """
        try:
            # Prepare headers
            request_headers = {
                'Content-Type': 'application/json',
                'User-Agent': f'TaskManagementSystem-Webhook/1.0',
                'X-Timestamp': str(int(timezone.now().timestamp())),
            }
            
            if headers:
                request_headers.update(headers)
            
            # Add signature if secret is provided
            if secret:
                payload_json = json.dumps(payload, separators=(',', ':'))
                signature = hashlib.sha256(
                    f"{secret}{payload_json}".encode('utf-8')
                ).hexdigest()
                request_headers['X-Signature-SHA256'] = f"sha256={signature}"
            
            # Send webhook
            response = requests.post(
                webhook_url,
                json=payload,
                headers=request_headers,
                timeout=timeout,
                verify=verify_ssl
            )
            
            # Check response status
            if response.status_code in [200, 201, 202, 204]:
                return DeliveryResult(
                    success=True,
                    message="Webhook delivered successfully",
                    status_code=response.status_code,
                    response_data={
                        'headers': dict(response.headers),
                        'body': response.text[:1000]  # Limit response body size
                    },
                    delivery_time=timezone.now()
                )
            else:
                return DeliveryResult(
                    success=False,
                    message=f"Webhook failed with status {response.status_code}",
                    status_code=response.status_code,
                    error_details=response.text[:1000]
                )
                
        except requests.exceptions.Timeout:
            return DeliveryResult(
                success=False,
                message="Webhook request timed out",
                error_details="Request timeout"
            )
        except requests.exceptions.ConnectionError as e:
            return DeliveryResult(
                success=False,
                message="Webhook connection failed",
                error_details=str(e)
            )
        except Exception as e:
            logger.error(f"Webhook send failed to {webhook_url}: {str(e)}")
            return DeliveryResult(
                success=False,
                message=f"Webhook send failed: {str(e)}",
                error_details=str(e)
            )


class NotificationDeliveryService:
    """Service for managing notification delivery and tracking."""
    
    @staticmethod
    def create_delivery_record(
        notification: Notification,
        channel: NotificationChannelType,
        delivery_result: DeliveryResult,
        recipient_identifier: str
    ) -> NotificationDelivery:
        """Create delivery tracking record."""
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=channel.value,
            recipient_identifier=recipient_identifier,
            status=DeliveryStatus.DELIVERED if delivery_result.success else DeliveryStatus.FAILED,
            delivered_at=delivery_result.delivery_time,
            status_code=delivery_result.status_code,
            response_data=delivery_result.response_data or {},
            error_message=delivery_result.error_details,
            delivery_metadata={
                'success': delivery_result.success,
                'message': delivery_result.message
            }
        )
        
        logger.info(f"Created delivery record {delivery.id} for notification {notification.id}")
        return delivery
    
    @staticmethod
    def schedule_retry(
        delivery: NotificationDelivery,
        delay_seconds: int = 300
    ) -> None:
        """Schedule notification retry."""
        from ..celery_app.tasks import retry_notification_delivery
        
        # Increment retry count
        delivery.retry_count += 1
        delivery.status = DeliveryStatus.PENDING_RETRY
        delivery.next_retry_at = timezone.now() + timedelta(seconds=delay_seconds)
        delivery.save(update_fields=['retry_count', 'status', 'next_retry_at'])
        
        # Schedule retry task
        retry_notification_delivery.apply_async(
            args=[delivery.id],
            countdown=delay_seconds
        )
        
        logger.info(f"Scheduled retry for delivery {delivery.id} in {delay_seconds} seconds")
    
    @staticmethod
    def get_delivery_statistics(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        notification_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get notification delivery statistics."""
        queryset = NotificationDelivery.objects.all()
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        if notification_type:
            queryset = queryset.filter(notification__notification_type=notification_type)
        
        # Calculate statistics
        total_deliveries = queryset.count()
        successful_deliveries = queryset.filter(status=DeliveryStatus.DELIVERED).count()
        failed_deliveries = queryset.filter(status=DeliveryStatus.FAILED).count()
        pending_deliveries = queryset.filter(status=DeliveryStatus.PENDING).count()
        
        # Calculate success rate
        success_rate = (successful_deliveries / total_deliveries * 100) if total_deliveries > 0 else 0
        
        # Group by channel
        channel_stats = {}
        for delivery in queryset.values('channel').annotate(
            total=models.Count('id'),
            successful=models.Count('id', filter=models.Q(status=DeliveryStatus.DELIVERED)),
            failed=models.Count('id', filter=models.Q(status=DeliveryStatus.FAILED))
        ):
            channel_stats[delivery['channel']] = {
                'total': delivery['total'],
                'successful': delivery['successful'],
                'failed': delivery['failed'],
                'success_rate': (delivery['successful'] / delivery['total'] * 100) if delivery['total'] > 0 else 0
            }
        
        return {
            'total_deliveries': total_deliveries,
            'successful_deliveries': successful_deliveries,
            'failed_deliveries': failed_deliveries,
            'pending_deliveries': pending_deliveries,
            'success_rate': round(success_rate, 2),
            'channel_statistics': channel_stats
        }


class NotificationService:
    """Main notification service orchestrating all notification operations."""
    
    def __init__(self):
        self.template_service = NotificationTemplateService()
        self.preference_service = NotificationPreferenceService()
        self.email_service = EmailNotificationService()
        self.webhook_service = WebhookNotificationService()
        self.delivery_service = NotificationDeliveryService()
    
    def send_notification(
        self,
        recipient_id: int,
        notification_type: str,
        template_id: str,
        context: NotificationContext,
        channels: Optional[List[NotificationChannelType]] = None,
        priority: Priority = Priority.NORMAL,
        scheduled_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send notification through specified channels.
        
        Args:
            recipient_id: Recipient user ID
            notification_type: Type of notification
            template_id: Template identifier
            context: Context variables for template rendering
            channels: List of channels to send through
            priority: Notification priority
            scheduled_at: Schedule notification for later delivery
            metadata: Additional metadata
            
        Returns:
            Dictionary with delivery results for each channel
        """
        # Default channels if not specified
        if channels is None:
            channels = [NotificationChannelType.EMAIL, NotificationChannelType.IN_APP]
        
        # Get recipient user
        try:
            recipient = User.objects.get(id=recipient_id)
        except User.DoesNotExist:
            raise NotificationServiceError(f"Recipient user {recipient_id} not found")
        
        # Create notification record
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=template_id,
            priority=priority,
            status=NotificationStatus.PENDING,
            scheduled_at=scheduled_at or timezone.now(),
            metadata=metadata or {}
        )
        
        delivery_results = {}
        
        # Process each channel
        for channel in channels:
            try:
                # Check user preferences
                if not self.preference_service.is_notification_allowed(
                    recipient_id, notification_type, channel
                ):
                    delivery_results[channel.value] = {
                        'success': False,
                        'message': 'Blocked by user preferences',
                        'skipped': True
                    }
                    continue
                
                # Render template
                rendered_template = self.template_service.render_template(
                    template_id, context, channel
                )
                
                # Send through appropriate channel
                if channel == NotificationChannelType.EMAIL:
                    result = self._send_email_channel(
                        recipient, rendered_template, notification
                    )
                elif channel == NotificationChannelType.WEBHOOK:
                    result = self._send_webhook_channel(
                        recipient, rendered_template, context, notification
                    )
                elif channel == NotificationChannelType.IN_APP:
                    result = self._send_in_app_channel(
                        recipient, rendered_template, notification
                    )
                else:
                    result = DeliveryResult(
                        success=False,
                        message=f"Channel {channel.value} not implemented"
                    )
                
                # Create delivery record
                self.delivery_service.create_delivery_record(
                    notification, channel, result, 
                    recipient.email if channel == NotificationChannelType.EMAIL else str(recipient_id)
                )
                
                delivery_results[channel.value] = {
                    'success': result.success,
                    'message': result.message,
                    'status_code': result.status_code,
                    'delivery_time': result.delivery_time
                }
                
                # Schedule retry if failed and retries are enabled
                if not result.success and getattr(settings, 'NOTIFICATION_RETRY_ENABLED', True):
                    delivery = NotificationDelivery.objects.filter(
                        notification=notification,
                        channel=channel.value
                    ).latest('created_at')
                    
                    max_retries = getattr(settings, 'NOTIFICATION_MAX_RETRIES', 3)
                    if delivery.retry_count < max_retries:
                        self.delivery_service.schedule_retry(delivery)
                
            except Exception as e:
                logger.error(f"Failed to send notification via {channel.value}: {str(e)}")
                delivery_results[channel.value] = {
                    'success': False,
                    'message': f"Channel error: {str(e)}",
                    'error_details': str(e)
                }
        
        # Update notification status
        successful_deliveries = sum(1 for result in delivery_results.values() if result.get('success', False))
        if successful_deliveries > 0:
            notification.status = NotificationStatus.SENT
        else:
            notification.status = NotificationStatus.FAILED
        
        notification.sent_at = timezone.now()
        notification.save(update_fields=['status', 'sent_at'])
        
        logger.info(f"Notification {notification.id} processed for user {recipient_id}")
        
        return {
            'notification_id': notification.id,
            'delivery_results': delivery_results,
            'successful_channels': successful_deliveries,
            'total_channels': len(channels)
        }
    
    def _send_email_channel(
        self,
        recipient: User,
        rendered_template: Dict[str, str],
        notification: Notification
    ) -> DeliveryResult:
        """Send notification via email channel."""
        return self.email_service.send_email_notification(
            recipient_email=recipient.email,
            subject=rendered_template['subject'],
            body=rendered_template['body'],
            html_body=rendered_template.get('html_body'),
            headers={
                'X-Notification-ID': str(notification.id),
                'X-Notification-Type': notification.notification_type
            }
        )
    
    def _send_webhook_channel(
        self,
        recipient: User,
        rendered_template: Dict[str, str],
        context: NotificationContext,
        notification: Notification
    ) -> DeliveryResult:
        """Send notification via webhook channel."""
        # Get user's webhook endpoints
        webhook_endpoints = WebhookEndpoint.objects.filter(
            user=recipient,
            is_active=True,
            notification_types__contains=[notification.notification_type]
        )
        
        if not webhook_endpoints.exists():
            return DeliveryResult(
                success=False,
                message="No webhook endpoints configured"
            )
        
        # Send to first active webhook (can be enhanced to send to all)
        webhook = webhook_endpoints.first()
        
        payload = {
            'notification_id': str(notification.id),
            'notification_type': notification.notification_type,
            'recipient_id': recipient.id,
            'subject': rendered_template['subject'],
            'body': rendered_template['body'],
            'timestamp': notification.created_at.isoformat(),
            'context': context.to_dict()
        }
        
        return self.webhook_service.send_webhook_notification(
            webhook_url=webhook.url,
            payload=payload,
            headers=webhook.headers or {},
            secret=webhook.secret,
            timeout=webhook.timeout_seconds
        )
    
    def _send_in_app_channel(
        self,
        recipient: User,
        rendered_template: Dict[str, str],
        notification: Notification
    ) -> DeliveryResult:
        """Send notification via in-app channel."""
        # Update notification with rendered content for in-app display
        notification.title = rendered_template['subject']
        notification.message = rendered_template['body']
        notification.status = NotificationStatus.SENT
        notification.save(update_fields=['title', 'message', 'status'])
        
        return DeliveryResult(
            success=True,
            message="In-app notification created",
            delivery_time=timezone.now()
        )
    
    def get_user_notifications(
        self,
        user_id: int,
        status: Optional[NotificationStatus] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get paginated user notifications."""
        queryset = Notification.objects.filter(recipient_id=user_id)
        
        if status:
            queryset = queryset.filter(status=status)
        
        total_count = queryset.count()
        unread_count = queryset.filter(read_at__isnull=True).count()
        
        notifications = queryset.order_by('-created_at')[offset:offset + limit]
        
        return {
            'notifications': [
                {
                    'id': notif.id,
                    'type': notif.notification_type,
                    'title': notif.title,
                    'message': notif.message,
                    'priority': notif.priority,
                    'status': notif.status,
                    'created_at': notif.created_at,
                    'read_at': notif.read_at,
                    'metadata': notif.metadata
                }
                for notif in notifications
            ],
            'total_count': total_count,
            'unread_count': unread_count,
            'has_more': offset + limit < total_count
        }
    
    def mark_notifications_as_read(
        self,
        user_id: int,
        notification_ids: Optional[List[int]] = None
    ) -> int:
        """Mark notifications as read."""
        queryset = Notification.objects.filter(
            recipient_id=user_id,
            read_at__isnull=True
        )
        
        if notification_ids:
            queryset = queryset.filter(id__in=notification_ids)
        
        updated_count = queryset.update(read_at=timezone.now())
        logger.info(f"Marked {updated_count} notifications as read for user {user_id}")
        
        return updated_count


# Service instances for easy import
notification_service = NotificationService()
template_service = NotificationTemplateService()
preference_service = NotificationPreferenceService()
email_service = EmailNotificationService()
webhook_service = WebhookNotificationService()
delivery_service = NotificationDeliveryService()
