"""
Workflow serializers for enterprise task management system.

This module provides comprehensive serialization for workflow-related models
including workflow definitions, states, transitions, and automation rules.
Implements advanced validation, nested serialization, and performance optimizations.
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal

from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.tasks.models import Task, TaskTemplate
from apps.users.models import Team
from .models import (
    Workflow,
    WorkflowState,
    WorkflowTransition,
    WorkflowRule,
    WorkflowExecution,
    WorkflowTemplate,
    TaskWorkflow,
    AutomationRule,
    EscalationRule,
)
from .choices import (
    WorkflowStatus,
    TransitionType,
    RuleType,
    ConditionOperator,
    ActionType,
)

User = get_user_model()


class WorkflowStateSerializer(serializers.ModelSerializer):
    """Serializer for workflow states with comprehensive validation."""
    
    task_count = serializers.SerializerMethodField()
    is_terminal = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkflowState
        fields = [
            'id', 'name', 'slug', 'description', 'color',
            'is_initial', 'is_final', 'order', 'metadata',
            'task_count', 'is_terminal', 'allowed_transitions',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'slug': {'validators': []},  # Custom validation in validate()
            'color': {'help_text': 'Hex color code for UI representation'},
            'metadata': {'help_text': 'Additional state configuration'},
        }

    def get_task_count(self, obj: WorkflowState) -> int:
        """Get number of tasks currently in this state."""
        if hasattr(obj, 'prefetched_task_count'):
            return obj.prefetched_task_count
        return obj.tasks.filter(is_archived=False).count()

    def get_is_terminal(self, obj: WorkflowState) -> bool:
        """Check if this is a terminal state (no outgoing transitions)."""
        return obj.is_final or not obj.outgoing_transitions.exists()

    def get_allowed_transitions(self, obj: WorkflowState) -> List[str]:
        """Get list of allowed transition names from this state."""
        return list(
            obj.outgoing_transitions.values_list('name', flat=True)
        )

    def validate_slug(self, value: str) -> str:
        """Validate state slug uniqueness within workflow."""
        workflow = self.context.get('workflow')
        if workflow and WorkflowState.objects.filter(
            workflow=workflow, slug=value
        ).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise ValidationError(_('State slug must be unique within workflow.'))
        return value

    def validate_color(self, value: str) -> str:
        """Validate hex color format."""
        if value and not value.startswith('#'):
            value = f'#{value}'
        if len(value) not in [4, 7] or not all(c in '0123456789ABCDEFabcdef' for c in value[1:]):
            raise ValidationError(_('Invalid hex color format.'))
        return value.upper()


class WorkflowTransitionSerializer(serializers.ModelSerializer):
    """Serializer for workflow transitions with rule validation."""
    
    from_state_name = serializers.CharField(source='from_state.name', read_only=True)
    to_state_name = serializers.CharField(source='to_state.name', read_only=True)
    conditions_count = serializers.SerializerMethodField()
    actions_count = serializers.SerializerMethodField()
    usage_count = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowTransition
        fields = [
            'id', 'name', 'slug', 'description', 'from_state', 'to_state',
            'from_state_name', 'to_state_name', 'transition_type',
            'conditions', 'actions', 'permissions_required',
            'conditions_count', 'actions_count', 'usage_count',
            'is_active', 'order', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'conditions': {'help_text': 'JSON conditions for transition execution'},
            'actions': {'help_text': 'JSON actions to execute on transition'},
            'permissions_required': {'help_text': 'Required permissions for transition'},
        }

    def get_conditions_count(self, obj: WorkflowTransition) -> int:
        """Get number of conditions for this transition."""
        return len(obj.conditions.get('rules', [])) if obj.conditions else 0

    def get_actions_count(self, obj: WorkflowTransition) -> int:
        """Get number of actions for this transition."""
        return len(obj.actions.get('actions', [])) if obj.actions else 0

    def get_usage_count(self, obj: WorkflowTransition) -> int:
        """Get number of times this transition has been used."""
        if hasattr(obj, 'prefetched_usage_count'):
            return obj.prefetched_usage_count
        return obj.workflow_executions.count()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Comprehensive transition validation."""
        from_state = attrs.get('from_state')
        to_state = attrs.get('to_state')
        
        if from_state and to_state:
            # Prevent self-loops unless explicitly allowed
            if from_state == to_state and attrs.get('transition_type') != TransitionType.LOOP:
                raise ValidationError(_('Self-transitions require LOOP type.'))
            
            # Validate states belong to same workflow
            if from_state.workflow != to_state.workflow:
                raise ValidationError(_('States must belong to the same workflow.'))
        
        # Validate conditions JSON structure
        conditions = attrs.get('conditions')
        if conditions:
            self._validate_conditions_structure(conditions)
        
        # Validate actions JSON structure
        actions = attrs.get('actions')
        if actions:
            self._validate_actions_structure(actions)
        
        return attrs

    def _validate_conditions_structure(self, conditions: Dict[str, Any]) -> None:
        """Validate conditions JSON structure."""
        if not isinstance(conditions, dict):
            raise ValidationError(_('Conditions must be a valid JSON object.'))
        
        rules = conditions.get('rules', [])
        if not isinstance(rules, list):
            raise ValidationError(_('Conditions rules must be a list.'))
        
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValidationError(_('Each condition rule must be an object.'))
            
            required_fields = ['field', 'operator', 'value']
            if not all(field in rule for field in required_fields):
                raise ValidationError(
                    _('Each condition rule must have: field, operator, value')
                )

    def _validate_actions_structure(self, actions: Dict[str, Any]) -> None:
        """Validate actions JSON structure."""
        if not isinstance(actions, dict):
            raise ValidationError(_('Actions must be a valid JSON object.'))
        
        action_list = actions.get('actions', [])
        if not isinstance(action_list, list):
            raise ValidationError(_('Actions must contain an actions list.'))
        
        for action in action_list:
            if not isinstance(action, dict):
                raise ValidationError(_('Each action must be an object.'))
            
            if 'type' not in action:
                raise ValidationError(_('Each action must have a type.'))


class WorkflowRuleSerializer(serializers.ModelSerializer):
    """Serializer for workflow automation rules."""
    
    trigger_events = serializers.ListField(
        child=serializers.CharField(),
        help_text='List of events that trigger this rule'
    )
    conditions_summary = serializers.SerializerMethodField()
    actions_summary = serializers.SerializerMethodField()
    execution_count = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowRule
        fields = [
            'id', 'name', 'description', 'rule_type', 'trigger_events',
            'conditions', 'actions', 'priority', 'is_active',
            'conditions_summary', 'actions_summary', 'execution_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_conditions_summary(self, obj: WorkflowRule) -> str:
        """Generate human-readable conditions summary."""
        if not obj.conditions:
            return 'No conditions'
        
        rules = obj.conditions.get('rules', [])
        if not rules:
            return 'No conditions'
        
        return f"{len(rules)} condition(s) defined"

    def get_actions_summary(self, obj: WorkflowRule) -> str:
        """Generate human-readable actions summary."""
        if not obj.actions:
            return 'No actions'
        
        actions = obj.actions.get('actions', [])
        if not actions:
            return 'No actions'
        
        action_types = [action.get('type', 'unknown') for action in actions]
        return f"{len(actions)} action(s): {', '.join(set(action_types))}"

    def get_execution_count(self, obj: WorkflowRule) -> int:
        """Get rule execution count."""
        if hasattr(obj, 'prefetched_execution_count'):
            return obj.prefetched_execution_count
        return obj.rule_executions.count()

    def validate_trigger_events(self, value: List[str]) -> List[str]:
        """Validate trigger events."""
        if not value:
            raise ValidationError(_('At least one trigger event is required.'))
        
        valid_events = [
            'task.created', 'task.updated', 'task.assigned',
            'task.completed', 'task.overdue', 'task.escalated'
        ]
        
        invalid_events = [event for event in value if event not in valid_events]
        if invalid_events:
            raise ValidationError(
                _f'Invalid trigger events: {", ".join(invalid_events)}'
            )
        
        return value


class WorkflowExecutionSerializer(serializers.ModelSerializer):
    """Serializer for workflow execution tracking."""
    
    task_title = serializers.CharField(source='task.title', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    from_state_name = serializers.CharField(source='from_state.name', read_only=True)
    to_state_name = serializers.CharField(source='to_state.name', read_only=True)
    transition_name = serializers.CharField(source='transition.name', read_only=True)
    executed_by_username = serializers.CharField(source='executed_by.username', read_only=True)
    duration = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowExecution
        fields = [
            'id', 'task', 'task_title', 'workflow', 'workflow_name',
            'from_state', 'from_state_name', 'to_state', 'to_state_name',
            'transition', 'transition_name', 'executed_by', 'executed_by_username',
            'execution_data', 'duration', 'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_duration(self, obj: WorkflowExecution) -> Optional[float]:
        """Calculate execution duration in seconds."""
        if hasattr(obj, 'execution_data') and obj.execution_data:
            start_time = obj.execution_data.get('start_time')
            end_time = obj.execution_data.get('end_time')
            if start_time and end_time:
                return end_time - start_time
        return None


class WorkflowTemplateSerializer(serializers.ModelSerializer):
    """Serializer for workflow templates with nested components."""
    
    states = WorkflowStateSerializer(many=True, read_only=True)
    transitions = WorkflowTransitionSerializer(many=True, read_only=True)
    usage_count = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkflowTemplate
        fields = [
            'id', 'name', 'description', 'category', 'industry',
            'states', 'transitions', 'template_data',
            'is_public', 'usage_count', 'created_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_usage_count(self, obj: WorkflowTemplate) -> int:
        """Get template usage count."""
        if hasattr(obj, 'prefetched_usage_count'):
            return obj.prefetched_usage_count
        return obj.workflows.count()


class WorkflowSerializer(serializers.ModelSerializer):
    """
    Comprehensive workflow serializer with nested relationships.
    
    Handles complex workflow creation, updates, and state management
    with proper validation and performance optimizations.
    """
    
    states = WorkflowStateSerializer(many=True, read_only=True)
    transitions = WorkflowTransitionSerializer(many=True, read_only=True)
    rules = WorkflowRuleSerializer(many=True, read_only=True)
    
    # Computed fields
    total_tasks = serializers.SerializerMethodField()
    active_tasks = serializers.SerializerMethodField()
    completion_rate = serializers.SerializerMethodField()
    average_completion_time = serializers.SerializerMethodField()
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    
    # Nested write operations
    states_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text='List of states to create/update'
    )
    transitions_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text='List of transitions to create/update'
    )

    class Meta:
        model = Workflow
        fields = [
            'id', 'name', 'slug', 'description', 'workflow_type',
            'status', 'is_default', 'version', 'metadata',
            'states', 'transitions', 'rules',
            'total_tasks', 'active_tasks', 'completion_rate',
            'average_completion_time', 'created_by', 'created_by_username',
            'states_data', 'transitions_data',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'slug': {'validators': []},  # Custom validation
            'version': {'help_text': 'Semantic version (e.g., 1.0.0)'},
            'metadata': {'help_text': 'Additional workflow configuration'},
        }

    def get_total_tasks(self, obj: Workflow) -> int:
        """Get total number of tasks using this workflow."""
        if hasattr(obj, 'prefetched_total_tasks'):
            return obj.prefetched_total_tasks
        return obj.task_workflows.count()

    def get_active_tasks(self, obj: Workflow) -> int:
        """Get number of active (non-archived) tasks."""
        if hasattr(obj, 'prefetched_active_tasks'):
            return obj.prefetched_active_tasks
        return obj.task_workflows.filter(task__is_archived=False).count()

    def get_completion_rate(self, obj: Workflow) -> Optional[float]:
        """Calculate workflow completion rate."""
        if hasattr(obj, 'prefetched_completion_stats'):
            stats = obj.prefetched_completion_stats
            total = stats.get('total', 0)
            completed = stats.get('completed', 0)
            return (completed / total * 100) if total > 0 else None
        
        total_tasks = self.get_total_tasks(obj)
        if total_tasks == 0:
            return None
        
        completed_tasks = obj.task_workflows.filter(
            current_state__is_final=True
        ).count()
        
        return (completed_tasks / total_tasks) * 100

    def get_average_completion_time(self, obj: Workflow) -> Optional[float]:
        """Calculate average task completion time in hours."""
        if hasattr(obj, 'prefetched_avg_completion_time'):
            return obj.prefetched_avg_completion_time
        
        # This would require complex aggregation - simplified for demo
        return None

    def validate_slug(self, value: str) -> str:
        """Validate workflow slug uniqueness."""
        if Workflow.objects.filter(slug=value).exclude(
            pk=self.instance.pk if self.instance else None
        ).exists():
            raise ValidationError(_('Workflow with this slug already exists.'))
        return value

    def validate_version(self, value: str) -> str:
        """Validate semantic version format."""
        import re
        version_pattern = r'^\d+\.\d+\.\d+(?:-[a-zA-Z0-9\-\.]+)?$'
        if not re.match(version_pattern, value):
            raise ValidationError(_('Invalid semantic version format (e.g., 1.0.0).'))
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Comprehensive workflow validation."""
        # Validate workflow type and status combination
        workflow_type = attrs.get('workflow_type')
        status = attrs.get('status')
        
        if workflow_type == 'template' and status not in ['draft', 'published']:
            raise ValidationError(
                _('Template workflows can only have draft or published status.')
            )
        
        # Validate states data if provided
        states_data = attrs.get('states_data', [])
        if states_data:
            self._validate_states_data(states_data)
        
        # Validate transitions data if provided
        transitions_data = attrs.get('transitions_data', [])
        if transitions_data:
            self._validate_transitions_data(transitions_data, states_data)
        
        return attrs

    def _validate_states_data(self, states_data: List[Dict[str, Any]]) -> None:
        """Validate states data structure and business rules."""
        if not states_data:
            raise ValidationError(_('At least one state is required.'))
        
        state_slugs = [state.get('slug') for state in states_data if state.get('slug')]
        if len(state_slugs) != len(set(state_slugs)):
            raise ValidationError(_('State slugs must be unique within workflow.'))
        
        initial_states = [state for state in states_data if state.get('is_initial')]
        if len(initial_states) != 1:
            raise ValidationError(_('Exactly one initial state is required.'))
        
        final_states = [state for state in states_data if state.get('is_final')]
        if not final_states:
            raise ValidationError(_('At least one final state is required.'))

    def _validate_transitions_data(
        self, 
        transitions_data: List[Dict[str, Any]], 
        states_data: List[Dict[str, Any]]
    ) -> None:
        """Validate transitions data and state references."""
        if not transitions_data:
            return  # Transitions are optional during creation
        
        state_slugs = {state.get('slug') for state in states_data if state.get('slug')}
        
        for transition in transitions_data:
            from_state_slug = transition.get('from_state_slug')
            to_state_slug = transition.get('to_state_slug')
            
            if from_state_slug and from_state_slug not in state_slugs:
                raise ValidationError(
                    _(f'Invalid from_state reference: {from_state_slug}')
                )
            
            if to_state_slug and to_state_slug not in state_slugs:
                raise ValidationError(
                    _(f'Invalid to_state reference: {to_state_slug}')
                )

    @transaction.atomic
    def create(self, validated_data: Dict[str, Any]) -> Workflow:
        """Create workflow with nested states and transitions."""
        states_data = validated_data.pop('states_data', [])
        transitions_data = validated_data.pop('transitions_data', [])
        
        # Set created_by from request user
        validated_data['created_by'] = self.context['request'].user
        
        workflow = Workflow.objects.create(**validated_data)
        
        # Create states
        state_mapping = {}
        if states_data:
            for state_data in states_data:
                state = WorkflowState.objects.create(
                    workflow=workflow,
                    **state_data
                )
                state_mapping[state_data.get('slug')] = state
        
        # Create transitions
        if transitions_data:
            for transition_data in transitions_data:
                from_state_slug = transition_data.pop('from_state_slug', None)
                to_state_slug = transition_data.pop('to_state_slug', None)
                
                if from_state_slug in state_mapping:
                    transition_data['from_state'] = state_mapping[from_state_slug]
                if to_state_slug in state_mapping:
                    transition_data['to_state'] = state_mapping[to_state_slug]
                
                WorkflowTransition.objects.create(
                    workflow=workflow,
                    **transition_data
                )
        
        return workflow

    @transaction.atomic
    def update(self, instance: Workflow, validated_data: Dict[str, Any]) -> Workflow:
        """Update workflow with support for nested operations."""
        states_data = validated_data.pop('states_data', None)
        transitions_data = validated_data.pop('transitions_data', None)
        
        # Update workflow fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle states update (simplified - would need more complex logic for production)
        if states_data is not None:
            # This is a simplified implementation
            # Production code would handle partial updates, deletions, etc.
            pass
        
        # Handle transitions update
        if transitions_data is not None:
            # This is a simplified implementation
            pass
        
        return instance


class TaskWorkflowSerializer(serializers.ModelSerializer):
    """Serializer for task-workflow associations."""
    
    task_title = serializers.CharField(source='task.title', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    current_state_name = serializers.CharField(source='current_state.name', read_only=True)
    time_in_current_state = serializers.SerializerMethodField()
    available_transitions = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskWorkflow
        fields = [
            'id', 'task', 'task_title', 'workflow', 'workflow_name',
            'current_state', 'current_state_name', 'started_at',
            'time_in_current_state', 'available_transitions',
            'workflow_data', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_time_in_current_state(self, obj: TaskWorkflow) -> Optional[int]:
        """Calculate time spent in current state (in hours)."""
        if not obj.started_at:
            return None
        
        from django.utils import timezone
        delta = timezone.now() - obj.started_at
        return int(delta.total_seconds() // 3600)

    def get_available_transitions(self, obj: TaskWorkflow) -> List[Dict[str, Any]]:
        """Get available transitions from current state."""
        if not obj.current_state:
            return []
        
        transitions = obj.current_state.outgoing_transitions.filter(is_active=True)
        return [
            {
                'id': transition.id,
                'name': transition.name,
                'to_state': transition.to_state.name,
                'requires_permission': bool(transition.permissions_required),
            }
            for transition in transitions
        ]


class AutomationRuleSerializer(serializers.ModelSerializer):
    """Serializer for workflow automation rules."""
    
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    execution_count = serializers.SerializerMethodField()
    last_execution = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = AutomationRule
        fields = [
            'id', 'name', 'description', 'workflow', 'workflow_name',
            'rule_type', 'trigger_conditions', 'actions',
            'is_active', 'priority', 'execution_count',
            'last_execution', 'success_rate',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_execution_count(self, obj: AutomationRule) -> int:
        """Get rule execution count."""
        if hasattr(obj, 'prefetched_execution_count'):
            return obj.prefetched_execution_count
        return obj.rule_executions.count()

    def get_last_execution(self, obj: AutomationRule) -> Optional[str]:
        """Get last execution timestamp."""
        if hasattr(obj, 'prefetched_last_execution'):
            return obj.prefetched_last_execution
        
        last_execution = obj.rule_executions.order_by('-created_at').first()
        return last_execution.created_at.isoformat() if last_execution else None

    def get_success_rate(self, obj: AutomationRule) -> Optional[float]:
        """Calculate rule success rate."""
        if hasattr(obj, 'prefetched_success_stats'):
            stats = obj.prefetched_success_stats
            total = stats.get('total', 0)
            successful = stats.get('successful', 0)
            return (successful / total * 100) if total > 0 else None
        
        return None  # Would require complex aggregation


class EscalationRuleSerializer(serializers.ModelSerializer):
    """Serializer for SLA escalation rules."""
    
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    escalation_count = serializers.SerializerMethodField()

    class Meta:
        model = EscalationRule
        fields = [
            'id', 'name', 'description', 'workflow', 'workflow_name',
            'trigger_after_hours', 'escalate_to', 'notification_template',
            'is_active', 'escalation_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_escalation_count(self, obj: EscalationRule) -> int:
        """Get escalation execution count."""
        if hasattr(obj, 'prefetched_escalation_count'):
            return obj.prefetched_escalation_count
        return obj.escalations.count()

    def validate_trigger_after_hours(self, value: Decimal) -> Decimal:
        """Validate escalation trigger time."""
        if value <= 0:
            raise ValidationError(_('Trigger time must be positive.'))
        if value > Decimal('168'):  # 1 week
            raise ValidationError(_('Trigger time cannot exceed 168 hours (1 week).'))
        return value
