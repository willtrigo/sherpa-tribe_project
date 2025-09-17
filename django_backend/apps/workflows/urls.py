"""
Workflows URL Configuration

This module defines URL patterns for the workflows application,
handling task workflow engine, automation rules, and business logic endpoints.

Author: Enterprise Task Management System
Version: 1.0.0
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.urlpatterns import format_suffix_patterns

from . import views


# Application namespace for URL reversing
app_name = 'workflows'

# DRF Router configuration for ViewSets
router = DefaultRouter(trailing_slash=True)
router.register(
    r'definitions',
    views.WorkflowDefinitionViewSet,
    basename='workflow-definitions'
)
router.register(
    r'instances',
    views.WorkflowInstanceViewSet,
    basename='workflow-instances'
)
router.register(
    r'transitions',
    views.WorkflowTransitionViewSet,
    basename='workflow-transitions'
)
router.register(
    r'rules',
    views.AutomationRuleViewSet,
    basename='automation-rules'
)
router.register(
    r'templates',
    views.TaskTemplateViewSet,
    basename='task-templates'
)

# URL patterns for workflow management
urlpatterns = [
    # ========================
    # Router-based URLs (DRF ViewSets)
    # ========================
    path('api/', include(router.urls)),
    
    # ========================
    # Workflow Engine Operations
    # ========================
    path(
        'api/engine/validate-transition/',
        views.ValidateTransitionAPIView.as_view(),
        name='validate-transition'
    ),
    path(
        'api/engine/execute-transition/',
        views.ExecuteTransitionAPIView.as_view(),
        name='execute-transition'
    ),
    path(
        'api/engine/rollback-transition/',
        views.RollbackTransitionAPIView.as_view(),
        name='rollback-transition'
    ),
    
    # ========================
    # Task Template Operations
    # ========================
    path(
        'api/templates/<int:template_id>/instantiate/',
        views.InstantiateTemplateAPIView.as_view(),
        name='instantiate-template'
    ),
    path(
        'api/templates/<int:template_id>/preview/',
        views.PreviewTemplateAPIView.as_view(),
        name='preview-template'
    ),
    path(
        'api/templates/bulk-instantiate/',
        views.BulkInstantiateTemplatesAPIView.as_view(),
        name='bulk-instantiate-templates'
    ),
    
    # ========================
    # Automation Rules Management
    # ========================
    path(
        'api/rules/<int:rule_id>/activate/',
        views.ActivateRuleAPIView.as_view(),
        name='activate-rule'
    ),
    path(
        'api/rules/<int:rule_id>/deactivate/',
        views.DeactivateRuleAPIView.as_view(),
        name='deactivate-rule'
    ),
    path(
        'api/rules/<int:rule_id>/test/',
        views.TestRuleAPIView.as_view(),
        name='test-rule'
    ),
    path(
        'api/rules/bulk-execute/',
        views.BulkExecuteRulesAPIView.as_view(),
        name='bulk-execute-rules'
    ),
    
    # ========================
    # Workflow Analytics & Reporting
    # ========================
    path(
        'api/analytics/workflow-performance/',
        views.WorkflowPerformanceAnalyticsAPIView.as_view(),
        name='workflow-performance'
    ),
    path(
        'api/analytics/transition-metrics/',
        views.TransitionMetricsAPIView.as_view(),
        name='transition-metrics'
    ),
    path(
        'api/analytics/bottleneck-analysis/',
        views.BottleneckAnalysisAPIView.as_view(),
        name='bottleneck-analysis'
    ),
    
    # ========================
    # SLA Management
    # ========================
    path(
        'api/sla/definitions/',
        views.SLADefinitionListCreateAPIView.as_view(),
        name='sla-definitions'
    ),
    path(
        'api/sla/definitions/<int:pk>/',
        views.SLADefinitionRetrieveUpdateDestroyAPIView.as_view(),
        name='sla-definition-detail'
    ),
    path(
        'api/sla/violations/',
        views.SLAViolationListAPIView.as_view(),
        name='sla-violations'
    ),
    path(
        'api/sla/escalations/',
        views.SLAEscalationListCreateAPIView.as_view(),
        name='sla-escalations'
    ),
    
    # ========================
    # Dependency Management
    # ========================
    path(
        'api/dependencies/create/',
        views.CreateTaskDependencyAPIView.as_view(),
        name='create-dependency'
    ),
    path(
        'api/dependencies/<int:dependency_id>/remove/',
        views.RemoveTaskDependencyAPIView.as_view(),
        name='remove-dependency'
    ),
    path(
        'api/dependencies/critical-path/',
        views.CriticalPathAnalysisAPIView.as_view(),
        name='critical-path'
    ),
    path(
        'api/dependencies/validate-cycle/',
        views.ValidateDependencyCycleAPIView.as_view(),
        name='validate-cycle'
    ),
    
    # ========================
    # Recurring Tasks Management
    # ========================
    path(
        'api/recurring/',
        views.RecurringTaskListCreateAPIView.as_view(),
        name='recurring-tasks'
    ),
    path(
        'api/recurring/<int:pk>/',
        views.RecurringTaskRetrieveUpdateDestroyAPIView.as_view(),
        name='recurring-task-detail'
    ),
    path(
        'api/recurring/<int:recurring_id>/generate/',
        views.GenerateRecurringTaskAPIView.as_view(),
        name='generate-recurring-task'
    ),
    path(
        'api/recurring/<int:recurring_id>/pause/',
        views.PauseRecurringTaskAPIView.as_view(),
        name='pause-recurring-task'
    ),
    path(
        'api/recurring/<int:recurring_id>/resume/',
        views.ResumeRecurringTaskAPIView.as_view(),
        name='resume-recurring-task'
    ),
    
    # ========================
    # Workload Balancing
    # ========================
    path(
        'api/workload/balance/',
        views.WorkloadBalancingAPIView.as_view(),
        name='workload-balance'
    ),
    path(
        'api/workload/user-capacity/',
        views.UserCapacityAnalysisAPIView.as_view(),
        name='user-capacity'
    ),
    path(
        'api/workload/team-metrics/',
        views.TeamWorkloadMetricsAPIView.as_view(),
        name='team-metrics'
    ),
    path(
        'api/workload/recommendations/',
        views.WorkloadRecommendationsAPIView.as_view(),
        name='workload-recommendations'
    ),
    
    # ========================
    # Priority Calculation
    # ========================
    path(
        'api/priority/calculate/',
        views.CalculateTaskPriorityAPIView.as_view(),
        name='calculate-priority'
    ),
    path(
        'api/priority/bulk-recalculate/',
        views.BulkRecalculatePriorityAPIView.as_view(),
        name='bulk-recalculate-priority'
    ),
    path(
        'api/priority/factors/',
        views.PriorityFactorsAPIView.as_view(),
        name='priority-factors'
    ),
    
    # ========================
    # Business Hours & Calendar
    # ========================
    path(
        'api/business-hours/',
        views.BusinessHoursConfigurationAPIView.as_view(),
        name='business-hours'
    ),
    path(
        'api/business-hours/calculate/',
        views.CalculateBusinessHoursAPIView.as_view(),
        name='calculate-business-hours'
    ),
    path(
        'api/holidays/',
        views.HolidayCalendarAPIView.as_view(),
        name='holiday-calendar'
    ),
    
    # ========================
    # Workflow Import/Export
    # ========================
    path(
        'api/export/workflows/',
        views.ExportWorkflowsAPIView.as_view(),
        name='export-workflows'
    ),
    path(
        'api/import/workflows/',
        views.ImportWorkflowsAPIView.as_view(),
        name='import-workflows'
    ),
    path(
        'api/export/templates/',
        views.ExportTemplatesAPIView.as_view(),
        name='export-templates'
    ),
    path(
        'api/import/templates/',
        views.ImportTemplatesAPIView.as_view(),
        name='import-templates'
    ),
    
    # ========================
    # Workflow Simulation & Testing
    # ========================
    path(
        'api/simulation/run/',
        views.RunWorkflowSimulationAPIView.as_view(),
        name='run-simulation'
    ),
    path(
        'api/simulation/results/<str:simulation_id>/',
        views.SimulationResultsAPIView.as_view(),
        name='simulation-results'
    ),
    
    # ========================
    # Health Check & Diagnostics
    # ========================
    path(
        'api/health/',
        views.WorkflowHealthCheckAPIView.as_view(),
        name='workflow-health'
    ),
    path(
        'api/diagnostics/',
        views.WorkflowDiagnosticsAPIView.as_view(),
        name='workflow-diagnostics'
    ),
]

# Apply format suffixes for content negotiation
urlpatterns = format_suffix_patterns(urlpatterns, allowed=['json', 'xml'])

# Add debug URLs in development mode
if __debug__:
    from django.conf import settings
    
    if settings.DEBUG:
        urlpatterns += [
            path(
                'api/debug/workflow-states/',
                views.DebugWorkflowStatesAPIView.as_view(),
                name='debug-workflow-states'
            ),
            path(
                'api/debug/rule-execution-log/',
                views.DebugRuleExecutionLogAPIView.as_view(),
                name='debug-rule-execution'
            ),
        ]
