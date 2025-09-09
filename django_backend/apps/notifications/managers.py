"""
Notification managers for Enterprise Task Management System.

This module provides custom managers for notification-related models,
implementing sophisticated querying capabilities, bulk operations,
and business logic encapsulation following Django best practices.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, QuerySet, Union

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Count, Q, Prefetch
from django.utils import timezone

User = get_user_model()


class NotificationQuerySet(models.QuerySet):
    """Custom QuerySet for Notification model with advanced filtering capabilities."""
    
    def unread(self) -> 'NotificationQuerySet':
        """Filter notifications that haven't been read."""
        return self.filter(is_read=False)
    
    def read(self) -> 'NotificationQuerySet':
        """Filter notifications that have been read."""
        return self.filter(is_read=True)
    
    def for_user(self, user: User) -> 'NotificationQuerySet':
        """Filter notifications for a specific user."""
        return self.filter(recipient=user)
    
    def by_type(self, notification_type: str) -> 'NotificationQuerySet':
        """Filter notifications by type."""
        return self.filter(notification_type=notification_type)
    
    def by_priority(self, priority: str) -> 'NotificationQuerySet':
        """Filter notifications by priority level."""
        return self.filter(priority=priority)
    
    def recent(self, days: int = 7) -> 'NotificationQuerySet':
        """Filter notifications from the last N days."""
        since = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=since)
    
    def pending_delivery(self) -> 'NotificationQuerySet':
        """Filter notifications that are pending delivery."""
        return self.filter(
            delivery_status__in=['pending', 'retrying'],
            is_delivered=False
        )
    
    def failed_delivery(self) -> 'NotificationQuerySet':
        """Filter notifications with failed delivery."""
        return self.filter(delivery_status='failed', is_delivered=False)
    
    def deliverable(self) -> 'NotificationQuerySet':
        """Filter notifications that can be delivered (not disabled users)."""
        return self.filter(
            recipient__is_active=True,
            is_delivered=False
        ).exclude(delivery_status='failed')
    
    def with_related_data(self) -> 'NotificationQuerySet':
        """Optimize query by selecting related data."""
        return self.select_related(
            'recipient',
            'sender'
        ).prefetch_related(
            'notification_preferences'
        )
    
    def aggregate_by_type(self) -> Dict[str, int]:
        """Aggregate notification counts by type."""
        return dict(
            self.values('notification_type')
            .annotate(count=Count('id'))
            .values_list('notification_type', 'count')
        )
    
    def mark_as_read(self) -> int:
        """Mark all notifications in queryset as read."""
        return self.update(
            is_read=True,
            read_at=timezone.now()
        )
    
    def mark_as_delivered(self) -> int:
        """Mark all notifications in queryset as delivered."""
        return self.update(
            is_delivered=True,
            delivered_at=timezone.now(),
            delivery_status='delivered'
        )
    
    def delete_old(self, days: int = 90) -> tuple:
        """Delete notifications older than specified days."""
        cutoff_date = timezone.now() - timedelta(days=days)
        return self.filter(created_at__lt=cutoff_date).delete()


class NotificationManager(models.Manager):
    """
    Custom manager for Notification model.
    
    Provides high-level methods for notification creation, delivery,
    and management operations with proper error handling and optimization.
    """
    
    def get_queryset(self) -> NotificationQuerySet:
        """Return custom QuerySet with optimization."""
        return NotificationQuerySet(self.model, using=self._db)
    
    def unread(self) -> NotificationQuerySet:
        """Get all unread notifications."""
        return self.get_queryset().unread()
    
    def for_user(self, user: User) -> NotificationQuerySet:
        """Get notifications for specific user with optimization."""
        return self.get_queryset().for_user(user).with_related_data()
    
    def create_notification(
        self,
        recipient: User,
        notification_type: str,
        title: str,
        message: str,
        sender: Optional[User] = None,
        priority: str = 'medium',
        metadata: Optional[Dict] = None,
        related_object_id: Optional[int] = None,
        related_content_type_id: Optional[int] = None,
        delivery_channels: Optional[List[str]] = None
    ) -> 'Notification':
        """
        Create a new notification with comprehensive validation.
        
        Args:
            recipient: User who will receive the notification
            notification_type: Type of notification (task_assigned, due_reminder, etc.)
            title: Notification title
            message: Notification message content
            sender: User who triggered the notification (optional)
            priority: Priority level (low, medium, high, critical)
            metadata: Additional metadata as JSON
            related_object_id: ID of related object
            related_content_type_id: Content type ID of related object
            delivery_channels: List of delivery channels (email, push, etc.)
            
        Returns:
            Created Notification instance
        """
        if not recipient.is_active:
            raise ValueError("Cannot create notification for inactive user")
        
        if metadata is None:
            metadata = {}
        
        if delivery_channels is None:
            delivery_channels = ['in_app']  # Default channel
        
        return self.create(
            recipient=recipient,
            sender=sender,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            metadata=metadata,
            related_object_id=related_object_id,
            related_content_type_id=related_content_type_id,
            delivery_channels=delivery_channels,
            created_at=timezone.now()
        )
    
    def bulk_create_notifications(
        self,
        recipients: List[User],
        notification_type: str,
        title: str,
        message: str,
        **kwargs
    ) -> List['Notification']:
        """
        Create multiple notifications efficiently.
        
        Args:
            recipients: List of users to notify
            notification_type: Type of notification
            title: Notification title
            message: Notification message
            **kwargs: Additional notification parameters
            
        Returns:
            List of created Notification instances
        """
        active_recipients = [u for u in recipients if u.is_active]
        
        if not active_recipients:
            return []
        
        notifications = []
        current_time = timezone.now()
        
        for recipient in active_recipients:
            notification_data = {
                'recipient': recipient,
                'notification_type': notification_type,
                'title': title,
                'message': message,
                'created_at': current_time,
                **kwargs
            }
            notifications.append(self.model(**notification_data))
        
        return self.bulk_create(notifications, batch_size=100)
    
    def get_user_notifications(
        self,
        user: User,
        limit: int = 50,
        include_read: bool = True,
        notification_types: Optional[List[str]] = None
    ) -> QuerySet:
        """
        Get user notifications with filtering and pagination.
        
        Args:
            user: User to get notifications for
            limit: Maximum number of notifications to return
            include_read: Whether to include read notifications
            notification_types: List of notification types to filter by
            
        Returns:
            QuerySet of notifications
        """
        queryset = self.for_user(user)
        
        if not include_read:
            queryset = queryset.unread()
        
        if notification_types:
            queryset = queryset.filter(notification_type__in=notification_types)
        
        return queryset.order_by('-created_at')[:limit]
    
    def get_unread_count_by_user(self, user: User) -> int:
        """Get count of unread notifications for user."""
        return self.for_user(user).unread().count()
    
    def get_notification_stats(
        self,
        user: Optional[User] = None,
        days: int = 30
    ) -> Dict[str, Union[int, Dict]]:
        """
        Get comprehensive notification statistics.
        
        Args:
            user: Specific user for stats (optional, if None returns global stats)
            days: Number of days to include in stats
            
        Returns:
            Dictionary with notification statistics
        """
        queryset = self.get_queryset().recent(days)
        
        if user:
            queryset = queryset.for_user(user)
        
        stats = {
            'total_notifications': queryset.count(),
            'unread_notifications': queryset.unread().count(),
            'read_notifications': queryset.read().count(),
            'by_type': queryset.aggregate_by_type(),
            'by_priority': dict(
                queryset.values('priority')
                .annotate(count=Count('id'))
                .values_list('priority', 'count')
            ),
            'delivery_success_rate': self._calculate_delivery_success_rate(queryset),
        }
        
        return stats
    
    def cleanup_old_notifications(self, days: int = 90) -> Dict[str, int]:
        """
        Clean up old notifications to maintain database performance.
        
        Args:
            days: Number of days to retain notifications
            
        Returns:
            Dictionary with cleanup statistics
        """
        with transaction.atomic():
            # Delete read notifications older than specified days
            read_deleted, read_details = (
                self.get_queryset()
                .read()
                .delete_old(days)
            )
            
            # Delete delivered notifications older than extended period
            delivered_deleted, delivered_details = (
                self.get_queryset()
                .filter(is_delivered=True)
                .delete_old(days * 2)  # Keep delivered notifications longer
            )
            
            return {
                'read_notifications_deleted': read_deleted,
                'delivered_notifications_deleted': delivered_deleted,
                'total_deleted': read_deleted + delivered_deleted
            }
    
    def retry_failed_deliveries(self, max_retries: int = 3) -> int:
        """
        Retry failed notification deliveries.
        
        Args:
            max_retries: Maximum number of retry attempts
            
        Returns:
            Number of notifications queued for retry
        """
        failed_notifications = (
            self.get_queryset()
            .failed_delivery()
            .filter(retry_count__lt=max_retries)
        )
        
        return failed_notifications.update(
            delivery_status='retrying',
            retry_count=models.F('retry_count') + 1,
            updated_at=timezone.now()
        )
    
    def _calculate_delivery_success_rate(self, queryset: QuerySet) -> float:
        """Calculate delivery success rate for given queryset."""
        total_with_delivery_attempts = queryset.exclude(
            delivery_status='pending'
        ).count()
        
        if total_with_delivery_attempts == 0:
            return 100.0
        
        successful_deliveries = queryset.filter(
            delivery_status='delivered'
        ).count()
        
        return round(
            (successful_deliveries / total_with_delivery_attempts) * 100,
            2
        )


class NotificationPreferenceQuerySet(models.QuerySet):
    """Custom QuerySet for NotificationPreference model."""
    
    def for_user(self, user: User) -> 'NotificationPreferenceQuerySet':
        """Filter preferences for specific user."""
        return self.filter(user=user)
    
    def enabled(self) -> 'NotificationPreferenceQuerySet':
        """Filter enabled notification preferences."""
        return self.filter(is_enabled=True)
    
    def by_channel(self, channel: str) -> 'NotificationPreferenceQuerySet':
        """Filter preferences by delivery channel."""
        return self.filter(delivery_channel=channel)
    
    def by_notification_type(self, notification_type: str) -> 'NotificationPreferenceQuerySet':
        """Filter preferences by notification type."""
        return self.filter(notification_type=notification_type)


class NotificationPreferenceManager(models.Manager):
    """
    Custom manager for NotificationPreference model.
    
    Handles user notification preferences and delivery channel management.
    """
    
    def get_queryset(self) -> NotificationPreferenceQuerySet:
        """Return custom QuerySet."""
        return NotificationPreferenceQuerySet(self.model, using=self._db)
    
    def for_user(self, user: User) -> NotificationPreferenceQuerySet:
        """Get preferences for specific user."""
        return self.get_queryset().for_user(user)
    
    def get_user_preferences(
        self,
        user: User,
        notification_type: Optional[str] = None
    ) -> Dict[str, Dict[str, bool]]:
        """
        Get user notification preferences in structured format.
        
        Args:
            user: User to get preferences for
            notification_type: Specific notification type to filter by
            
        Returns:
            Nested dictionary of preferences by type and channel
        """
        queryset = self.for_user(user)
        
        if notification_type:
            queryset = queryset.by_notification_type(notification_type)
        
        preferences = {}
        
        for pref in queryset.select_related():
            if pref.notification_type not in preferences:
                preferences[pref.notification_type] = {}
            
            preferences[pref.notification_type][pref.delivery_channel] = pref.is_enabled
        
        return preferences
    
    def is_user_subscribed(
        self,
        user: User,
        notification_type: str,
        delivery_channel: str
    ) -> bool:
        """
        Check if user is subscribed to specific notification type and channel.
        
        Args:
            user: User to check
            notification_type: Type of notification
            delivery_channel: Delivery channel
            
        Returns:
            True if user is subscribed and preference is enabled
        """
        try:
            preference = self.get(
                user=user,
                notification_type=notification_type,
                delivery_channel=delivery_channel
            )
            return preference.is_enabled
        except self.model.DoesNotExist:
            # Default to enabled if no preference exists
            return True
    
    def create_default_preferences(self, user: User) -> List['NotificationPreference']:
        """
        Create default notification preferences for a new user.
        
        Args:
            user: User to create preferences for
            
        Returns:
            List of created NotificationPreference instances
        """
        default_preferences = [
            # Task-related notifications
            ('task_assigned', 'in_app', True),
            ('task_assigned', 'email', True),
            ('task_due_reminder', 'in_app', True),
            ('task_due_reminder', 'email', False),
            ('task_overdue', 'in_app', True),
            ('task_overdue', 'email', True),
            ('task_completed', 'in_app', True),
            ('task_completed', 'email', False),
            ('task_comment_added', 'in_app', True),
            ('task_comment_added', 'email', False),
            
            # System notifications
            ('system_maintenance', 'in_app', True),
            ('system_maintenance', 'email', True),
            ('account_security', 'in_app', True),
            ('account_security', 'email', True),
            
            # Team notifications
            ('team_invitation', 'in_app', True),
            ('team_invitation', 'email', True),
            ('team_update', 'in_app', True),
            ('team_update', 'email', False),
        ]
        
        preferences = []
        
        for notification_type, channel, is_enabled in default_preferences:
            preference = self.model(
                user=user,
                notification_type=notification_type,
                delivery_channel=channel,
                is_enabled=is_enabled
            )
            preferences.append(preference)
        
        return self.bulk_create(preferences, ignore_conflicts=True)
    
    def update_user_preference(
        self,
        user: User,
        notification_type: str,
        delivery_channel: str,
        is_enabled: bool
    ) -> 'NotificationPreference':
        """
        Update or create user notification preference.
        
        Args:
            user: User to update preference for
            notification_type: Type of notification
            delivery_channel: Delivery channel
            is_enabled: Whether preference is enabled
            
        Returns:
            Updated or created NotificationPreference instance
        """
        preference, created = self.update_or_create(
            user=user,
            notification_type=notification_type,
            delivery_channel=delivery_channel,
            defaults={
                'is_enabled': is_enabled,
                'updated_at': timezone.now()
            }
        )
        
        return preference
    
    def bulk_update_preferences(
        self,
        user: User,
        preferences_data: Dict[str, Dict[str, bool]]
    ) -> int:
        """
        Bulk update user notification preferences.
        
        Args:
            user: User to update preferences for
            preferences_data: Nested dict of preferences by type and channel
            
        Returns:
            Number of preferences updated
        """
        updated_count = 0
        
        with transaction.atomic():
            for notification_type, channels in preferences_data.items():
                for channel, is_enabled in channels.items():
                    self.update_user_preference(
                        user, notification_type, channel, is_enabled
                    )
                    updated_count += 1
        
        return updated_count
