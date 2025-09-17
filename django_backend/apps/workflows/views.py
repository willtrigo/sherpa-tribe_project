"""
Workflow Management Views

This module implements enterprise-grade workflow automation views for task management.
Handles workflow engine operations, automation rules, and business logic processing.
"""

import logging

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from ..common.exceptions import ValidationException, WorkflowException
from ..common.mixins import AuditLogMixin, CacheResponseMixin
from ..common.pagination import StandardResultsSetPagination
from ..tasks.models import Task
from ..users.models import User
from .engines import AutomationEngine, TemplateEngine, WorkflowEngine
from .models import (
    AutomationRule,
    RecurringTaskConfig,
    TaskTemplate,
    Workflow,
    WorkflowExecution,
    WorkflowRule,
    WorkflowState,
)
from .permissions import WorkflowPermission
from .rules import RuleExecutor, RuleValidator
from .serializers import (
    AutomationRuleSerializer,
    RecurringTaskConfigSerializer,
    TaskTemplateSerializer,
    WorkflowExecutionSerializer,
    WorkflowRuleSerializer,
    WorkflowSerializer,
    WorkflowStateSerializer,
    WorkflowTriggerSerializer,
)


logger = logging.getLogger(__name__)

User = get_user_model()


class WorkflowViewSet(AuditLogMixin, CacheResponseMixin, ModelViewSet):
    """
    Comprehensive workflow management viewset.
    
    Provides CRUD operations and workflow-specific actions for enterprise
    workflow automation including execution, validation, and monitoring.
    """
    
    queryset = Workflow.objects.select_related('created_by', 'team').prefetch_related(
        'rules', 'executions', 'states'
    )
    serializer_class = WorkflowSerializer
    permission_classes = [permissions.IsAuthenticated, WorkflowPermission]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    
    search_fields = ['name', 'description', 'category']
    ordering_fields = ['name', 'created_at', 'updated_at', 'priority', 'status']
    ordering = ['-created_at']
    filterset_fields = ['status', 'category', 'is_active', 'created_by', 'team']
    
    cache_timeout = 300  # 5 minutes
    cache_key_prefix = 'workflow'
    
    def get_queryset(self):
        """Optimize queryset based on user permissions and context."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if not user.is_superuser:
            queryset = queryset.filter(
                Q(created_by=user) | 
                Q(team__members=user) |
                Q(is_public=True)
            ).distinct()
        
        # Apply additional filters for performance
        if self.action in ['list', 'retrieve']:
            queryset = queryset.select_related(
                'created_by__profile', 'team'
            ).prefetch_related(
                'rules__conditions',
                'rules__actions', 
                'executions__workflow_state'
            )
        
        return queryset
    
    def perform_create(self, serializer):
        """Handle workflow creation with validation and initialization."""
        try:
            with transaction.atomic():
                workflow = serializer.save(
                    created_by=self.request.user,
                    status='draft'
                )
                
                # Initialize workflow engine
                engine = WorkflowEngine(workflow)
                engine.initialize()
                
                self.log_audit_event('workflow_created', workflow.pk)
                
        except Exception as e:
            logger.error(f"Workflow creation failed: {str(e)}")
            raise WorkflowException("Failed to create workflow")
    
    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """
        Execute workflow with provided context and parameters.
        
        Triggers workflow execution with comprehensive validation,
        state management, and error handling.
        """
        workflow = self.get_object()
        
        try:
            # Validate execution prerequisites
            if not workflow.is_active:
                return Response(
                    {'error': 'Workflow is not active'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            context_data = request.data.get('context', {})
            execution_params = request.data.get('parameters', {})
            
            # Initialize workflow engine
            engine = WorkflowEngine(workflow)
            
            # Execute with comprehensive error handling
            with transaction.atomic():
                execution = engine.execute(
                    context=context_data,
                    parameters=execution_params,
                    triggered_by=request.user
                )
                
                serializer = WorkflowExecutionSerializer(execution)
                
                self.log_audit_event('workflow_executed', workflow.pk, {
                    'execution_id': execution.pk,
                    'context': context_data,
                    'parameters': execution_params
                })
                
                return Response(serializer.data, status=status.HTTP_201_CREATED)
                
        except ValidationError as e:
            logger.warning(f"Workflow validation failed: {str(e)}")
            return Response(
                {'error': 'Validation failed', 'details': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Workflow execution failed: {str(e)}")
            return Response(
                {'error': 'Execution failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def validate_workflow(self, request, pk=None):
        """
        Comprehensive workflow validation including rules, conditions, and dependencies.
        """
        workflow = self.get_object()
        
        try:
            validator = RuleValidator(workflow)
            validation_result = validator.validate_complete()
            
            return Response({
                'is_valid': validation_result.is_valid,
                'errors': validation_result.errors,
                'warnings': validation_result.warnings,
                'recommendations': validation_result.recommendations
            })
            
        except Exception as e:
            logger.error(f"Workflow validation error: {str(e)}")
            return Response(
                {'error': 'Validation process failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def execution_history(self, request, pk=None):
        """
        Retrieve comprehensive execution history with analytics and insights.
        """
        workflow = self.get_object()
        
        executions = WorkflowExecution.objects.filter(
            workflow=workflow
        ).select_related(
            'triggered_by', 'workflow_state'
        ).order_by('-created_at')
        
        # Apply pagination
        paginator = self.paginate_queryset(executions)
        if paginator is not None:
            serializer = WorkflowExecutionSerializer(paginator, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = WorkflowExecutionSerializer(executions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """
        Generate comprehensive workflow analytics and performance metrics.
        """
        workflow = self.get_object()
        
        cache_key = f'workflow_analytics_{workflow.pk}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return Response(cached_data)
        
        # Calculate comprehensive metrics
        executions = WorkflowExecution.objects.filter(workflow=workflow)
        
        analytics_data = {
            'total_executions': executions.count(),
            'success_rate': self._calculate_success_rate(executions),
            'average_duration': self._calculate_average_duration(executions),
            'execution_trends': self._get_execution_trends(executions),
            'error_analysis': self._analyze_errors(executions),
            'performance_metrics': self._get_performance_metrics(executions)
        }
        
        # Cache results for 15 minutes
        cache.set(cache_key, analytics_data, 900)
        
        return Response(analytics_data)
    
    @action(detail=False, methods=['post'])
    def bulk_execute(self, request):
        """
        Execute multiple workflows in batch with comprehensive monitoring.
        """
        workflow_ids = request.data.get('workflow_ids', [])
        context_data = request.data.get('context', {})
        
        if not workflow_ids:
            return Response(
                {'error': 'No workflow IDs provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        results = []
        
        for workflow_id in workflow_ids:
            try:
                workflow = Workflow.objects.get(pk=workflow_id)
                engine = WorkflowEngine(workflow)
                
                execution = engine.execute(
                    context=context_data,
                    triggered_by=request.user
                )
                
                results.append({
                    'workflow_id': workflow_id,
                    'execution_id': execution.pk,
                    'status': 'success'
                })
                
            except Workflow.DoesNotExist:
                results.append({
                    'workflow_id': workflow_id,
                    'status': 'error',
                    'error': 'Workflow not found'
                })
            except Exception as e:
                results.append({
                    'workflow_id': workflow_id,
                    'status': 'error',
                    'error': str(e)
                })
        
        return Response({'results': results})
    
    def _calculate_success_rate(self, executions) -> float:
        """Calculate workflow execution success rate."""
        if not executions.exists():
            return 0.0
        
        total = executions.count()
        successful = executions.filter(status='completed').count()
        
        return (successful / total) * 100
    
    def _calculate_average_duration(self, executions) -> Optional[float]:
        """Calculate average execution duration in seconds."""
        completed_executions = executions.filter(
            status='completed',
            completed_at__isnull=False
        )
        
        if not completed_executions.exists():
            return None
        
        durations = []
        for execution in completed_executions:
            if execution.completed_at and execution.created_at:
                duration = (execution.completed_at - execution.created_at).total_seconds()
                durations.append(duration)
        
        return sum(durations) / len(durations) if durations else None
    
    def _get_execution_trends(self, executions) -> Dict[str, Any]:
        """Analyze execution trends over time."""
        last_30_days = timezone.now() - timedelta(days=30)
        
        recent_executions = executions.filter(created_at__gte=last_30_days)
        
        return {
            'last_30_days': recent_executions.count(),
            'daily_average': recent_executions.count() / 30,
            'peak_day': self._get_peak_execution_day(recent_executions)
        }
    
    def _analyze_errors(self, executions) -> Dict[str, Any]:
        """Analyze error patterns and frequency."""
        failed_executions = executions.filter(status='failed')
        
        error_types = {}
        for execution in failed_executions:
            error_type = execution.error_message or 'Unknown'
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return {
            'total_failures': failed_executions.count(),
            'error_types': error_types,
            'failure_rate': (failed_executions.count() / executions.count() * 100) if executions.exists() else 0
        }
    
    def _get_performance_metrics(self, executions) -> Dict[str, Any]:
        """Calculate detailed performance metrics."""
        return {
            'total_executions': executions.count(),
            'completed': executions.filter(status='completed').count(),
            'failed': executions.filter(status='failed').count(),
            'running': executions.filter(status='running').count(),
            'pending': executions.filter(status='pending').count()
        }
    
    def _get_peak_execution_day(self, executions):
        """Find the day with most executions."""
        # Implementation for finding peak execution day
        return None  # Placeholder


class AutomationRuleViewSet(ModelViewSet):
    """
    Advanced automation rule management for enterprise task automation.
    
    Handles creation, validation, and execution of complex automation rules
    including conditional logic, triggers, and actions.
    """
    
    queryset = AutomationRule.objects.select_related('created_by').prefetch_related(
        'conditions', 'actions', 'triggers'
    )
    serializer_class = AutomationRuleSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    
    search_fields = ['name', 'description', 'trigger_event']
    ordering_fields = ['name', 'priority', 'created_at', 'last_executed']
    filterset_fields = ['is_active', 'trigger_event', 'created_by']
    
    def perform_create(self, serializer):
        """Create automation rule with comprehensive validation."""
        try:
            with transaction.atomic():
                rule = serializer.save(created_by=self.request.user)
                
                # Initialize automation engine
                engine = AutomationEngine()
                engine.register_rule(rule)
                
                logger.info(f"Automation rule created: {rule.pk}")
                
        except Exception as e:
            logger.error(f"Automation rule creation failed: {str(e)}")
            raise ValidationException("Failed to create automation rule")
    
    @action(detail=True, methods=['post'])
    def test_rule(self, request, pk=None):
        """
        Test automation rule with provided test data and context.
        """
        rule = self.get_object()
        test_data = request.data.get('test_data', {})
        
        try:
            executor = RuleExecutor(rule)
            result = executor.test_execution(test_data)
            
            return Response({
                'test_passed': result.success,
                'conditions_met': result.conditions_met,
                'actions_executed': result.actions_executed,
                'execution_log': result.execution_log,
                'warnings': result.warnings
            })
            
        except Exception as e:
            logger.error(f"Rule test failed: {str(e)}")
            return Response(
                {'error': 'Rule test failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def execute_manual(self, request, pk=None):
        """
        Manually execute automation rule with provided context.
        """
        rule = self.get_object()
        context_data = request.data.get('context', {})
        
        try:
            if not rule.is_active:
                return Response(
                    {'error': 'Rule is not active'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            executor = RuleExecutor(rule)
            execution_result = executor.execute_with_context(
                context_data, 
                manual_trigger=True,
                triggered_by=request.user
            )
            
            rule.last_executed = timezone.now()
            rule.execution_count = F('execution_count') + 1
            rule.save(update_fields=['last_executed', 'execution_count'])
            
            return Response({
                'execution_id': execution_result.execution_id,
                'success': execution_result.success,
                'actions_performed': execution_result.actions_performed,
                'execution_time': execution_result.execution_time
            })
            
        except Exception as e:
            logger.error(f"Manual rule execution failed: {str(e)}")
            return Response(
                {'error': 'Rule execution failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TaskTemplateViewSet(ModelViewSet):
    """
    Enterprise task template management with variable substitution and validation.
    
    Provides comprehensive template management including variable handling,
    validation, and instantiation capabilities.
    """
    
    queryset = TaskTemplate.objects.select_related('created_by', 'category').prefetch_related(
        'variables', 'default_assignees', 'tags'
    )
    serializer_class = TaskTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    @action(detail=True, methods=['post'])
    def instantiate(self, request, pk=None):
        """
        Create task instances from template with variable substitution.
        """
        template = self.get_object()
        variables = request.data.get('variables', {})
        override_fields = request.data.get('overrides', {})
        
        try:
            engine = TemplateEngine(template)
            
            # Validate required variables
            validation_result = engine.validate_variables(variables)
            if not validation_result.is_valid:
                return Response(
                    {'error': 'Variable validation failed', 'details': validation_result.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create task from template
            with transaction.atomic():
                task = engine.instantiate(
                    variables=variables,
                    overrides=override_fields,
                    created_by=request.user
                )
                
                return Response({
                    'task_id': task.pk,
                    'success': True,
                    'variables_applied': variables,
                    'overrides_applied': override_fields
                }, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            logger.error(f"Template instantiation failed: {str(e)}")
            return Response(
                {'error': 'Template instantiation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def preview(self, request, pk=None):
        """
        Preview task creation with provided variables without actual instantiation.
        """
        template = self.get_object()
        variables = dict(request.query_params)
        
        # Remove non-variable query parameters
        variables.pop('format', None)
        
        try:
            engine = TemplateEngine(template)
            preview_data = engine.generate_preview(variables)
            
            return Response(preview_data)
            
        except Exception as e:
            logger.error(f"Template preview failed: {str(e)}")
            return Response(
                {'error': 'Preview generation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RecurringTaskConfigViewSet(ModelViewSet):
    """
    Advanced recurring task configuration management.
    
    Handles complex recurring task patterns, scheduling, and lifecycle management
    with comprehensive validation and monitoring capabilities.
    """
    
    queryset = RecurringTaskConfig.objects.select_related(
        'template', 'created_by'
    ).prefetch_related('generated_tasks')
    serializer_class = RecurringTaskConfigSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=True, methods=['post'])
    def generate_next_tasks(self, request, pk=None):
        """
        Generate next scheduled tasks based on recurrence pattern.
        """
        config = self.get_object()
        
        try:
            if not config.is_active:
                return Response(
                    {'error': 'Recurring configuration is not active'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Calculate next execution times
            next_executions = config.calculate_next_executions(
                count=request.data.get('count', 5)
            )
            
            generated_tasks = []
            
            with transaction.atomic():
                for execution_time in next_executions:
                    task_data = config.prepare_task_data(execution_time)
                    
                    # Create task using template engine
                    engine = TemplateEngine(config.template)
                    task = engine.instantiate(
                        variables=task_data.get('variables', {}),
                        overrides={
                            'due_date': execution_time,
                            'created_by': request.user
                        },
                        created_by=request.user
                    )
                    
                    generated_tasks.append({
                        'task_id': task.pk,
                        'due_date': execution_time.isoformat(),
                        'title': task.title
                    })
            
            # Update last generation timestamp
            config.last_generated = timezone.now()
            config.save(update_fields=['last_generated'])
            
            return Response({
                'generated_count': len(generated_tasks),
                'tasks': generated_tasks
            })
            
        except Exception as e:
            logger.error(f"Recurring task generation failed: {str(e)}")
            return Response(
                {'error': 'Task generation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkflowAnalyticsAPIView(APIView):
    """
    Comprehensive workflow analytics and reporting endpoint.
    
    Provides advanced analytics, insights, and reporting capabilities
    for workflow performance monitoring and optimization.
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    @method_decorator(cache_page(300))  # Cache for 5 minutes
    def get(self, request):
        """
        Generate comprehensive workflow analytics dashboard data.
        """
        try:
            analytics_data = self._generate_comprehensive_analytics()
            return Response(analytics_data)
            
        except Exception as e:
            logger.error(f"Analytics generation failed: {str(e)}")
            return Response(
                {'error': 'Analytics generation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _generate_comprehensive_analytics(self) -> Dict[str, Any]:
        """Generate comprehensive workflow analytics."""
        now = timezone.now()
        last_30_days = now - timedelta(days=30)
        
        return {
            'overview': self._get_overview_metrics(),
            'performance': self._get_performance_metrics(),
            'trends': self._get_trend_analysis(last_30_days, now),
            'efficiency': self._get_efficiency_metrics(),
            'automation': self._get_automation_metrics(),
            'recommendations': self._generate_recommendations()
        }
    
    def _get_overview_metrics(self) -> Dict[str, Any]:
        """Get high-level overview metrics."""
        return {
            'total_workflows': Workflow.objects.count(),
            'active_workflows': Workflow.objects.filter(is_active=True).count(),
            'total_executions': WorkflowExecution.objects.count(),
            'automation_rules': AutomationRule.objects.filter(is_active=True).count()
        }
    
    def _get_performance_metrics(self) -> Dict[str, Any]:
        """Get detailed performance metrics."""
        executions = WorkflowExecution.objects.all()
        
        return {
            'success_rate': self._calculate_overall_success_rate(executions),
            'average_execution_time': self._calculate_average_execution_time(executions),
            'failure_analysis': self._analyze_failure_patterns(executions)
        }
    
    def _get_trend_analysis(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Analyze trends over specified period."""
        return {
            'execution_trends': self._analyze_execution_trends(start_date, end_date),
            'performance_trends': self._analyze_performance_trends(start_date, end_date)
        }
    
    def _get_efficiency_metrics(self) -> Dict[str, Any]:
        """Calculate workflow efficiency metrics."""
        return {
            'automation_percentage': self._calculate_automation_percentage(),
            'time_saved': self._calculate_time_savings(),
            'resource_utilization': self._calculate_resource_utilization()
        }
    
    def _get_automation_metrics(self) -> Dict[str, Any]:
        """Get automation-specific metrics."""
        return {
            'active_rules': AutomationRule.objects.filter(is_active=True).count(),
            'rule_executions': self._get_rule_execution_stats(),
            'trigger_distribution': self._get_trigger_distribution()
        }
    
    def _generate_recommendations(self) -> List[Dict[str, Any]]:
        """Generate actionable recommendations based on analytics."""
        recommendations = []
        
        # Analyze workflow performance and suggest improvements
        low_performing_workflows = self._identify_low_performing_workflows()
        if low_performing_workflows:
            recommendations.append({
                'type': 'performance',
                'priority': 'high',
                'title': 'Optimize Low-Performing Workflows',
                'description': f'Found {len(low_performing_workflows)} workflows with success rates below 80%',
                'action': 'Review and optimize workflow logic'
            })
        
        return recommendations
    
    # Additional helper methods would be implemented here...
    def _calculate_overall_success_rate(self, executions):
        """Calculate overall success rate across all workflows."""
        if not executions.exists():
            return 0.0
        
        total = executions.count()
        successful = executions.filter(status='completed').count()
        return (successful / total) * 100
    
    def _calculate_average_execution_time(self, executions):
        """Calculate average execution time across all workflows."""
        # Implementation would calculate actual execution times
        return None  # Placeholder
    
    def _analyze_failure_patterns(self, executions):
        """Analyze common failure patterns."""
        # Implementation would analyze failure reasons and patterns
        return {}  # Placeholder
    
    def _analyze_execution_trends(self, start_date, end_date):
        """Analyze execution trends over time period."""
        # Implementation would analyze trends
        return {}  # Placeholder
    
    def _analyze_performance_trends(self, start_date, end_date):
        """Analyze performance trends over time period."""
        # Implementation would analyze performance trends
        return {}  # Placeholder
    
    def _calculate_automation_percentage(self):
        """Calculate percentage of tasks handled by automation."""
        # Implementation would calculate automation metrics
        return 0.0  # Placeholder
    
    def _calculate_time_savings(self):
        """Calculate time saved through automation."""
        # Implementation would calculate time savings
        return 0.0  # Placeholder
    
    def _calculate_resource_utilization(self):
        """Calculate resource utilization metrics."""
        # Implementation would calculate resource metrics
        return {}  # Placeholder
    
    def _get_rule_execution_stats(self):
        """Get automation rule execution statistics."""
        # Implementation would get rule stats
        return {}  # Placeholder
    
    def _get_trigger_distribution(self):
        """Get distribution of trigger types."""
        # Implementation would get trigger distribution
        return {}  # Placeholder
    
    def _identify_low_performing_workflows(self):
        """Identify workflows with poor performance metrics."""
        # Implementation would identify low-performing workflows
        return []  # Placeholder
