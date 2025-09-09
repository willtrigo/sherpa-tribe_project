"""
Notification URL patterns for the Task Management System.

This module defines URL routing for notification-related endpoints including
notification preferences, delivery status tracking, and webhook management.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

# Initialize DRF router for ViewSet-based endpoints
router = DefaultRouter(trailing_slash=False)
router.register(
    r'notifications',
    views.NotificationViewSet,
    basename='notification'
)
router.register(
    r'preferences',
    views.NotificationPreferenceViewSet,
    basename='notification-preference'
)
router.register(
    r'templates',
    views.NotificationTemplateViewSet,
    basename='notification-template'
)

app_name = 'notifications'

urlpatterns = [
    # DRF ViewSet routes
    path('api/v1/', include(router.urls)),
    
    # Custom notification endpoints
    path(
        'api/v1/notifications/<uuid:notification_id>/mark-read/',
        views.MarkNotificationAsReadAPIView.as_view(),
        name='mark-notification-read'
    ),
    path(
        'api/v1/notifications/<uuid:notification_id>/mark-unread/',
        views.MarkNotificationAsUnreadAPIView.as_view(),
        name='mark-notification-unread'
    ),
    path(
        'api/v1/notifications/mark-all-read/',
        views.MarkAllNotificationsAsReadAPIView.as_view(),
        name='mark-all-notifications-read'
    ),
    
    # Bulk operations
    path(
        'api/v1/notifications/bulk-actions/',
        views.BulkNotificationActionsAPIView.as_view(),
        name='bulk-notification-actions'
    ),
    
    # User-specific notification endpoints
    path(
        'api/v1/users/<uuid:user_id>/notifications/',
        views.UserNotificationListAPIView.as_view(),
        name='user-notifications'
    ),
    path(
        'api/v1/users/<uuid:user_id>/notifications/unread-count/',
        views.UserUnreadNotificationCountAPIView.as_view(),
        name='user-unread-count'
    ),
    path(
        'api/v1/users/<uuid:user_id>/preferences/',
        views.UserNotificationPreferenceAPIView.as_view(),
        name='user-notification-preferences'
    ),
    
    # Webhook endpoints for external integrations
    path(
        'api/v1/webhooks/',
        views.WebhookListCreateAPIView.as_view(),
        name='webhook-list-create'
    ),
    path(
        'api/v1/webhooks/<uuid:webhook_id>/',
        views.WebhookDetailAPIView.as_view(),
        name='webhook-detail'
    ),
    path(
        'api/v1/webhooks/<uuid:webhook_id>/test/',
        views.TestWebhookAPIView.as_view(),
        name='test-webhook'
    ),
    path(
        'api/v1/webhooks/<uuid:webhook_id>/logs/',
        views.WebhookDeliveryLogListAPIView.as_view(),
        name='webhook-delivery-logs'
    ),
    
    # Notification delivery tracking
    path(
        'api/v1/delivery-logs/',
        views.NotificationDeliveryLogListAPIView.as_view(),
        name='delivery-log-list'
    ),
    path(
        'api/v1/delivery-logs/<uuid:log_id>/',
        views.NotificationDeliveryLogDetailAPIView.as_view(),
        name='delivery-log-detail'
    ),
    path(
        'api/v1/delivery-logs/<uuid:log_id>/retry/',
        views.RetryNotificationDeliveryAPIView.as_view(),
        name='retry-notification-delivery'
    ),
    
    # Template management endpoints
    path(
        'api/v1/templates/<uuid:template_id>/render/',
        views.RenderNotificationTemplateAPIView.as_view(),
        name='render-template'
    ),
    path(
        'api/v1/templates/<uuid:template_id>/preview/',
        views.PreviewNotificationTemplateAPIView.as_view(),
        name='preview-template'
    ),
    
    # System-level notification endpoints
    path(
        'api/v1/system/statistics/',
        views.NotificationStatisticsAPIView.as_view(),
        name='notification-statistics'
    ),
    path(
        'api/v1/system/health/',
        views.NotificationSystemHealthAPIView.as_view(),
        name='notification-system-health'
    ),
    
    # Email bounce and complaint handling
    path(
        'api/v1/email/bounce/',
        views.EmailBounceHandlerAPIView.as_view(),
        name='email-bounce-handler'
    ),
    path(
        'api/v1/email/complaint/',
        views.EmailComplaintHandlerAPIView.as_view(),
        name='email-complaint-handler'
    ),
    
    # Subscription management
    path(
        'api/v1/subscriptions/',
        views.NotificationSubscriptionListCreateAPIView.as_view(),
        name='subscription-list-create'
    ),
    path(
        'api/v1/subscriptions/<uuid:subscription_id>/',
        views.NotificationSubscriptionDetailAPIView.as_view(),
        name='subscription-detail'
    ),
    path(
        'api/v1/subscriptions/<uuid:subscription_id>/toggle/',
        views.ToggleNotificationSubscriptionAPIView.as_view(),
        name='toggle-subscription'
    ),
]
