"""
Comprehensive test suite for notification services.

This module tests all notification-related business logic including:
- Email notification delivery
- Webhook notification handling
- User preference management
- Template rendering and processing
- Delivery tracking and retry mechanisms
"""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from freezegun import freeze_time

from apps.notifications.models import (
    Notification, NotificationPreference, NotificationTemplate, 
    NotificationDelivery, WebhookEndpoint
)
from apps.notifications.services import (
    NotificationService, EmailNotificationService,
    WebhookNotificationService, NotificationPreferencesService,
    NotificationTemplateService, NotificationDeliveryService
)
from apps.notifications.choices import (
    NotificationTypes, DeliveryStatus, NotificationChannels
)
from apps.tasks.models import Task
from apps.users.models import Team


User = get_user_model()


class BaseNotificationTestCase(TestCase):
    """Base test case with common fixtures for notification tests."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data that won't change during test execution."""
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            first_name='Test',
            last_name='User'
        )
        
        cls.assignee = User.objects.create_user(
            username='assignee',
            email='assignee@example.com',
            first_name='John',
            last_name='Doe'
        )
        
        cls.team = Team.objects.create(
            name='Development Team',
            description='Main development team'
        )
        cls.team.members.add(cls.user, cls.assignee)
        
        cls.task = Task.objects.create(
            title='Test Task',
            description='Test task description',
            status='TODO',
            priority='HIGH',
            due_date=timezone.now() + timedelta(days=3),
            estimated_hours=8.0,
            created_by=cls.user
        )
        cls.task.assigned_to.add(cls.assignee)
    
    def setUp(self):
        """Set up test state for each individual test method."""
        self.notification_service = NotificationService()
        self.email_service = EmailNotificationService()
        self.webhook_service = WebhookNotificationService()
        self.preferences_service = NotificationPreferencesService()
        self.template_service = NotificationTemplateService()
        self.delivery_service = NotificationDeliveryService()


class NotificationServiceTestCase(BaseNotificationTestCase):
    """Test core notification service functionality."""
    
    def test_create_notification_success(self):
        """Test successful notification creation."""
        notification_data = {
            'user': self.user,
            'notification_type': NotificationTypes.TASK_ASSIGNED,
            'title': 'Task Assigned',
            'message': 'You have been assigned a new task.',
            'related_object_id': self.task.pk,
            'related_object_type': 'task',
            'metadata': {'task_priority': self.task.priority}
        }
        
        notification = self.notification_service.create_notification(**notification_data)
        
        self.assertIsInstance(notification, Notification)
        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.notification_type, NotificationTypes.TASK_ASSIGNED)
        self.assertEqual(notification.title, 'Task Assigned')
        self.assertEqual(notification.related_object_id, self.task.pk)
        self.assertEqual(notification.metadata['task_priority'], 'HIGH')
        self.assertFalse(notification.is_read)
        
    def test_create_notification_with_invalid_user(self):
        """Test notification creation with invalid user raises error."""
        with self.assertRaises(ValidationError):
            self.notification_service.create_notification(
                user=None,
                notification_type=NotificationTypes.TASK_ASSIGNED,
                title='Test',
                message='Test message'
            )
    
    def test_mark_notification_as_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Test Notification',
            message='Test message'
        )
        
        updated_notification = self.notification_service.mark_as_read(notification.pk)
        
        self.assertTrue(updated_notification.is_read)
        self.assertIsNotNone(updated_notification.read_at)
        
    def test_mark_nonexistent_notification_as_read(self):
        """Test marking non-existent notification as read raises error."""
        with self.assertRaises(Notification.DoesNotExist):
            self.notification_service.mark_as_read(99999)
            
    def test_get_user_notifications_with_filters(self):
        """Test retrieving user notifications with various filters."""
        # Create test notifications
        Notification.objects.bulk_create([
            Notification(
                user=self.user,
                notification_type=NotificationTypes.TASK_ASSIGNED,
                title='Task 1',
                message='Message 1'
            ),
            Notification(
                user=self.user,
                notification_type=NotificationTypes.TASK_OVERDUE,
                title='Task 2',
                message='Message 2',
                is_read=True
            ),
            Notification(
                user=self.assignee,
                notification_type=NotificationTypes.TASK_ASSIGNED,
                title='Task 3',
                message='Message 3'
            )
        ])
        
        # Test unread notifications
        unread_notifications = self.notification_service.get_user_notifications(
            user=self.user, 
            is_read=False
        )
        self.assertEqual(unread_notifications.count(), 1)
        
        # Test all user notifications
        all_notifications = self.notification_service.get_user_notifications(
            user=self.user
        )
        self.assertEqual(all_notifications.count(), 2)
        
        # Test notification type filter
        task_assigned = self.notification_service.get_user_notifications(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED
        )
        self.assertEqual(task_assigned.count(), 1)
        
    def test_bulk_mark_as_read(self):
        """Test bulk marking notifications as read."""
        notifications = Notification.objects.bulk_create([
            Notification(
                user=self.user,
                notification_type=NotificationTypes.TASK_ASSIGNED,
                title=f'Task {i}',
                message=f'Message {i}'
            ) for i in range(5)
        ])
        
        notification_ids = [n.pk for n in notifications]
        updated_count = self.notification_service.bulk_mark_as_read(
            notification_ids
        )
        
        self.assertEqual(updated_count, 5)
        
        # Verify all notifications are marked as read
        read_notifications = Notification.objects.filter(
            pk__in=notification_ids,
            is_read=True
        ).count()
        self.assertEqual(read_notifications, 5)


class EmailNotificationServiceTestCase(BaseNotificationTestCase):
    """Test email notification service functionality."""
    
    @patch('apps.notifications.services.send_mail')
    def test_send_email_notification_success(self, mock_send_mail):
        """Test successful email notification sending."""
        mock_send_mail.return_value = True
        
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Task Assigned',
            message='You have been assigned a new task.'
        )
        
        result = self.email_service.send_email_notification(
            notification=notification,
            subject='Task Assignment Notification',
            template_name='task_assigned.html',
            context={'task': self.task, 'user': self.user}
        )
        
        self.assertTrue(result)
        mock_send_mail.assert_called_once()
        
        # Verify call arguments
        call_args = mock_send_mail.call_args
        self.assertEqual(call_args[0][0], 'Task Assignment Notification')
        self.assertEqual(call_args[0][3], [self.user.email])
        
    @patch('apps.notifications.services.send_mail')
    def test_send_email_notification_failure(self, mock_send_mail):
        """Test email notification sending failure."""
        mock_send_mail.side_effect = Exception('SMTP Error')
        
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Task Assigned',
            message='Test message'
        )
        
        result = self.email_service.send_email_notification(
            notification=notification,
            subject='Test Subject',
            template_name='test_template.html'
        )
        
        self.assertFalse(result)
        
    @patch('apps.notifications.services.render_to_string')
    def test_render_email_template(self, mock_render):
        """Test email template rendering."""
        mock_render.return_value = '<html>Rendered template</html>'
        
        context = {
            'user': self.user,
            'task': self.task,
            'notification_type': 'task_assigned'
        }
        
        rendered = self.email_service.render_template(
            'task_assigned.html',
            context
        )
        
        self.assertEqual(rendered, '<html>Rendered template</html>')
        mock_render.assert_called_once_with('task_assigned.html', context)
        
    def test_validate_email_address(self):
        """Test email address validation."""
        valid_emails = [
            'test@example.com',
            'user.name@domain.co.uk',
            'firstname+lastname@example.org'
        ]
        
        invalid_emails = [
            'invalid-email',
            '@example.com',
            'test@',
            ''
        ]
        
        for email in valid_emails:
            self.assertTrue(
                self.email_service.validate_email_address(email),
                f'Valid email {email} should pass validation'
            )
            
        for email in invalid_emails:
            self.assertFalse(
                self.email_service.validate_email_address(email),
                f'Invalid email {email} should fail validation'
            )


class WebhookNotificationServiceTestCase(BaseNotificationTestCase):
    """Test webhook notification service functionality."""
    
    def setUp(self):
        """Set up webhook-specific test data."""
        super().setUp()
        self.webhook_endpoint = WebhookEndpoint.objects.create(
            user=self.user,
            name='Test Webhook',
            url='https://api.example.com/webhooks/notifications',
            secret_key='test_secret_key_123',
            is_active=True,
            notification_types=[
                NotificationTypes.TASK_ASSIGNED,
                NotificationTypes.TASK_OVERDUE
            ]
        )
        
    @patch('requests.post')
    def test_send_webhook_notification_success(self, mock_post):
        """Test successful webhook notification delivery."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_post.return_value = mock_response
        
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Task Assigned',
            message='Test webhook notification'
        )
        
        result = self.webhook_service.send_webhook_notification(
            webhook_endpoint=self.webhook_endpoint,
            notification=notification
        )
        
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        # Verify webhook payload
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], self.webhook_endpoint.url)
        self.assertIn('json', call_args[1])
        
        payload = call_args[1]['json']
        self.assertEqual(payload['notification_id'], notification.pk)
        self.assertEqual(payload['notification_type'], NotificationTypes.TASK_ASSIGNED)
        self.assertEqual(payload['user_id'], self.user.pk)
        
    @patch('requests.post')
    def test_send_webhook_notification_failure(self, mock_post):
        """Test webhook notification delivery failure."""
        mock_post.side_effect = Exception('Connection error')
        
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Task Assigned',
            message='Test webhook notification'
        )
        
        result = self.webhook_service.send_webhook_notification(
            webhook_endpoint=self.webhook_endpoint,
            notification=notification
        )
        
        self.assertFalse(result)
        
    def test_generate_webhook_signature(self):
        """Test webhook signature generation."""
        payload = {'test': 'data', 'timestamp': 1234567890}
        secret = 'test_secret_key'
        
        signature = self.webhook_service.generate_signature(
            payload=payload,
            secret=secret
        )
        
        self.assertIsInstance(signature, str)
        self.assertTrue(signature.startswith('sha256='))
        
    def test_validate_webhook_signature(self):
        """Test webhook signature validation."""
        payload = {'test': 'data'}
        secret = 'test_secret_key'
        
        signature = self.webhook_service.generate_signature(payload, secret)
        
        # Test valid signature
        is_valid = self.webhook_service.validate_signature(
            payload=payload,
            signature=signature,
            secret=secret
        )
        self.assertTrue(is_valid)
        
        # Test invalid signature
        is_invalid = self.webhook_service.validate_signature(
            payload=payload,
            signature='sha256=invalid_signature',
            secret=secret
        )
        self.assertFalse(is_invalid)


class NotificationPreferencesServiceTestCase(BaseNotificationTestCase):
    """Test notification preferences service functionality."""
    
    def test_get_user_preferences_default(self):
        """Test getting default user preferences when none exist."""
        preferences = self.preferences_service.get_user_preferences(self.user)
        
        # Should return default preferences
        self.assertIsInstance(preferences, dict)
        self.assertIn(NotificationChannels.EMAIL, preferences)
        self.assertIn(NotificationChannels.IN_APP, preferences)
        
    def test_update_user_preferences(self):
        """Test updating user notification preferences."""
        new_preferences = {
            NotificationChannels.EMAIL: {
                NotificationTypes.TASK_ASSIGNED: True,
                NotificationTypes.TASK_OVERDUE: False,
                NotificationTypes.TASK_COMPLETED: True
            },
            NotificationChannels.WEBHOOK: {
                NotificationTypes.TASK_ASSIGNED: True,
                NotificationTypes.TASK_OVERDUE: True
            }
        }
        
        updated_preferences = self.preferences_service.update_user_preferences(
            user=self.user,
            preferences=new_preferences
        )
        
        self.assertEqual(
            updated_preferences[NotificationChannels.EMAIL][NotificationTypes.TASK_ASSIGNED],
            True
        )
        self.assertEqual(
            updated_preferences[NotificationChannels.EMAIL][NotificationTypes.TASK_OVERDUE],
            False
        )
        
    def test_check_notification_enabled(self):
        """Test checking if specific notification is enabled for user."""
        # Create specific preferences
        NotificationPreference.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            channel=NotificationChannels.EMAIL,
            is_enabled=True
        )
        
        is_enabled = self.preferences_service.is_notification_enabled(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            channel=NotificationChannels.EMAIL
        )
        
        self.assertTrue(is_enabled)
        
        # Test disabled notification
        is_disabled = self.preferences_service.is_notification_enabled(
            user=self.user,
            notification_type=NotificationTypes.TASK_OVERDUE,
            channel=NotificationChannels.EMAIL
        )
        
        # Should return default value if not explicitly set
        self.assertIsInstance(is_disabled, bool)
        
    def test_bulk_update_team_preferences(self):
        """Test bulk updating preferences for team members."""
        team_preferences = {
            NotificationChannels.EMAIL: {
                NotificationTypes.TASK_ASSIGNED: True,
                NotificationTypes.TASK_OVERDUE: True
            }
        }
        
        updated_count = self.preferences_service.bulk_update_team_preferences(
            team=self.team,
            preferences=team_preferences
        )
        
        self.assertEqual(updated_count, self.team.members.count())
        
        # Verify preferences were updated for all team members
        for member in self.team.members.all():
            is_enabled = self.preferences_service.is_notification_enabled(
                user=member,
                notification_type=NotificationTypes.TASK_ASSIGNED,
                channel=NotificationChannels.EMAIL
            )
            self.assertTrue(is_enabled)


class NotificationTemplateServiceTestCase(BaseNotificationTestCase):
    """Test notification template service functionality."""
    
    def setUp(self):
        """Set up template-specific test data."""
        super().setUp()
        self.template = NotificationTemplate.objects.create(
            name='task_assigned',
            notification_type=NotificationTypes.TASK_ASSIGNED,
            channel=NotificationChannels.EMAIL,
            subject_template='Task Assigned: {{ task.title }}',
            body_template='Hello {{ user.first_name }}, you have been assigned task: {{ task.title }}',
            is_active=True
        )
        
    def test_render_template_with_context(self):
        """Test template rendering with context variables."""
        context = {
            'user': self.user,
            'task': self.task
        }
        
        rendered_subject, rendered_body = self.template_service.render_template(
            template=self.template,
            context=context
        )
        
        self.assertEqual(rendered_subject, f'Task Assigned: {self.task.title}')
        self.assertIn(self.user.first_name, rendered_body)
        self.assertIn(self.task.title, rendered_body)
        
    def test_get_template_for_notification(self):
        """Test retrieving appropriate template for notification."""
        template = self.template_service.get_template(
            notification_type=NotificationTypes.TASK_ASSIGNED,
            channel=NotificationChannels.EMAIL
        )
        
        self.assertEqual(template, self.template)
        
    def test_get_nonexistent_template(self):
        """Test retrieving non-existent template returns None."""
        template = self.template_service.get_template(
            notification_type=NotificationTypes.TASK_COMPLETED,
            channel=NotificationChannels.SMS
        )
        
        self.assertIsNone(template)
        
    def test_validate_template_syntax(self):
        """Test template syntax validation."""
        valid_template = 'Hello {{ user.name }}, task {{ task.title }} is ready.'
        invalid_template = 'Hello {{ user.name }, task {{ task.title }} is ready.'
        
        self.assertTrue(
            self.template_service.validate_template_syntax(valid_template)
        )
        
        self.assertFalse(
            self.template_service.validate_template_syntax(invalid_template)
        )
        
    def test_create_template_from_dict(self):
        """Test creating template from dictionary data."""
        template_data = {
            'name': 'task_completed',
            'notification_type': NotificationTypes.TASK_COMPLETED,
            'channel': NotificationChannels.EMAIL,
            'subject_template': 'Task Completed: {{ task.title }}',
            'body_template': 'Task {{ task.title }} has been completed by {{ user.full_name }}.',
            'variables': ['task.title', 'user.full_name'],
            'is_active': True
        }
        
        template = self.template_service.create_template(template_data)
        
        self.assertIsInstance(template, NotificationTemplate)
        self.assertEqual(template.name, 'task_completed')
        self.assertEqual(template.notification_type, NotificationTypes.TASK_COMPLETED)
        self.assertTrue(template.is_active)


class NotificationDeliveryServiceTestCase(BaseNotificationTestCase):
    """Test notification delivery service functionality."""
    
    def test_create_delivery_record(self):
        """Test creating notification delivery record."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Test Notification',
            message='Test message'
        )
        
        delivery = self.delivery_service.create_delivery_record(
            notification=notification,
            channel=NotificationChannels.EMAIL,
            recipient=self.user.email,
            status=DeliveryStatus.PENDING
        )
        
        self.assertIsInstance(delivery, NotificationDelivery)
        self.assertEqual(delivery.notification, notification)
        self.assertEqual(delivery.channel, NotificationChannels.EMAIL)
        self.assertEqual(delivery.recipient, self.user.email)
        self.assertEqual(delivery.status, DeliveryStatus.PENDING)
        
    def test_update_delivery_status(self):
        """Test updating delivery status."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Test Notification',
            message='Test message'
        )
        
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationChannels.EMAIL,
            recipient=self.user.email,
            status=DeliveryStatus.PENDING
        )
        
        updated_delivery = self.delivery_service.update_delivery_status(
            delivery_id=delivery.pk,
            status=DeliveryStatus.DELIVERED,
            delivered_at=timezone.now(),
            response_data={'message_id': 'test_123'}
        )
        
        self.assertEqual(updated_delivery.status, DeliveryStatus.DELIVERED)
        self.assertIsNotNone(updated_delivery.delivered_at)
        self.assertEqual(updated_delivery.response_data['message_id'], 'test_123')
        
    def test_retry_failed_deliveries(self):
        """Test retrying failed deliveries."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Test Notification',
            message='Test message'
        )
        
        # Create failed deliveries
        failed_deliveries = []
        for i in range(3):
            delivery = NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationChannels.EMAIL,
                recipient=f'user{i}@example.com',
                status=DeliveryStatus.FAILED,
                retry_count=1,
                last_error='SMTP connection failed'
            )
            failed_deliveries.append(delivery)
            
        with patch.object(self.delivery_service, '_attempt_delivery') as mock_attempt:
            mock_attempt.return_value = True
            
            retried_count = self.delivery_service.retry_failed_deliveries(
                max_retries=3
            )
            
            self.assertEqual(retried_count, 3)
            self.assertEqual(mock_attempt.call_count, 3)
            
    @freeze_time("2023-12-01 12:00:00")
    def test_cleanup_old_delivery_records(self):
        """Test cleanup of old delivery records."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Test Notification',
            message='Test message'
        )
        
        # Create old delivery records
        old_date = timezone.now() - timedelta(days=35)
        recent_date = timezone.now() - timedelta(days=5)
        
        with freeze_time(old_date):
            old_delivery = NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationChannels.EMAIL,
                recipient=self.user.email,
                status=DeliveryStatus.DELIVERED
            )
            
        with freeze_time(recent_date):
            recent_delivery = NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationChannels.EMAIL,
                recipient=self.user.email,
                status=DeliveryStatus.DELIVERED
            )
            
        deleted_count = self.delivery_service.cleanup_old_delivery_records(
            days_to_keep=30
        )
        
        self.assertEqual(deleted_count, 1)
        self.assertFalse(
            NotificationDelivery.objects.filter(pk=old_delivery.pk).exists()
        )
        self.assertTrue(
            NotificationDelivery.objects.filter(pk=recent_delivery.pk).exists()
        )
        
    def test_get_delivery_statistics(self):
        """Test getting delivery statistics."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Test Notification',
            message='Test message'
        )
        
        # Create deliveries with different statuses
        delivery_data = [
            (DeliveryStatus.DELIVERED, NotificationChannels.EMAIL),
            (DeliveryStatus.DELIVERED, NotificationChannels.EMAIL),
            (DeliveryStatus.FAILED, NotificationChannels.EMAIL),
            (DeliveryStatus.DELIVERED, NotificationChannels.WEBHOOK),
            (DeliveryStatus.PENDING, NotificationChannels.SMS)
        ]
        
        for status, channel in delivery_data:
            NotificationDelivery.objects.create(
                notification=notification,
                channel=channel,
                recipient='test@example.com',
                status=status
            )
            
        stats = self.delivery_service.get_delivery_statistics(
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1)
        )
        
        self.assertEqual(stats['total_deliveries'], 5)
        self.assertEqual(stats['successful_deliveries'], 3)
        self.assertEqual(stats['failed_deliveries'], 1)
        self.assertEqual(stats['pending_deliveries'], 1)
        self.assertAlmostEqual(stats['success_rate'], 0.6, places=1)
        self.assertEqual(stats['by_channel'][NotificationChannels.EMAIL]['total'], 3)
        self.assertEqual(stats['by_channel'][NotificationChannels.WEBHOOK]['total'], 1)


class NotificationIntegrationTestCase(BaseNotificationTestCase):
    """Integration tests for complete notification workflows."""
    
    @patch('apps.notifications.services.send_mail')
    @patch('requests.post')
    def test_complete_notification_workflow(self, mock_webhook, mock_email):
        """Test complete notification workflow from creation to delivery."""
        # Set up mocks
        mock_email.return_value = True
        mock_webhook_response = Mock()
        mock_webhook_response.status_code = 200
        mock_webhook.return_value = mock_webhook_response
        
        # Set up user preferences
        self.preferences_service.update_user_preferences(
            user=self.user,
            preferences={
                NotificationChannels.EMAIL: {
                    NotificationTypes.TASK_ASSIGNED: True
                },
                NotificationChannels.WEBHOOK: {
                    NotificationTypes.TASK_ASSIGNED: True
                }
            }
        )
        
        # Set up webhook endpoint
        WebhookEndpoint.objects.create(
            user=self.user,
            name='Test Webhook',
            url='https://api.example.com/webhook',
            is_active=True,
            notification_types=[NotificationTypes.TASK_ASSIGNED]
        )
        
        # Set up email template
        NotificationTemplate.objects.create(
            name='task_assigned_email',
            notification_type=NotificationTypes.TASK_ASSIGNED,
            channel=NotificationChannels.EMAIL,
            subject_template='New Task: {{ task.title }}',
            body_template='You have been assigned: {{ task.title }}',
            is_active=True
        )
        
        # Create notification
        notification = self.notification_service.create_notification(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            title='Task Assigned',
            message='You have been assigned a new task.',
            related_object_id=self.task.pk,
            related_object_type='task'
        )
        
        # Verify notification was created
        self.assertIsInstance(notification, Notification)
        
        # Verify delivery records exist (this would be handled by signals in real implementation)
        deliveries = NotificationDelivery.objects.filter(notification=notification)
        self.assertTrue(deliveries.exists())
        
        # Verify notification preferences were respected
        email_enabled = self.preferences_service.is_notification_enabled(
            user=self.user,
            notification_type=NotificationTypes.TASK_ASSIGNED,
            channel=NotificationChannels.EMAIL
        )
        self.assertTrue(email_enabled)
