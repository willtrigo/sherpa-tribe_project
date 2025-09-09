"""
Notification views for the Enterprise Task Management System.

This module provides RESTful API endpoints for managing notifications,
including user preferences, notification history, and delivery tracking.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import QuerySet, Q, Prefetch
from django.db import transaction
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterFilter

from .models import Notification, NotificationPreference, NotificationTemplate
from .serializers import (
    NotificationSerializer,
    NotificationPreferenceSerializer,
    NotificationTemplateSerializer,
    NotificationCreateSerializer,
    NotificationBulkCreateSerializer,
    NotificationStatsSerializer
)
from .services import NotificationService, NotificationDeliveryService
from .filters import NotificationFilter
from ..common.permissions import IsOwnerOrAdmin, CanManageNotifications
from ..common.pagination import StandardResultsSetPagination
from ..common.mixins import AuditLogMixin, CacheControlMixin
from ..common.exceptions import BusinessLogicError, ValidationError as CustomValidationError


class NotificationViewSet(AuditLogMixin, CacheControlMixin, ModelViewSet):
    """
    ViewSet for managing notifications with comprehensive CRUD operations,
    filtering, search capabilities, and bulk operations.
    """
    
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterFilter, SearchFilter, OrderingFilter]
    filterset_class = NotificationFilter
    search_fields = ['title', 'message', 'metadata__tags']
    ordering_fields = ['created_at', 'priority', 'delivery_status', 'read_at']
    ordering = ['-created_at']
    
    def get_queryset(self) -> QuerySet[Notification]:
        """
        Return notifications for the current user with optimized queries.
        Admins can access all notifications with proper filtering.
        """
        base_queryset = Notification.objects.select_related(
            'sender', 'notification_type', 'template'
        ).prefetch_related(
            Prefetch(
                'recipients',
                queryset=self.request.user.__class__.objects.select_related('profile')
            )
        )
        
        if self.request.user.is_staff and self.request.query_params.get('admin_view'):
            return base_queryset.filter(is_deleted=False)
        
        return base_queryset.filter(
            recipients=self.request.user,
            is_deleted=False
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        serializer_mapping = {
            'create': NotificationCreateSerializer,
            'bulk_create': NotificationBulkCreateSerializer,
            'list': NotificationSerializer,
            'retrieve': NotificationSerializer,
            'update': NotificationSerializer,
            'partial_update': NotificationSerializer,
        }
        return serializer_mapping.get(self.action, self.serializer_class)
    
    def get_permissions(self):
        """Apply specific permissions based on action."""
        if self.action in ['create', 'bulk_create', 'destroy']:
            permission_classes = [IsAuthenticated, CanManageNotifications]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]
    
    @transaction.atomic
    def create(self, request: Request, *args, **kwargs) -> Response:
        """
        Create a new notification with validation and automatic delivery scheduling.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            notification = serializer.save(sender=request.user)
            
            # Schedule delivery if auto_send is enabled
            if serializer.validated_data.get('auto_send', True):
                NotificationDeliveryService.schedule_delivery(notification)
            
            self.log_audit_event('notification_created', notification)
            
            response_serializer = NotificationSerializer(notification)
            return Response(
                response_serializer.data,
                status=status.HTTP_201_CREATED
            )
            
        except ValidationError as e:
            raise CustomValidationError(str(e))
        except Exception as e:
            raise BusinessLogicError(f"Failed to create notification: {str(e)}")
    
    @action(detail=False, methods=['post'], url_path='bulk-create')
    @transaction.atomic
    def bulk_create(self, request: Request) -> Response:
        """
        Create multiple notifications efficiently with batch processing.
        """
        serializer = NotificationBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            notifications = NotificationService.create_bulk_notifications(
                data=serializer.validated_data,
                sender=request.user
            )
            
            # Schedule bulk delivery
            for notification in notifications:
                if serializer.validated_data.get('auto_send', True):
                    NotificationDeliveryService.schedule_delivery(notification)
            
            self.log_audit_event('bulk_notifications_created', {
                'count': len(notifications),
                'notification_ids': [n.id for n in notifications]
            })
            
            response_serializer = NotificationSerializer(notifications, many=True)
            return Response({
                'notifications': response_serializer.data,
                'count': len(notifications),
                'message': f'Successfully created {len(notifications)} notifications'
            }, status=status.HTTP_201_CREATED)
            
        except ValidationError as e:
            raise CustomValidationError(str(e))
        except Exception as e:
            raise BusinessLogicError(f"Failed to create bulk notifications: {str(e)}")
    
    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def mark_as_read(self, request: Request, pk: str = None) -> Response:
        """Mark a specific notification as read for the current user."""
        notification = self.get_object()
        
        if request.user not in notification.recipients.all():
            raise Http404("Notification not found")
        
        try:
            NotificationService.mark_as_read(notification, request.user)
            self.log_audit_event('notification_read', notification)
            
            serializer = self.get_serializer(notification)
            return Response({
                'notification': serializer.data,
                'message': 'Notification marked as read'
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to mark notification as read: {str(e)}")
    
    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def mark_as_unread(self, request: Request, pk: str = None) -> Response:
        """Mark a specific notification as unread for the current user."""
        notification = self.get_object()
        
        if request.user not in notification.recipients.all():
            raise Http404("Notification not found")
        
        try:
            NotificationService.mark_as_unread(notification, request.user)
            self.log_audit_event('notification_unread', notification)
            
            serializer = self.get_serializer(notification)
            return Response({
                'notification': serializer.data,
                'message': 'Notification marked as unread'
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to mark notification as unread: {str(e)}")
    
    @action(detail=False, methods=['patch'])
    @transaction.atomic
    def mark_all_as_read(self, request: Request) -> Response:
        """Mark all notifications as read for the current user."""
        try:
            updated_count = NotificationService.mark_all_as_read(request.user)
            self.log_audit_event('all_notifications_read', {'count': updated_count})
            
            return Response({
                'count': updated_count,
                'message': f'Marked {updated_count} notifications as read'
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to mark all notifications as read: {str(e)}")
    
    @action(detail=True, methods=['delete'])
    @transaction.atomic
    def soft_delete(self, request: Request, pk: str = None) -> Response:
        """Soft delete a notification for the current user."""
        notification = self.get_object()
        
        try:
            NotificationService.soft_delete_for_user(notification, request.user)
            self.log_audit_event('notification_soft_deleted', notification)
            
            return Response({
                'message': 'Notification deleted successfully'
            }, status=status.HTTP_204_NO_CONTENT)
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to delete notification: {str(e)}")
    
    @action(detail=False, methods=['get'])
    def stats(self, request: Request) -> Response:
        """Get notification statistics for the current user."""
        try:
            stats = NotificationService.get_user_stats(request.user)
            serializer = NotificationStatsSerializer(stats)
            
            return Response(serializer.data)
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to retrieve notification stats: {str(e)}")
    
    @action(detail=False, methods=['get'])
    def unread_count(self, request: Request) -> Response:
        """Get the count of unread notifications for the current user."""
        try:
            count = NotificationService.get_unread_count(request.user)
            
            return Response({
                'unread_count': count,
                'timestamp': timezone.now()
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to retrieve unread count: {str(e)}")


class NotificationPreferenceViewSet(AuditLogMixin, ModelViewSet):
    """
    ViewSet for managing user notification preferences with comprehensive
    settings for different notification types and delivery channels.
    """
    
    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    
    def get_queryset(self) -> QuerySet[NotificationPreference]:
        """Return notification preferences for the current user."""
        return NotificationPreference.objects.filter(
            user=self.request.user
        ).select_related('user', 'notification_type')
    
    @transaction.atomic
    def create(self, request: Request, *args, **kwargs) -> Response:
        """Create notification preference with validation."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            preference = serializer.save(user=request.user)
            self.log_audit_event('preference_created', preference)
            
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to create preference: {str(e)}")
    
    @action(detail=False, methods=['patch'])
    @transaction.atomic
    def bulk_update(self, request: Request) -> Response:
        """Update multiple notification preferences in a single request."""
        preferences_data = request.data.get('preferences', [])
        
        if not preferences_data:
            raise CustomValidationError("No preferences data provided")
        
        try:
            updated_preferences = []
            
            for pref_data in preferences_data:
                pref_id = pref_data.get('id')
                if not pref_id:
                    continue
                
                preference = get_object_or_404(
                    self.get_queryset(),
                    id=pref_id
                )
                
                serializer = self.get_serializer(
                    preference,
                    data=pref_data,
                    partial=True
                )
                serializer.is_valid(raise_exception=True)
                updated_preference = serializer.save()
                updated_preferences.append(updated_preference)
            
            self.log_audit_event('preferences_bulk_updated', {
                'count': len(updated_preferences),
                'preference_ids': [p.id for p in updated_preferences]
            })
            
            response_serializer = self.get_serializer(updated_preferences, many=True)
            return Response({
                'preferences': response_serializer.data,
                'count': len(updated_preferences),
                'message': f'Successfully updated {len(updated_preferences)} preferences'
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to bulk update preferences: {str(e)}")
    
    @action(detail=False, methods=['post'])
    @transaction.atomic
    def reset_to_defaults(self, request: Request) -> Response:
        """Reset all notification preferences to system defaults."""
        try:
            reset_count = NotificationService.reset_user_preferences_to_defaults(
                request.user
            )
            
            self.log_audit_event('preferences_reset_to_defaults', {
                'reset_count': reset_count
            })
            
            return Response({
                'message': f'Reset {reset_count} preferences to defaults',
                'count': reset_count
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to reset preferences: {str(e)}")


class NotificationTemplateViewSet(CacheControlMixin, ModelViewSet):
    """
    ViewSet for managing notification templates with version control,
    variable substitution testing, and preview capabilities.
    """
    
    serializer_class = NotificationTemplateSerializer
    permission_classes = [IsAuthenticated, CanManageNotifications]
    pagination_class = StandardResultsSetPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'description', 'subject_template', 'body_template']
    ordering_fields = ['created_at', 'updated_at', 'name', 'notification_type']
    ordering = ['-updated_at']
    
    def get_queryset(self) -> QuerySet[NotificationTemplate]:
        """Return active notification templates with related data."""
        return NotificationTemplate.objects.filter(
            is_active=True
        ).select_related('notification_type', 'created_by')
    
    @action(detail=True, methods=['post'])
    def preview(self, request: Request, pk: str = None) -> Response:
        """
        Preview a notification template with provided context variables.
        """
        template = self.get_object()
        context_data = request.data.get('context', {})
        
        try:
            preview_result = NotificationService.preview_template(
                template,
                context_data
            )
            
            return Response({
                'preview': preview_result,
                'template_id': template.id,
                'context_used': context_data
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to generate template preview: {str(e)}")
    
    @action(detail=True, methods=['post'])
    def test_send(self, request: Request, pk: str = None) -> Response:
        """
        Send a test notification using the template to specified recipients.
        """
        template = self.get_object()
        test_data = request.data
        
        required_fields = ['recipients', 'context']
        for field in required_fields:
            if field not in test_data:
                raise CustomValidationError(f"Missing required field: {field}")
        
        try:
            test_notification = NotificationService.send_test_notification(
                template=template,
                recipients=test_data['recipients'],
                context=test_data['context'],
                sender=request.user
            )
            
            serializer = NotificationSerializer(test_notification)
            return Response({
                'test_notification': serializer.data,
                'message': 'Test notification sent successfully'
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to send test notification: {str(e)}")


class NotificationDeliveryAPIView(APIView):
    """
    API view for managing notification delivery operations,
    including retry mechanisms and delivery status tracking.
    """
    
    permission_classes = [IsAuthenticated, CanManageNotifications]
    
    def post(self, request: Request) -> Response:
        """
        Trigger manual delivery for specific notifications.
        """
        notification_ids = request.data.get('notification_ids', [])
        delivery_channels = request.data.get('channels', ['email', 'push', 'in_app'])
        
        if not notification_ids:
            raise CustomValidationError("No notification IDs provided")
        
        try:
            delivery_results = NotificationDeliveryService.deliver_notifications(
                notification_ids=notification_ids,
                channels=delivery_channels,
                force_delivery=request.data.get('force_delivery', False)
            )
            
            return Response({
                'delivery_results': delivery_results,
                'total_processed': len(notification_ids),
                'successful_deliveries': sum(
                    1 for result in delivery_results
                    if result.get('status') == 'success'
                )
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to deliver notifications: {str(e)}")
    
    def patch(self, request: Request) -> Response:
        """
        Retry failed notification deliveries.
        """
        retry_parameters = {
            'max_retry_hours': request.data.get('max_retry_hours', 24),
            'retry_channels': request.data.get('channels', ['email']),
            'notification_types': request.data.get('notification_types', []),
        }
        
        try:
            retry_results = NotificationDeliveryService.retry_failed_deliveries(
                **retry_parameters
            )
            
            return Response({
                'retry_results': retry_results,
                'retried_count': retry_results.get('retried_count', 0),
                'success_count': retry_results.get('success_count', 0),
                'failed_count': retry_results.get('failed_count', 0)
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to retry deliveries: {str(e)}")


class NotificationAnalyticsAPIView(APIView):
    """
    API view for notification analytics and reporting with comprehensive
    metrics for delivery rates, engagement, and performance monitoring.
    """
    
    permission_classes = [IsAuthenticated, CanManageNotifications]
    
    def get(self, request: Request) -> Response:
        """
        Get comprehensive notification analytics and metrics.
        """
        try:
            # Parse query parameters for date range and filters
            date_from = request.query_params.get('date_from')
            date_to = request.query_params.get('date_to')
            notification_types = request.query_params.getlist('notification_types')
            user_segments = request.query_params.getlist('user_segments')
            
            analytics_data = NotificationService.get_analytics_data(
                date_from=date_from,
                date_to=date_to,
                notification_types=notification_types,
                user_segments=user_segments,
                requesting_user=request.user
            )
            
            return Response({
                'analytics': analytics_data,
                'generated_at': timezone.now(),
                'filters_applied': {
                    'date_from': date_from,
                    'date_to': date_to,
                    'notification_types': notification_types,
                    'user_segments': user_segments
                }
            })
            
        except Exception as e:
            raise BusinessLogicError(f"Failed to generate analytics: {str(e)}")
