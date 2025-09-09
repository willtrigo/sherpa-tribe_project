"""
Task-related URL configuration for the Enterprise Task Management System.

This module defines URL patterns for both API and web views related to task management,
including CRUD operations, task assignment, comments, and history tracking.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views


# API URL patterns using DRF router for RESTful endpoints
api_router = DefaultRouter()
api_router.register(r'tasks', views.TaskViewSet, basename='task')

# Define URL patterns
app_name = 'tasks'

urlpatterns = [
    # =============================================================================
    # API ENDPOINTS (RESTful)
    # =============================================================================
    
    # DRF Router URLs - provides standard CRUD operations
    # GET    /api/tasks/           - List tasks with filtering, search, pagination
    # POST   /api/tasks/           - Create new task
    # GET    /api/tasks/{id}/      - Retrieve specific task
    # PUT    /api/tasks/{id}/      - Full update of task
    # PATCH  /api/tasks/{id}/      - Partial update of task
    # DELETE /api/tasks/{id}/      - Delete task
    path('api/', include(api_router.urls)),
    
    # Custom API endpoints for specific task operations
    path(
        'api/tasks/<int:pk>/assign/',
        views.TaskAssignmentAPIView.as_view(),
        name='api-task-assign'
    ),
    path(
        'api/tasks/<int:pk>/comments/',
        views.TaskCommentListCreateAPIView.as_view(),
        name='api-task-comments'
    ),
    path(
        'api/tasks/<int:pk>/history/',
        views.TaskHistoryAPIView.as_view(),
        name='api-task-history'
    ),
    path(
        'api/tasks/<int:pk>/duplicate/',
        views.TaskDuplicateAPIView.as_view(),
        name='api-task-duplicate'
    ),
    path(
        'api/tasks/<int:pk>/archive/',
        views.TaskArchiveAPIView.as_view(),
        name='api-task-archive'
    ),
    path(
        'api/tasks/<int:pk>/unarchive/',
        views.TaskUnarchiveAPIView.as_view(),
        name='api-task-unarchive'
    ),
    path(
        'api/tasks/bulk-actions/',
        views.TaskBulkActionsAPIView.as_view(),
        name='api-task-bulk-actions'
    ),
    
    # =============================================================================
    # WEB VIEWS (Django Templates)
    # =============================================================================
    
    # Task list and dashboard
    path(
        '',
        views.TaskListView.as_view(),
        name='task-list'
    ),
    path(
        'dashboard/',
        views.TaskDashboardView.as_view(),
        name='task-dashboard'
    ),
    
    # Task CRUD operations
    path(
        'create/',
        views.TaskCreateView.as_view(),
        name='task-create'
    ),
    path(
        '<int:pk>/',
        views.TaskDetailView.as_view(),
        name='task-detail'
    ),
    path(
        '<int:pk>/edit/',
        views.TaskUpdateView.as_view(),
        name='task-update'
    ),
    path(
        '<int:pk>/delete/',
        views.TaskDeleteView.as_view(),
        name='task-delete'
    ),
    
    # Task-specific web operations
    path(
        '<int:pk>/assign/',
        views.TaskAssignmentView.as_view(),
        name='task-assign-web'
    ),
    path(
        '<int:pk>/comments/',
        views.TaskCommentView.as_view(),
        name='task-comments-web'
    ),
    path(
        '<int:pk>/history/',
        views.TaskHistoryView.as_view(),
        name='task-history-web'
    ),
    path(
        '<int:pk>/duplicate/',
        views.TaskDuplicateView.as_view(),
        name='task-duplicate-web'
    ),
    
    # Advanced task views
    path(
        'my-tasks/',
        views.MyTasksView.as_view(),
        name='my-tasks'
    ),
    path(
        'overdue/',
        views.OverdueTasksView.as_view(),
        name='overdue-tasks'
    ),
    path(
        'archived/',
        views.ArchivedTasksView.as_view(),
        name='archived-tasks'
    ),
    path(
        'templates/',
        views.TaskTemplateListView.as_view(),
        name='task-templates'
    ),
    path(
        'templates/create/',
        views.TaskTemplateCreateView.as_view(),
        name='task-template-create'
    ),
    path(
        'templates/<int:pk>/use/',
        views.TaskFromTemplateView.as_view(),
        name='task-from-template'
    ),
    
    # Search and filtering
    path(
        'search/',
        views.TaskSearchView.as_view(),
        name='task-search'
    ),
    path(
        'advanced-search/',
        views.TaskAdvancedSearchView.as_view(),
        name='task-advanced-search'
    ),
    
    # Reports and analytics (web interface)
    path(
        'reports/',
        views.TaskReportsView.as_view(),
        name='task-reports'
    ),
    path(
        'analytics/',
        views.TaskAnalyticsView.as_view(),
        name='task-analytics'
    ),
    
    # Export/Import operations
    path(
        'export/',
        views.TaskExportView.as_view(),
        name='task-export'
    ),
    path(
        'import/',
        views.TaskImportView.as_view(),
        name='task-import'
    ),
    
    # =============================================================================
    # AJAX/HTMX ENDPOINTS (for dynamic UI updates)
    # =============================================================================
    
    path(
        'htmx/task-row/<int:pk>/',
        views.TaskRowHTMXView.as_view(),
        name='htmx-task-row'
    ),
    path(
        'htmx/task-status-update/<int:pk>/',
        views.TaskStatusUpdateHTMXView.as_view(),
        name='htmx-task-status-update'
    ),
    path(
        'htmx/task-priority-update/<int:pk>/',
        views.TaskPriorityUpdateHTMXView.as_view(),
        name='htmx-task-priority-update'
    ),
    path(
        'htmx/assignee-autocomplete/',
        views.AssigneeAutocompleteHTMXView.as_view(),
        name='htmx-assignee-autocomplete'
    ),
    path(
        'htmx/tag-autocomplete/',
        views.TagAutocompleteHTMXView.as_view(),
        name='htmx-tag-autocomplete'
    ),
]
