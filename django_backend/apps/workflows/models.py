"""
Workflow models for the Enterprise Task Management System.

This module defines models for workflow management including:
- Workflow definitions and templates
- Task status transitions and validation
- Automation rules and conditions
- Workflow executions and state tracking
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models import JSONField, Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel, SoftDeleteModel

User = get_user_model()


class WorkflowManager(models.Manager):
    """Custom manager for Workflow model with optimized queries."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related(
            'created_by', 'updated_by'
        ).prefetch_related('states', 'transitions', 'rules')
    
    def active(self) -> QuerySet:
        """Return only active workflows."""
        return self.get_queryset().filter(is_active=True)
    
    def for_user(self, user: User) -> QuerySet:
        """Return workflows accessible by the given user."""
        return self.get_queryset().filter(
            Q(created_by=user) | 
            Q(is_public=True) |
            Q(teams__members=user)
        ).distinct()


class Workflow(TimeStampedModel, SoftDeleteModel):
    """
    Defines a workflow template with states, transitions, and automation rules.
    
    A workflow represents a business process that tasks can follow,
    with defined states, allowed transitions, and automation rules.
    """
    
    class WorkflowType(models.TextChoices):
        TASK_LIFECYCLE = 'task_lifecycle', _('Task Lifecycle')
        APPROVAL_PROCESS = 'approval_process', _('Approval Process')
        CUSTOM_WORKFLOW = 'custom_workflow', _('Custom Workflow')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True)
    workflow_type = models.CharField(
        max_length=20,
        choices=WorkflowType.choices,
        default=WorkflowType.TASK_LIFECYCLE,
        db_index=True
    )
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True, db_index=True)
    is_public = models.BooleanField(default=False, db_index=True)
    is_default = models.BooleanField(default=False, db_index=True)
    
    # Workflow configuration
    configuration = JSONField(default=dict, blank=True)
    metadata = JSONField(default=dict, blank=True)
    
    # Relationships
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_workflows'
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_workflows'
    )
    teams = models.ManyToManyField(
        'users.Team',
        blank=True,
        related_name='workflows'
    )
    
    objects = WorkflowManager()
    
    class Meta:
        db_table = 'workflows_workflow'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workflow_type', 'is_active']),
            models.Index(fields=['created_by', 'is_active']),
            models.Index(fields=['is_default', 'workflow_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'version'],
                name='unique_workflow_name_version'
            )
        ]
    
    def __str__(self) -> str:
        return f"{self.name} v{self.version}"
    
    def clean(self) -> None:
        """Validate workflow configuration."""
        super().clean()
        if self.is_default:
            # Ensure only one default workflow per type
            existing_default = Workflow.objects.filter(
                workflow_type=self.workflow_type,
                is_default=True
            ).exclude(pk=self.pk).first()
            
            if existing_default:
                raise ValidationError(
                    f"A default workflow already exists for {self.workflow_type}"
                )
    
    @property
    def initial_state(self) -> Optional['WorkflowState']:
        """Get the initial state of this workflow."""
        return self.states.filter(is_initial=True).first()
    
    @property
    def final_states(self) -> QuerySet:
        """Get all final states of this workflow."""
        return self.states.filter(is_final=True)
    
    def get_next_states(self, current_state: 'WorkflowState', user: User = None) -> QuerySet:
        """Get possible next states from the current state."""
        transitions = self.transitions.filter(
            from_state=current_state,
            is_active=True
        )
        
        if user:
            # Filter by user permissions if provided
            transitions = transitions.filter(
                Q(required_permissions__isnull=True) |
                Q(required_permissions__in=user.user_permissions.all()) |
                Q(required_roles__isnull=True) |
                Q(required_roles__in=user.groups.all())
            )
        
        return WorkflowState.objects.filter(
            id__in=transitions.values_list('to_state_id', flat=True)
        )
    
    def can_transition(self, from_state: 'WorkflowState', to_state: 'WorkflowState', 
                      user: User = None, context: Dict[str, Any] = None) -> bool:
        """Check if transition between states is allowed."""
        transition = self.transitions.filter(
            from_state=from_state,
            to_state=to_state,
            is_active=True
        ).first()
        
        if not transition:
            return False
        
        return transition.can_execute(user=user, context=context)


class WorkflowStateManager(models.Manager):
    """Custom manager for WorkflowState model."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related('workflow')
    
    def initial_states(self) -> QuerySet:
        """Return only initial states."""
        return self.get_queryset().filter(is_initial=True)
    
    def final_states(self) -> QuerySet:
        """Return only final states."""
        return self.get_queryset().filter(is_final=True)


class WorkflowState(TimeStampedModel):
    """
    Represents a state in a workflow.
    
    States define the possible statuses a task can have within a workflow.
    """
    
    class StateType(models.TextChoices):
        INITIAL = 'initial', _('Initial')
        INTERMEDIATE = 'intermediate', _('Intermediate')
        FINAL = 'final', _('Final')
        ERROR = 'error', _('Error')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='states'
    )
    name = models.CharField(max_length=100, db_index=True)
    display_name = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    state_type = models.CharField(
        max_length=20,
        choices=StateType.choices,
        default=StateType.INTERMEDIATE,
        db_index=True
    )
    color = models.CharField(max_length=7, default='#6c757d')  # Hex color
    icon = models.CharField(max_length=50, blank=True)
    order = models.PositiveIntegerField(default=0, db_index=True)
    
    # State configuration
    is_initial = models.BooleanField(default=False, db_index=True)
    is_final = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    
    # SLA and timing
    sla_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(8760)]  # 1 hour to 1 year
    )
    
    # State configuration and metadata
    configuration = JSONField(default=dict, blank=True)
    metadata = JSONField(default=dict, blank=True)
    
    objects = WorkflowStateManager()
    
    class Meta:
        db_table = 'workflows_state'
        ordering = ['workflow', 'order']
        indexes = [
            models.Index(fields=['workflow', 'is_active']),
            models.Index(fields=['workflow', 'state_type']),
            models.Index(fields=['is_initial', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'name'],
                name='unique_workflow_state_name'
            )
        ]
    
    def __str__(self) -> str:
        return f"{self.workflow.name}: {self.display_name or self.name}"
    
    def clean(self) -> None:
        """Validate state configuration."""
        super().clean()
        
        if self.is_initial and self.is_final:
            raise ValidationError("A state cannot be both initial and final")
        
        if self.is_initial:
            # Ensure only one initial state per workflow
            existing_initial = WorkflowState.objects.filter(
                workflow=self.workflow,
                is_initial=True
            ).exclude(pk=self.pk).first()
            
            if existing_initial:
                raise ValidationError(
                    f"Workflow already has an initial state: {existing_initial.name}"
                )
    
    def save(self, *args, **kwargs) -> None:
        """Override save to set display_name and validate."""
        if not self.display_name:
            self.display_name = self.name.replace('_', ' ').title()
        
        self.full_clean()
        super().save(*args, **kwargs)


class WorkflowTransitionManager(models.Manager):
    """Custom manager for WorkflowTransition model."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related(
            'workflow', 'from_state', 'to_state'
        ).prefetch_related('required_permissions', 'required_roles')
    
    def active(self) -> QuerySet:
        """Return only active transitions."""
        return self.get_queryset().filter(is_active=True)


class WorkflowTransition(TimeStampedModel):
    """
    Represents a transition between workflow states.
    
    Transitions define how tasks can move between states,
    including validation rules and required permissions.
    """
    
    class TriggerType(models.TextChoices):
        MANUAL = 'manual', _('Manual')
        AUTOMATIC = 'automatic', _('Automatic')
        TIME_BASED = 'time_based', _('Time Based')
        EVENT_DRIVEN = 'event_driven', _('Event Driven')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='transitions'
    )
    from_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.CASCADE,
        related_name='outgoing_transitions'
    )
    to_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.CASCADE,
        related_name='incoming_transitions'
    )
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    trigger_type = models.CharField(
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.MANUAL,
        db_index=True
    )
    
    # Transition configuration
    is_active = models.BooleanField(default=True, db_index=True)
    order = models.PositiveIntegerField(default=0)
    
    # Conditions and validation
    conditions = JSONField(default=dict, blank=True)
    validation_rules = JSONField(default=dict, blank=True)
    
    # Permissions and roles
    required_permissions = models.ManyToManyField(
        'auth.Permission',
        blank=True,
        related_name='workflow_transitions'
    )
    required_roles = models.ManyToManyField(
        'auth.Group',
        blank=True,
        related_name='workflow_transitions'
    )
    
    # Actions to perform on transition
    pre_actions = JSONField(default=list, blank=True)
    post_actions = JSONField(default=list, blank=True)
    
    # Metadata
    metadata = JSONField(default=dict, blank=True)
    
    objects = WorkflowTransitionManager()
    
    class Meta:
        db_table = 'workflows_transition'
        ordering = ['workflow', 'from_state', 'order']
        indexes = [
            models.Index(fields=['workflow', 'is_active']),
            models.Index(fields=['from_state', 'is_active']),
            models.Index(fields=['trigger_type', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'from_state', 'to_state'],
                name='unique_workflow_transition'
            )
        ]
    
    def __str__(self) -> str:
        return f"{self.from_state.name} → {self.to_state.name}"
    
    def clean(self) -> None:
        """Validate transition configuration."""
        super().clean()
        
        if self.from_state.workflow != self.workflow:
            raise ValidationError("From state must belong to the same workflow")
        
        if self.to_state.workflow != self.workflow:
            raise ValidationError("To state must belong to the same workflow")
        
        if self.from_state == self.to_state:
            raise ValidationError("From state and to state cannot be the same")
    
    def can_execute(self, user: User = None, context: Dict[str, Any] = None) -> bool:
        """Check if the transition can be executed by the user."""
        if not self.is_active:
            return False
        
        # Check permissions
        if user and self.required_permissions.exists():
            user_permissions = set(user.get_all_permissions())
            required_permissions = set(
                f"{perm.content_type.app_label}.{perm.codename}"
                for perm in self.required_permissions.all()
            )
            if not required_permissions.issubset(user_permissions):
                return False
        
        # Check roles
        if user and self.required_roles.exists():
            user_groups = set(user.groups.all())
            required_roles = set(self.required_roles.all())
            if not required_roles.issubset(user_groups):
                return False
        
        # Check custom conditions
        if self.conditions and context:
            return self._evaluate_conditions(context)
        
        return True
    
    def _evaluate_conditions(self, context: Dict[str, Any]) -> bool:
        """Evaluate custom conditions for the transition."""
        # This is a simplified implementation
        # In a real system, you might use a rule engine
        conditions = self.conditions
        
        for condition_key, condition_value in conditions.items():
            if condition_key not in context:
                return False
            
            context_value = context[condition_key]
            
            # Simple equality check
            if isinstance(condition_value, dict):
                operator = condition_value.get('operator', 'eq')
                value = condition_value.get('value')
                
                if operator == 'eq' and context_value != value:
                    return False
                elif operator == 'ne' and context_value == value:
                    return False
                elif operator == 'gt' and context_value <= value:
                    return False
                elif operator == 'lt' and context_value >= value:
                    return False
                elif operator == 'in' and context_value not in value:
                    return False
            else:
                if context_value != condition_value:
                    return False
        
        return True


class WorkflowRuleManager(models.Manager):
    """Custom manager for WorkflowRule model."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related('workflow')
    
    def active(self) -> QuerySet:
        """Return only active rules."""
        return self.get_queryset().filter(is_active=True)
    
    def for_trigger(self, trigger: str) -> QuerySet:
        """Return rules for a specific trigger."""
        return self.active().filter(trigger_event=trigger)


class WorkflowRule(TimeStampedModel):
    """
    Defines automation rules for workflows.
    
    Rules specify when and how to automatically perform actions
    based on workflow events and conditions.
    """
    
    class TriggerEvent(models.TextChoices):
        TASK_CREATED = 'task_created', _('Task Created')
        TASK_UPDATED = 'task_updated', _('Task Updated')
        STATE_ENTERED = 'state_entered', _('State Entered')
        STATE_EXITED = 'state_exited', _('State Exited')
        SLA_BREACHED = 'sla_breached', _('SLA Breached')
        DUE_DATE_APPROACHING = 'due_date_approaching', _('Due Date Approaching')
        ASSIGNMENT_CHANGED = 'assignment_changed', _('Assignment Changed')
        PRIORITY_CHANGED = 'priority_changed', _('Priority Changed')
    
    class ActionType(models.TextChoices):
        ASSIGN_TASK = 'assign_task', _('Assign Task')
        CHANGE_PRIORITY = 'change_priority', _('Change Priority')
        SEND_NOTIFICATION = 'send_notification', _('Send Notification')
        CREATE_SUBTASK = 'create_subtask', _('Create Subtask')
        ESCALATE = 'escalate', _('Escalate')
        SET_METADATA = 'set_metadata', _('Set Metadata')
        TRANSITION_STATE = 'transition_state', _('Transition State')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='rules'
    )
    
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True)
    
    # Rule configuration
    trigger_event = models.CharField(
        max_length=30,
        choices=TriggerEvent.choices,
        db_index=True
    )
    conditions = JSONField(default=dict, blank=True)
    actions = JSONField(default=list, blank=True)
    
    # Rule behavior
    is_active = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1), MaxValueValidator(1000)]
    )
    
    # Execution limits
    max_executions = models.PositiveIntegerField(null=True, blank=True)
    execution_count = models.PositiveIntegerField(default=0)
    last_executed_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    metadata = JSONField(default=dict, blank=True)
    
    objects = WorkflowRuleManager()
    
    class Meta:
        db_table = 'workflows_rule'
        ordering = ['workflow', 'priority', 'name']
        indexes = [
            models.Index(fields=['workflow', 'trigger_event', 'is_active']),
            models.Index(fields=['trigger_event', 'is_active']),
            models.Index(fields=['priority', 'is_active']),
        ]
    
    def __str__(self) -> str:
        return f"{self.workflow.name}: {self.name}"
    
    @property
    def can_execute(self) -> bool:
        """Check if the rule can be executed."""
        if not self.is_active:
            return False
        
        if self.max_executions and self.execution_count >= self.max_executions:
            return False
        
        return True
    
    def execute(self, context: Dict[str, Any]) -> bool:
        """Execute the rule if conditions are met."""
        if not self.can_execute:
            return False
        
        if not self._evaluate_conditions(context):
            return False
        
        try:
            with transaction.atomic():
                self._execute_actions(context)
                self.execution_count += 1
                self.last_executed_at = timezone.now()
                self.save(update_fields=['execution_count', 'last_executed_at'])
                return True
        except Exception:
            # Log the error in a real implementation
            return False
    
    def _evaluate_conditions(self, context: Dict[str, Any]) -> bool:
        """Evaluate rule conditions against the context."""
        if not self.conditions:
            return True
        
        # Similar to transition conditions evaluation
        for condition_key, condition_value in self.conditions.items():
            if condition_key not in context:
                return False
            
            context_value = context[condition_key]
            
            if isinstance(condition_value, dict):
                operator = condition_value.get('operator', 'eq')
                value = condition_value.get('value')
                
                if operator == 'eq' and context_value != value:
                    return False
                elif operator == 'ne' and context_value == value:
                    return False
                elif operator == 'gt' and context_value <= value:
                    return False
                elif operator == 'lt' and context_value >= value:
                    return False
                elif operator == 'in' and context_value not in value:
                    return False
            else:
                if context_value != condition_value:
                    return False
        
        return True
    
    def _execute_actions(self, context: Dict[str, Any]) -> None:
        """Execute the rule actions."""
        for action in self.actions:
            action_type = action.get('type')
            action_params = action.get('params', {})
            
            if action_type == self.ActionType.SEND_NOTIFICATION:
                self._send_notification(context, action_params)
            elif action_type == self.ActionType.ASSIGN_TASK:
                self._assign_task(context, action_params)
            elif action_type == self.ActionType.CHANGE_PRIORITY:
                self._change_priority(context, action_params)
            # Add more action implementations as needed
    
    def _send_notification(self, context: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Send notification action implementation."""
        # This would integrate with the notification system
        pass
    
    def _assign_task(self, context: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Assign task action implementation."""
        from apps.tasks.models import Task
        task = context.get('task')
        if task and isinstance(task, Task):
            # Implement task assignment logic
            pass
    
    def _change_priority(self, context: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Change priority action implementation."""
        from apps.tasks.models import Task
        task = context.get('task')
        new_priority = params.get('priority')
        if task and isinstance(task, Task) and new_priority:
            task.priority = new_priority
            task.save(update_fields=['priority'])


class WorkflowExecutionManager(models.Manager):
    """Custom manager for WorkflowExecution model."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related(
            'workflow', 'current_state', 'task', 'started_by'
        )
    
    def active(self) -> QuerySet:
        """Return only active executions."""
        return self.get_queryset().filter(status=WorkflowExecution.Status.RUNNING)
    
    def completed(self) -> QuerySet:
        """Return only completed executions."""
        return self.get_queryset().filter(status=WorkflowExecution.Status.COMPLETED)


class WorkflowExecution(TimeStampedModel):
    """
    Tracks the execution of a workflow for a specific task.
    
    Records the current state, execution history, and metadata
    for a task progressing through a workflow.
    """
    
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        RUNNING = 'running', _('Running')
        PAUSED = 'paused', _('Paused')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
        CANCELLED = 'cancelled', _('Cancelled')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='executions'
    )
    task = models.ForeignKey(
        'tasks.Task',
        on_delete=models.CASCADE,
        related_name='workflow_executions'
    )
    current_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.CASCADE,
        related_name='current_executions'
    )
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    
    # Execution tracking
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='started_workflow_executions'
    )
    
    # Execution data
    context = JSONField(default=dict, blank=True)
    execution_data = JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    
    objects = WorkflowExecutionManager()
    
    class Meta:
        db_table = 'workflows_execution'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workflow', 'status']),
            models.Index(fields=['task', 'status']),
            models.Index(fields=['current_state', 'status']),
            models.Index(fields=['started_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['task'],
                condition=models.Q(status__in=['pending', 'running', 'paused']),
                name='unique_active_workflow_execution'
            )
        ]
    
    def __str__(self) -> str:
        return f"{self.workflow.name} - {self.task.title} ({self.status})"
    
    @property
    def duration(self) -> Optional[timedelta]:
        """Calculate execution duration."""
        if not self.started_at:
            return None
        
        end_time = self.completed_at or timezone.now()
        return end_time - self.started_at
    
    @property
    def is_active(self) -> bool:
        """Check if execution is currently active."""
        return self.status in [self.Status.PENDING, self.Status.RUNNING, self.Status.PAUSED]
    
    def start(self, user: User = None) -> bool:
        """Start the workflow execution."""
        if self.status != self.Status.PENDING:
            return False
        
        with transaction.atomic():
            self.status = self.Status.RUNNING
            self.started_at = timezone.now()
            self.started_by = user
            
            if not self.current_state:
                self.current_state = self.workflow.initial_state
            
            self.save(update_fields=['status', 'started_at', 'started_by', 'current_state'])
            
            # Log the state entry
            WorkflowExecutionLog.objects.create(
                execution=self,
                event_type=WorkflowExecutionLog.EventType.STATE_ENTERED,
                from_state=None,
                to_state=self.current_state,
                user=user,
                context=self.context
            )
            
            return True
    
    def transition_to(self, new_state: WorkflowState, user: User = None, 
                     context: Dict[str, Any] = None) -> bool:
        """Transition to a new state."""
        if not self.is_active:
            return False
        
        # Check if transition is allowed
        if not self.workflow.can_transition(
            from_state=self.current_state,
            to_state=new_state,
            user=user,
            context=context or {}
        ):
            return False
        
        old_state = self.current_state
        
        with transaction.atomic():
            self.current_state = new_state
            if context:
                self.context.update(context)
            
            # Check if this is a final state
            if new_state.is_final:
                self.status = self.Status.COMPLETED
                self.completed_at = timezone.now()
            
            self.save(update_fields=['current_state', 'context', 'status', 'completed_at'])
            
            # Log the transition
            WorkflowExecutionLog.objects.create(
                execution=self,
                event_type=WorkflowExecutionLog.EventType.STATE_TRANSITION,
                from_state=old_state,
                to_state=new_state,
                user=user,
                context=context or {}
            )
            
            return True
    
    def pause(self, user: User = None, reason: str = '') -> bool:
        """Pause the workflow execution."""
        if self.status != self.Status.RUNNING:
            return False
        
        with transaction.atomic():
            self.status = self.Status.PAUSED
            self.save(update_fields=['status'])
            
            # Log the pause event
            WorkflowExecutionLog.objects.create(
                execution=self,
                event_type=WorkflowExecutionLog.EventType.EXECUTION_PAUSED,
                from_state=self.current_state,
                to_state=self.current_state,
                user=user,
                context={'reason': reason}
            )
            
            return True
    
    def resume(self, user: User = None) -> bool:
        """Resume the workflow execution."""
        if self.status != self.Status.PAUSED:
            return False
        
        with transaction.atomic():
            self.status = self.Status.RUNNING
            self.save(update_fields=['status'])
            
            # Log the resume event
            WorkflowExecutionLog.objects.create(
                execution=self,
                event_type=WorkflowExecutionLog.EventType.EXECUTION_RESUMED,
                from_state=self.current_state,
                to_state=self.current_state,
                user=user,
                context={}
            )
            
            return True
    
    def cancel(self, user: User = None, reason: str = '') -> bool:
        """Cancel the workflow execution."""
        if not self.is_active:
            return False
        
        with transaction.atomic():
            self.status = self.Status.CANCELLED
            self.completed_at = timezone.now()
            self.save(update_fields=['status', 'completed_at'])
            
            # Log the cancellation
            WorkflowExecutionLog.objects.create(
                execution=self,
                event_type=WorkflowExecutionLog.EventType.EXECUTION_CANCELLED,
                from_state=self.current_state,
                to_state=self.current_state,
                user=user,
                context={'reason': reason}
            )
            
            return True
    
    def fail(self, error_message: str = '', user: User = None) -> bool:
        """Mark the workflow execution as failed."""
        if not self.is_active:
            return False
        
        with transaction.atomic():
            self.status = self.Status.FAILED
            self.error_message = error_message
            self.completed_at = timezone.now()
            self.save(update_fields=['status', 'error_message', 'completed_at'])
            
            # Log the failure
            WorkflowExecutionLog.objects.create(
                execution=self,
                event_type=WorkflowExecutionLog.EventType.EXECUTION_FAILED,
                from_state=self.current_state,
                to_state=self.current_state,
                user=user,
                context={'error': error_message}
            )
            
            return True


class WorkflowExecutionLogManager(models.Manager):
    """Custom manager for WorkflowExecutionLog model."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related(
            'execution', 'from_state', 'to_state', 'user'
        )
    
    def for_execution(self, execution: WorkflowExecution) -> QuerySet:
        """Return logs for a specific execution."""
        return self.get_queryset().filter(execution=execution)
    
    def state_transitions(self) -> QuerySet:
        """Return only state transition logs."""
        return self.get_queryset().filter(
            event_type=WorkflowExecutionLog.EventType.STATE_TRANSITION
        )


class WorkflowExecutionLog(TimeStampedModel):
    """
    Audit log for workflow execution events.
    
    Records all events that occur during workflow execution
    including state transitions, pauses, resumes, and failures.
    """
    
    class EventType(models.TextChoices):
        EXECUTION_STARTED = 'execution_started', _('Execution Started')
        EXECUTION_PAUSED = 'execution_paused', _('Execution Paused')
        EXECUTION_RESUMED = 'execution_resumed', _('Execution Resumed')
        EXECUTION_COMPLETED = 'execution_completed', _('Execution Completed')
        EXECUTION_FAILED = 'execution_failed', _('Execution Failed')
        EXECUTION_CANCELLED = 'execution_cancelled', _('Execution Cancelled')
        STATE_ENTERED = 'state_entered', _('State Entered')
        STATE_EXITED = 'state_exited', _('State Exited')
        STATE_TRANSITION = 'state_transition', _('State Transition')
        RULE_EXECUTED = 'rule_executed', _('Rule Executed')
        ACTION_EXECUTED = 'action_executed', _('Action Executed')
        VALIDATION_FAILED = 'validation_failed', _('Validation Failed')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name='logs'
    )
    
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        db_index=True
    )
    
    # State information
    from_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='log_entries_from'
    )
    to_state = models.ForeignKey(
        WorkflowState,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='log_entries_to'
    )
    
    # Event details
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='workflow_log_entries'
    )
    message = models.TextField(blank=True)
    context = JSONField(default=dict, blank=True)
    
    # Timing
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    
    objects = WorkflowExecutionLogManager()
    
    class Meta:
        db_table = 'workflows_execution_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['execution', 'event_type']),
            models.Index(fields=['execution', 'created_at']),
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['user', 'created_at']),
        ]
    
    def __str__(self) -> str:
        return f"{self.execution} - {self.event_type} at {self.created_at}"


class TaskTemplateManager(models.Manager):
    """Custom manager for TaskTemplate model."""
    
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related(
            'workflow', 'created_by'
        ).prefetch_related('default_assignees', 'tags')
    
    def active(self) -> QuerySet:
        """Return only active templates."""
        return self.get_queryset().filter(is_active=True)
    
    def public(self) -> QuerySet:
        """Return only public templates."""
        return self.get_queryset().filter(is_public=True)


class TaskTemplate(TimeStampedModel, SoftDeleteModel):
    """
    Template for creating tasks with predefined workflows.
    
    Templates define task structure, default values, and associated
    workflows for consistent task creation.
    """
    
    class TemplateType(models.TextChoices):
        STANDARD = 'standard', _('Standard')
        RECURRING = 'recurring', _('Recurring')
        PROJECT = 'project', _('Project')
        INCIDENT = 'incident', _('Incident')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='task_templates'
    )
    
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True)
    template_type = models.CharField(
        max_length=20,
        choices=TemplateType.choices,
        default=TemplateType.STANDARD,
        db_index=True
    )
    
    # Template configuration
    is_active = models.BooleanField(default=True, db_index=True)
    is_public = models.BooleanField(default=False, db_index=True)
    
    # Task defaults
    default_title = models.CharField(max_length=200)
    default_description = models.TextField(blank=True)
    default_priority = models.CharField(
        max_length=20,
        choices=[
            ('low', _('Low')),
            ('medium', _('Medium')),
            ('high', _('High')),
            ('urgent', _('Urgent'))
        ],
        default='medium'
    )
    default_estimated_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.1)]
    )
    
    # Relationships
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_task_templates'
    )
    default_assignees = models.ManyToManyField(
        User,
        blank=True,
        related_name='default_task_templates'
    )
    tags = models.ManyToManyField(
        'tasks.Tag',
        blank=True,
        related_name='task_templates'
    )
    
    # Template variables and customization
    variables = JSONField(default=dict, blank=True)
    custom_fields = JSONField(default=dict, blank=True)
    
    # Recurring configuration (for recurring templates)
    recurrence_pattern = JSONField(default=dict, blank=True)
    
    # Usage statistics
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    objects = TaskTemplateManager()
    
    class Meta:
        db_table = 'workflows_task_template'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workflow', 'is_active']),
            models.Index(fields=['template_type', 'is_active']),
            models.Index(fields=['created_by', 'is_active']),
            models.Index(fields=['is_public', 'is_active']),
        ]
    
    def __str__(self) -> str:
        return self.name
    
    def create_task(self, user: User, variables: Dict[str, Any] = None, 
                   **kwargs) -> 'Task':
        """Create a task instance from this template."""
        from apps.tasks.models import Task
        
        # Merge template variables with provided variables
        template_vars = self.variables.copy()
        if variables:
            template_vars.update(variables)
        
        # Apply variable substitution to title and description
        title = self._substitute_variables(self.default_title, template_vars)
        description = self._substitute_variables(self.default_description, template_vars)
        
        # Create task with template defaults
        task_data = {
            'title': title,
            'description': description,
            'priority': self.default_priority,
            'estimated_hours': self.default_estimated_hours,
            'created_by': user,
            'metadata': {
                'created_from_template': str(self.id),
                'template_name': self.name,
                'template_variables': template_vars
            }
        }
        
        # Override with any provided kwargs
        task_data.update(kwargs)
        
        with transaction.atomic():
            task = Task.objects.create(**task_data)
            
            # Add default assignees
            if self.default_assignees.exists():
                task.assigned_to.set(self.default_assignees.all())
            
            # Add template tags
            if self.tags.exists():
                task.tags.set(self.tags.all())
            
            # Create workflow execution
            if self.workflow.initial_state:
                execution = WorkflowExecution.objects.create(
                    workflow=self.workflow,
                    task=task,
                    current_state=self.workflow.initial_state,
                    started_by=user,
                    context=template_vars
                )
                execution.start(user=user)
            
            # Update usage statistics
            self.usage_count += 1
            self.last_used_at = timezone.now()
            self.save(update_fields=['usage_count', 'last_used_at'])
            
            return task
    
    def _substitute_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """Substitute template variables in text."""
        if not text or not variables:
            return text
        
        try:
            # Simple variable substitution using format
            # In a real implementation, you might use a more sophisticated templating engine
            return text.format(**variables)
        except (KeyError, ValueError):
            # If substitution fails, return original text
            return text
    
    def validate_variables(self, variables: Dict[str, Any]) -> List[str]:
        """Validate provided variables against template requirements."""
        errors = []
        
        # Check required variables
        required_vars = self.variables.get('required', [])
        for var in required_vars:
            if var not in variables:
                errors.append(f"Required variable '{var}' is missing")
        
        # Check variable types
        var_types = self.variables.get('types', {})
        for var, expected_type in var_types.items():
            if var in variables:
                actual_value = variables[var]
                if expected_type == 'string' and not isinstance(actual_value, str):
                    errors.append(f"Variable '{var}' must be a string")
                elif expected_type == 'number' and not isinstance(actual_value, (int, float)):
                    errors.append(f"Variable '{var}' must be a number")
                elif expected_type == 'boolean' and not isinstance(actual_value, bool):
                    errors.append(f"Variable '{var}' must be a boolean")
        
        return errors


class WorkflowMetrics(TimeStampedModel):
    """
    Aggregated metrics for workflow performance analysis.
    
    Stores calculated metrics for workflows including average completion times,
    success rates, and bottleneck identification.
    """
    
    class MetricType(models.TextChoices):
        COMPLETION_TIME = 'completion_time', _('Completion Time')
        SUCCESS_RATE = 'success_rate', _('Success Rate')
        STATE_DURATION = 'state_duration', _('State Duration')
        BOTTLENECK_ANALYSIS = 'bottleneck_analysis', _('Bottleneck Analysis')
        THROUGHPUT = 'throughput', _('Throughput')
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='metrics'
    )
    
    metric_type = models.CharField(
        max_length=30,
        choices=MetricType.choices,
        db_index=True
    )
    
    # Time period for the metrics
    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField(db_index=True)
    
    # Metric data
    value = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=20, default='count')
    
    # Additional metric details
    details = JSONField(default=dict, blank=True)
    
    # Sample size
    sample_size = models.PositiveIntegerField(default=0)
    
    class Meta:
        db_table = 'workflows_metrics'
        ordering = ['-period_end']
        indexes = [
            models.Index(fields=['workflow', 'metric_type', 'period_end']),
            models.Index(fields=['metric_type', 'period_end']),
            models.Index(fields=['period_start', 'period_end']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'metric_type', 'period_start', 'period_end'],
                name='unique_workflow_metric_period'
            )
        ]
    
    def __str__(self) -> str:
        return f"{self.workflow.name} - {self.metric_type}: {self.value} {self.unit}"


# Signal handlers for workflow automation
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


@receiver(post_save, sender='tasks.Task')
def handle_task_created(sender, instance, created, **kwargs):
    """Handle task creation events for workflow automation."""
    if created:
        # Check for workflow rules that should trigger on task creation
        try:
            from apps.workflows.services import WorkflowRuleEngine
            
            context = {
                'task': instance,
                'event': 'task_created',
                'user': getattr(instance, '_created_by_user', None)
            }
            
            WorkflowRuleEngine.execute_rules_for_event(
                event='task_created',
                context=context
            )
        except ImportError:
            # WorkflowRuleEngine not available yet, skip
            pass


@receiver(pre_save, sender='tasks.Task')
def handle_task_updated(sender, instance, **kwargs):
    """Handle task update events for workflow automation."""
    if instance.pk:  # Only for existing tasks
        try:
            from apps.tasks.models import Task
            old_instance = Task.objects.get(pk=instance.pk)
            
            # Check what changed
            changes = {}
            for field in ['status', 'priority']:
                old_value = getattr(old_instance, field, None)
                new_value = getattr(instance, field, None)
                if old_value != new_value:
                    changes[field] = {'old': old_value, 'new': new_value}
            
            # Check many-to-many field changes separately
            if hasattr(instance, '_state') and instance._state.adding is False:
                # For M2M fields, we need to handle this in post_save or use m2m_changed signal
                pass
            
            if changes:
                try:
                    from apps.workflows.services import WorkflowRuleEngine
                    
                    context = {
                        'task': instance,
                        'old_task': old_instance,
                        'changes': changes,
                        'event': 'task_updated',
                        'user': getattr(instance, '_updated_by_user', None)
                    }
                    
                    WorkflowRuleEngine.execute_rules_for_event(
                        event='task_updated',
                        context=context
                    )
                except ImportError:
                    # WorkflowRuleEngine not available yet, skip
                    pass
        except Exception:
            # Task was deleted or other error, ignore
            pass
