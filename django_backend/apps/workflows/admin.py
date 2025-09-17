"""
Django admin configuration for workflow management system.

This module provides comprehensive admin interfaces for managing workflow templates,
rules, states, transitions, and assignments with enterprise-grade functionality.
"""

from django.contrib import admin
from django.contrib.admin import ModelAdmin, TabularInline, StackedInline
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db import transaction
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    WorkflowTemplate,
    WorkflowRule,
    WorkflowState,
    WorkflowTransition,
    WorkflowAssignment,
    WorkflowExecution,
    WorkflowCondition,
    WorkflowAction,
    WorkflowVariable
)


class WorkflowConditionInline(TabularInline):
    """Inline admin for workflow conditions."""
    
    model = WorkflowCondition
    extra = 1
    fields = ('condition_type', 'field_name', 'operator', 'expected_value', 'is_active')
    
    class Meta:
        verbose_name = _("Workflow Condition")
        verbose_name_plural = _("Workflow Conditions")


class WorkflowActionInline(TabularInline):
    """Inline admin for workflow actions."""
    
    model = WorkflowAction
    extra = 1
    fields = ('action_type', 'target_field', 'action_value', 'execution_order', 'is_active')
    ordering = ('execution_order',)
    
    class Meta:
        verbose_name = _("Workflow Action")
        verbose_name_plural = _("Workflow Actions")


class WorkflowVariableInline(StackedInline):
    """Inline admin for workflow variables."""
    
    model = WorkflowVariable
    extra = 0
    fields = ('name', 'variable_type', 'default_value', 'is_required', 'description')
    
    class Meta:
        verbose_name = _("Workflow Variable")
        verbose_name_plural = _("Workflow Variables")


class WorkflowTransitionInline(TabularInline):
    """Inline admin for workflow state transitions."""
    
    model = WorkflowTransition
    fk_name = 'from_state'
    extra = 1
    fields = ('to_state', 'condition', 'action', 'permission_required', 'is_automatic')
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related(
            'from_state', 'to_state', 'condition', 'action'
        )


@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(ModelAdmin):
    """Admin interface for workflow templates."""
    
    list_display = (
        'name', 'category', 'version', 'is_active', 'created_by', 
        'usage_count', 'last_modified', 'template_actions'
    )
    list_filter = ('category', 'is_active', 'created_at', 'created_by')
    search_fields = ('name', 'description', 'category')
    ordering = ('-created_at', 'name')
    readonly_fields = ('created_at', 'updated_at', 'usage_count')
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'description', 'category', 'version')
        }),
        (_('Configuration'), {
            'fields': ('initial_state', 'final_states', 'is_active', 'metadata'),
            'classes': ('collapse',)
        }),
        (_('Advanced Settings'), {
            'fields': ('auto_assign_rules', 'escalation_rules', 'sla_settings'),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('created_by', 'created_at', 'updated_at', 'usage_count'),
            'classes': ('collapse',)
        })
    )
    
    inlines = [WorkflowVariableInline]
    
    def usage_count(self, obj: WorkflowTemplate) -> int:
        """Display usage count for the template."""
        return obj.workflow_executions.count()
    usage_count.short_description = _('Usage Count')
    usage_count.admin_order_field = 'workflow_executions__count'
    
    def template_actions(self, obj: WorkflowTemplate) -> str:
        """Display action links for the template."""
        actions = []
        
        # Clone template action
        clone_url = reverse('admin:workflows_workflowtemplate_clone', args=[obj.pk])
        actions.append(f'<a href="{clone_url}" class="button">Clone</a>')
        
        # Export template action
        export_url = reverse('admin:workflows_workflowtemplate_export', args=[obj.pk])
        actions.append(f'<a href="{export_url}" class="button">Export</a>')
        
        # Preview template action
        preview_url = reverse('admin:workflows_workflowtemplate_preview', args=[obj.pk])
        actions.append(f'<a href="{preview_url}" class="button">Preview</a>')
        
        return mark_safe(' '.join(actions))
    template_actions.short_description = _('Actions')
    
    def get_queryset(self, request):
        """Optimize queryset with annotations and select_related."""
        return super().get_queryset(request).select_related(
            'created_by', 'initial_state'
        ).prefetch_related('final_states', 'workflow_executions')
    
    def save_model(self, request, obj: WorkflowTemplate, form, change: bool) -> None:
        """Override save to add audit trail."""
        if not change:
            obj.created_by = request.user
        
        try:
            with transaction.atomic():
                super().save_model(request, obj, form, change)
                
                # Log the action
                action = 'updated' if change else 'created'
                messages.success(
                    request, 
                    f'Workflow template "{obj.name}" was {action} successfully.'
                )
                
        except ValidationError as e:
            messages.error(request, f'Validation error: {e.message}')
        except Exception as e:
            messages.error(request, f'Error saving template: {str(e)}')


@admin.register(WorkflowRule)
class WorkflowRuleAdmin(ModelAdmin):
    """Admin interface for workflow rules."""
    
    list_display = (
        'name', 'rule_type', 'template', 'priority', 'is_active', 
        'execution_count', 'last_executed'
    )
    list_filter = ('rule_type', 'is_active', 'template', 'created_at')
    search_fields = ('name', 'description', 'template__name')
    ordering = ('-priority', 'name')
    readonly_fields = ('created_at', 'updated_at', 'execution_count', 'last_executed')
    
    fieldsets = (
        (_('Rule Information'), {
            'fields': ('name', 'description', 'rule_type', 'template')
        }),
        (_('Execution Settings'), {
            'fields': ('priority', 'is_active', 'trigger_events', 'execution_limit'),
            'classes': ('collapse',)
        }),
        (_('Conditions & Actions'), {
            'fields': ('conditions', 'actions', 'metadata'),
            'classes': ('collapse',)
        }),
        (_('Statistics'), {
            'fields': ('execution_count', 'last_executed', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    inlines = [WorkflowConditionInline, WorkflowActionInline]
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('template')


@admin.register(WorkflowState)
class WorkflowStateAdmin(ModelAdmin):
    """Admin interface for workflow states."""
    
    list_display = (
        'name', 'template', 'state_type', 'is_initial', 'is_final', 
        'transition_count', 'color_display'
    )
    list_filter = ('state_type', 'is_initial', 'is_final', 'template')
    search_fields = ('name', 'description', 'template__name')
    ordering = ('template', 'display_order', 'name')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (_('State Information'), {
            'fields': ('name', 'description', 'template', 'state_type')
        }),
        (_('State Properties'), {
            'fields': ('is_initial', 'is_final', 'display_order', 'color'),
            'classes': ('collapse',)
        }),
        (_('Permissions & Actions'), {
            'fields': ('required_permissions', 'entry_actions', 'exit_actions'),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    inlines = [WorkflowTransitionInline]
    
    def transition_count(self, obj: WorkflowState) -> int:
        """Display number of outgoing transitions."""
        return obj.outgoing_transitions.count()
    transition_count.short_description = _('Outgoing Transitions')
    
    def color_display(self, obj: WorkflowState) -> str:
        """Display state color as a colored box."""
        if obj.color:
            return format_html(
                '<div style="width: 20px; height: 20px; '
                'background-color: {}; border: 1px solid #ccc;"></div>',
                obj.color
            )
        return '-'
    color_display.short_description = _('Color')
    
    def get_queryset(self, request):
        """Optimize queryset with select_related and prefetch_related."""
        return super().get_queryset(request).select_related(
            'template'
        ).prefetch_related('outgoing_transitions')


@admin.register(WorkflowTransition)
class WorkflowTransitionAdmin(ModelAdmin):
    """Admin interface for workflow transitions."""
    
    list_display = (
        'transition_name', 'from_state', 'to_state', 'is_automatic', 
        'permission_required', 'usage_count'
    )
    list_filter = ('is_automatic', 'from_state__template', 'created_at')
    search_fields = ('name', 'from_state__name', 'to_state__name', 'description')
    ordering = ('from_state__template', 'from_state', 'display_order')
    readonly_fields = ('created_at', 'updated_at', 'usage_count')
    
    fieldsets = (
        (_('Transition Information'), {
            'fields': ('name', 'description', 'from_state', 'to_state')
        }),
        (_('Execution Settings'), {
            'fields': ('is_automatic', 'permission_required', 'display_order'),
            'classes': ('collapse',)
        }),
        (_('Conditions & Actions'), {
            'fields': ('condition', 'action', 'trigger_condition'),
            'classes': ('collapse',)
        }),
        (_('Statistics'), {
            'fields': ('usage_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def transition_name(self, obj: WorkflowTransition) -> str:
        """Display transition name or generate one."""
        return obj.name or f'{obj.from_state} → {obj.to_state}'
    transition_name.short_description = _('Transition')
    transition_name.admin_order_field = 'name'
    
    def usage_count(self, obj: WorkflowTransition) -> int:
        """Display how many times this transition was used."""
        return obj.workflow_executions.count()
    usage_count.short_description = _('Usage Count')
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related(
            'from_state', 'to_state', 'condition', 'action',
            'from_state__template'
        )


@admin.register(WorkflowAssignment)
class WorkflowAssignmentAdmin(ModelAdmin):
    """Admin interface for workflow assignments."""
    
    list_display = (
        'workflow_execution', 'assigned_to', 'assigned_by', 'assignment_type',
        'status', 'assigned_at', 'completed_at'
    )
    list_filter = ('assignment_type', 'status', 'assigned_at', 'completed_at')
    search_fields = (
        'workflow_execution__task__title', 'assigned_to__username',
        'assigned_by__username'
    )
    ordering = ('-assigned_at',)
    readonly_fields = ('assigned_at', 'completed_at', 'metadata')
    
    fieldsets = (
        (_('Assignment Information'), {
            'fields': ('workflow_execution', 'assigned_to', 'assigned_by', 'assignment_type')
        }),
        (_('Status & Timing'), {
            'fields': ('status', 'assigned_at', 'due_date', 'completed_at'),
            'classes': ('collapse',)
        }),
        (_('Additional Information'), {
            'fields': ('notes', 'metadata'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related(
            'workflow_execution', 'assigned_to', 'assigned_by',
            'workflow_execution__task'
        )


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(ModelAdmin):
    """Admin interface for workflow executions."""
    
    list_display = (
        'execution_id', 'template', 'task', 'current_state', 'status',
        'progress_percentage', 'started_at', 'completed_at'
    )
    list_filter = ('status', 'template', 'current_state', 'started_at')
    search_fields = ('task__title', 'template__name', 'execution_id')
    ordering = ('-started_at',)
    readonly_fields = (
        'execution_id', 'started_at', 'completed_at', 'duration',
        'progress_percentage', 'execution_log'
    )
    
    fieldsets = (
        (_('Execution Information'), {
            'fields': ('execution_id', 'template', 'task', 'initiated_by')
        }),
        (_('Current Status'), {
            'fields': ('current_state', 'status', 'progress_percentage'),
            'classes': ('collapse',)
        }),
        (_('Timing Information'), {
            'fields': ('started_at', 'completed_at', 'duration'),
            'classes': ('collapse',)
        }),
        (_('Execution Details'), {
            'fields': ('variables', 'execution_log', 'error_details'),
            'classes': ('collapse',)
        })
    )
    
    def execution_id(self, obj: WorkflowExecution) -> str:
        """Display short execution ID."""
        return str(obj.id)[:8] if obj.id else '-'
    execution_id.short_description = _('Execution ID')
    
    def progress_percentage(self, obj: WorkflowExecution) -> str:
        """Calculate and display progress percentage."""
        if not obj.template or not obj.current_state:
            return '0%'
        
        total_states = obj.template.workflow_states.count()
        if total_states == 0:
            return '0%'
        
        # Simple progress calculation based on state order
        current_order = getattr(obj.current_state, 'display_order', 0)
        progress = min((current_order / total_states) * 100, 100)
        return f'{progress:.1f}%'
    progress_percentage.short_description = _('Progress')
    
    def duration(self, obj: WorkflowExecution) -> Optional[str]:
        """Calculate execution duration."""
        if obj.started_at and obj.completed_at:
            delta = obj.completed_at - obj.started_at
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            if days > 0:
                return f'{days}d {hours}h {minutes}m'
            elif hours > 0:
                return f'{hours}h {minutes}m'
            else:
                return f'{minutes}m'
        return None
    duration.short_description = _('Duration')
    
    def get_queryset(self, request):
        """Optimize queryset with select_related and prefetch_related."""
        return super().get_queryset(request).select_related(
            'template', 'task', 'current_state', 'initiated_by'
        ).prefetch_related('workflow_assignments')
    
    actions = ['restart_execution', 'force_complete_execution']
    
    def restart_execution(self, request, queryset) -> None:
        """Custom action to restart selected executions."""
        updated_count = 0
        for execution in queryset:
            if execution.status in ['completed', 'failed', 'cancelled']:
                execution.status = 'pending'
                execution.current_state = execution.template.initial_state
                execution.completed_at = None
                execution.error_details = None
                execution.save()
                updated_count += 1
        
        messages.success(
            request,
            f'Successfully restarted {updated_count} workflow execution(s).'
        )
    restart_execution.short_description = _('Restart selected executions')
    
    def force_complete_execution(self, request, queryset) -> None:
        """Custom action to force complete selected executions."""
        updated_count = 0
        for execution in queryset:
            if execution.status in ['running', 'pending']:
                final_states = execution.template.final_states.all()
                if final_states:
                    execution.current_state = final_states.first()
                    execution.status = 'completed'
                    execution.completed_at = timezone.now()
                    execution.save()
                    updated_count += 1
        
        messages.success(
            request,
            f'Successfully completed {updated_count} workflow execution(s).'
        )
    force_complete_execution.short_description = _('Force complete selected executions')


# Register additional models with basic admin interfaces
@admin.register(WorkflowCondition)
class WorkflowConditionAdmin(ModelAdmin):
    """Basic admin for workflow conditions."""
    
    list_display = ('rule', 'condition_type', 'field_name', 'operator', 'is_active')
    list_filter = ('condition_type', 'operator', 'is_active')
    search_fields = ('rule__name', 'field_name')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('rule')


@admin.register(WorkflowAction)
class WorkflowActionAdmin(ModelAdmin):
    """Basic admin for workflow actions."""
    
    list_display = ('rule', 'action_type', 'target_field', 'execution_order', 'is_active')
    list_filter = ('action_type', 'is_active')
    search_fields = ('rule__name', 'target_field')
    ordering = ('rule', 'execution_order')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('rule')


@admin.register(WorkflowVariable)
class WorkflowVariableAdmin(ModelAdmin):
    """Basic admin for workflow variables."""
    
    list_display = ('name', 'template', 'variable_type', 'is_required', 'default_value')
    list_filter = ('variable_type', 'is_required')
    search_fields = ('name', 'template__name', 'description')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('template')


# Admin site customization
admin.site.site_header = _('Task Management System - Workflow Administration')
admin.site.site_title = _('Workflow Admin')
admin.site.index_title = _('Workflow Management Dashboard')
