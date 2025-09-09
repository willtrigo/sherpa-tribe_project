"""
Common URL patterns for shared functionality.
"""
from django.urls import path, include
from django.views.generic import RedirectView

from . import views

app_name = 'common'

urlpatterns = [
    # Health check endpoints
    path('health/', views.HealthCheckView.as_view(), name='health_check'),
    path('healthz/', views.HealthCheckView.as_view(), name='health_check_k8s'),
    path('ping/', views.PingView.as_view(), name='ping'),

    # System status endpoints
    path('status/', views.SystemStatusView.as_view(), name='system_status'),
    path('version/', views.VersionView.as_view(), name='version'),

    # API documentation redirect
    path('docs/', RedirectView.as_view(url='/api/docs/', permanent=False), name='api_docs_redirect'),

    # Dashboard and landing
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard_explicit'),

    # Error pages for testing
    path('test-404/', views.Test404View.as_view(), name='test_404'),
    path('test-500/', views.Test500View.as_view(), name='test_500'),

    # Utility endpoints
    path('export/', include([
        path('csv/', views.ExportCSVView.as_view(), name='export_csv'),
        path('excel/', views.ExportExcelView.as_view(), name='export_excel'),
        path('pdf/', views.ExportPDFView.as_view(), name='export_pdf'),
    ])),

    # Search endpoints
    path('search/', views.GlobalSearchView.as_view(), name='global_search'),
    path('search/suggestions/', views.SearchSuggestionsView.as_view(), name='search_suggestions'),

    # File upload endpoints
    path('upload/', views.FileUploadView.as_view(), name='file_upload'),
    path('upload/bulk/', views.BulkUploadView.as_view(), name='bulk_upload'),

    # Notifications endpoints (if not handled by dedicated app)
    path('notifications/', include([
        path('', views.NotificationListView.as_view(), name='notification_list'),
        path('mark-read/', views.MarkNotificationsReadView.as_view(), name='mark_notifications_read'),
        path('count/', views.UnreadNotificationCountView.as_view(), name='unread_notification_count'),
    ])),

    # Settings and preferences
    path('settings/', views.UserSettingsView.as_view(), name='user_settings'),
    path('preferences/', views.UserPreferencesView.as_view(), name='user_preferences'),

    # Analytics and metrics (if not handled by Flask service)
    path('metrics/', include([
        path('', views.MetricsDashboardView.as_view(), name='metrics_dashboard'),
        path('api/', views.MetricsAPIView.as_view(), name='metrics_api'),
        path('performance/', views.PerformanceMetricsView.as_view(), name='performance_metrics'),
    ])),
]

# Add debug-only URLs in development
from django.conf import settings
if settings.DEBUG:
    urlpatterns += [
        path('debug/', include([
            path('info/', views.DebugInfoView.as_view(), name='debug_info'),
            path('cache/', views.CacheTestView.as_view(), name='cache_test'),
            path('celery/', views.CeleryTestView.as_view(), name='celery_test'),
        ])),
    ]
