"""
Workflow rules engine for task automation and business logic.

This module provides a comprehensive rule-based system for automating task workflows,
implementing business logic, and managing task lifecycle automation.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set, Type, Union

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.tasks.models import Task, TaskHistory
from apps.tasks.choices import TaskStatus, TaskPriority
from apps.notifications.services import NotificationService
from apps.common.exceptions import WorkflowRuleException
from apps.common.utils import get_business_hours_difference

logger = logging.getLogger(__name__)

User = get_user_model()


class RuleType(Enum):
    """Enumeration of available rule types."""
    AUTO_ASSIGNMENT = "auto_assignment"
    STATUS_TRANSITION = "status_transition"
    ESCALATION = "escalation"
    NOTIFICATION = "notification"
    DEPENDENCY = "dependency"
    SLA_MONITORING = "sla_monitoring"
    WORKLOAD_BALANCING = "workload_balancing"


class TriggerEvent(Enum):
    """Events that can trigger workflow rules."""
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_ASSIGNED = "task_assigned"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    DUE_DATE_APPROACHING = "due_date_approaching"
    TASK_OVERDUE = "task_overdue"
    SUBTASK_COMPLETED = "subtask_completed"
    ALL_SUBTASKS_COMPLETED = "all_subtasks_completed"
    COMMENT_ADDED = "comment_added"
    USER_AVAILABILITY_CHANGED = "user_availability_changed"


@dataclass(frozen=True)
class RuleContext:
    """Context data passed to rule evaluation and execution."""
    task: Task
    trigger_event: TriggerEvent
    user: Optional[User] = None
    old_values: Optional[Dict[str, Any]] = None
    additional_data: Optional[Dict[str, Any]] = None
    
    @property
    def task_id(self) -> int:
        return self.task.id
    
    @property
    def created_by(self) -> User:
        return self.task.created_by


class RuleCondition(Protocol):
    """Protocol for rule conditions."""
    
    def evaluate(self, context: RuleContext) -> bool:
        """Evaluate if the condition is met."""
        ...


class RuleAction(Protocol):
    """Protocol for rule actions."""
    
    def execute(self, context: RuleContext) -> bool:
        """Execute the action. Returns True if successful."""
        ...


class BaseRuleCondition(ABC):
    """Base class for all rule conditions."""
    
    @abstractmethod
    def evaluate(self, context: RuleContext) -> bool:
        """Evaluate the condition against the given context."""
        pass
    
    def __and__(self, other: 'BaseRuleCondition') -> 'AndCondition':
        return AndCondition(self, other)
    
    def __or__(self, other: 'BaseRuleCondition') -> 'OrCondition':
        return OrCondition(self, other)
    
    def __invert__(self) -> 'NotCondition':
        return NotCondition(self)


class AndCondition(BaseRuleCondition):
    """Logical AND condition."""
    
    def __init__(self, *conditions: BaseRuleCondition):
        self.conditions = conditions
    
    def evaluate(self, context: RuleContext) -> bool:
        return all(condition.evaluate(context) for condition in self.conditions)


class OrCondition(BaseRuleCondition):
    """Logical OR condition."""
    
    def __init__(self, *conditions: BaseRuleCondition):
        self.conditions = conditions
    
    def evaluate(self, context: RuleContext) -> bool:
        return any(condition.evaluate(context) for condition in self.conditions)


class NotCondition(BaseRuleCondition):
    """Logical NOT condition."""
    
    def __init__(self, condition: BaseRuleCondition):
        self.condition = condition
    
    def evaluate(self, context: RuleContext) -> bool:
        return not self.condition.evaluate(context)


# Condition Implementations

class TaskStatusCondition(BaseRuleCondition):
    """Condition based on task status."""
    
    def __init__(self, status: Union[TaskStatus, List[TaskStatus]], operator: str = "eq"):
        self.status = [status] if isinstance(status, TaskStatus) else status
        self.operator = operator
    
    def evaluate(self, context: RuleContext) -> bool:
        task_status = TaskStatus(context.task.status)
        
        if self.operator == "eq":
            return task_status in self.status
        elif self.operator == "ne":
            return task_status not in self.status
        
        return False


class TaskPriorityCondition(BaseRuleCondition):
    """Condition based on task priority."""
    
    def __init__(self, priority: Union[TaskPriority, List[TaskPriority]], operator: str = "eq"):
        self.priority = [priority] if isinstance(priority, TaskPriority) else priority
        self.operator = operator
    
    def evaluate(self, context: RuleContext) -> bool:
        task_priority = TaskPriority(context.task.priority)
        
        if self.operator == "eq":
            return task_priority in self.priority
        elif self.operator == "ne":
            return task_priority not in self.priority
        elif self.operator == "gte":
            priority_order = [TaskPriority.LOW, TaskPriority.MEDIUM, TaskPriority.HIGH, TaskPriority.CRITICAL]
            task_index = priority_order.index(task_priority)
            min_index = min(priority_order.index(p) for p in self.priority)
            return task_index >= min_index
        
        return False


class DueDateCondition(BaseRuleCondition):
    """Condition based on due date proximity."""
    
    def __init__(self, hours_before: int, operator: str = "lte"):
        self.hours_before = hours_before
        self.operator = operator
    
    def evaluate(self, context: RuleContext) -> bool:
        if not context.task.due_date:
            return False
        
        now = timezone.now()
        time_until_due = context.task.due_date - now
        hours_until_due = time_until_due.total_seconds() / 3600
        
        if self.operator == "lte":
            return hours_until_due <= self.hours_before
        elif self.operator == "gte":
            return hours_until_due >= self.hours_before
        elif self.operator == "eq":
            return abs(hours_until_due - self.hours_before) < 1  # Within 1 hour
        
        return False


class AssigneeWorkloadCondition(BaseRuleCondition):
    """Condition based on assignee workload."""
    
    def __init__(self, max_active_tasks: int, operator: str = "lt"):
        self.max_active_tasks = max_active_tasks
        self.operator = operator
    
    def evaluate(self, context: RuleContext) -> bool:
        if not context.task.assigned_to.exists():
            return self.operator == "eq" and self.max_active_tasks == 0
        
        active_statuses = [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW]
        
        for user in context.task.assigned_to.all():
            active_tasks_count = Task.objects.filter(
                assigned_to=user,
                status__in=active_statuses,
                is_archived=False
            ).count()
            
            if self.operator == "lt" and active_tasks_count >= self.max_active_tasks:
                return False
            elif self.operator == "lte" and active_tasks_count > self.max_active_tasks:
                return False
            elif self.operator == "eq" and active_tasks_count != self.max_active_tasks:
                return False
        
        return True


class TagCondition(BaseRuleCondition):
    """Condition based on task tags."""
    
    def __init__(self, tag_names: List[str], operator: str = "contains_any"):
        self.tag_names = tag_names
        self.operator = operator
    
    def evaluate(self, context: RuleContext) -> bool:
        task_tag_names = set(context.task.tags.values_list('name', flat=True))
        condition_tags = set(self.tag_names)
        
        if self.operator == "contains_any":
            return bool(task_tag_names.intersection(condition_tags))
        elif self.operator == "contains_all":
            return condition_tags.issubset(task_tag_names)
        elif self.operator == "exact":
            return task_tag_names == condition_tags
        
        return False


class TriggerEventCondition(BaseRuleCondition):
    """Condition based on the trigger event."""
    
    def __init__(self, events: Union[TriggerEvent, List[TriggerEvent]]):
        self.events = [events] if isinstance(events, TriggerEvent) else events
    
    def evaluate(self, context: RuleContext) -> bool:
        return context.trigger_event in self.events


# Action Implementations

class BaseRuleAction(ABC):
    """Base class for all rule actions."""
    
    @abstractmethod
    def execute(self, context: RuleContext) -> bool:
        """Execute the action."""
        pass


class AssignTaskAction(BaseRuleAction):
    """Action to assign task to users based on criteria."""
    
    def __init__(self, assignment_strategy: str = "least_loaded", 
                 user_ids: Optional[List[int]] = None,
                 team_id: Optional[int] = None,
                 skills_required: Optional[List[str]] = None):
        self.assignment_strategy = assignment_strategy
        self.user_ids = user_ids or []
        self.team_id = team_id
        self.skills_required = skills_required or []
    
    def execute(self, context: RuleContext) -> bool:
        try:
            candidate_users = self._get_candidate_users()
            
            if not candidate_users:
                logger.warning(f"No candidate users found for task {context.task_id}")
                return False
            
            selected_user = self._select_user(candidate_users)
            
            if selected_user:
                context.task.assigned_to.add(selected_user)
                context.task.save(update_fields=['updated_at'])
                
                logger.info(f"Task {context.task_id} assigned to user {selected_user.id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to assign task {context.task_id}: {str(e)}")
            return False
    
    def _get_candidate_users(self) -> QuerySet:
        """Get candidate users for assignment."""
        queryset = User.objects.filter(is_active=True)
        
        if self.user_ids:
            queryset = queryset.filter(id__in=self.user_ids)
        
        if self.team_id:
            queryset = queryset.filter(teams__id=self.team_id)
        
        # Add skill filtering logic here if implemented
        
        return queryset
    
    def _select_user(self, candidates: QuerySet) -> Optional[User]:
        """Select user based on assignment strategy."""
        if self.assignment_strategy == "least_loaded":
            return self._get_least_loaded_user(candidates)
        elif self.assignment_strategy == "round_robin":
            return self._get_round_robin_user(candidates)
        elif self.assignment_strategy == "random":
            return candidates.order_by('?').first()
        
        return candidates.first()
    
    def _get_least_loaded_user(self, candidates: QuerySet) -> Optional[User]:
        """Get user with least active tasks."""
        active_statuses = [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW]
        
        min_load = float('inf')
        selected_user = None
        
        for user in candidates:
            active_tasks_count = Task.objects.filter(
                assigned_to=user,
                status__in=active_statuses,
                is_archived=False
            ).count()
            
            if active_tasks_count < min_load:
                min_load = active_tasks_count
                selected_user = user
        
        return selected_user
    
    def _get_round_robin_user(self, candidates: QuerySet) -> Optional[User]:
        """Get next user in round-robin fashion."""
        # Implementation would require storing last assigned user state
        # For now, fallback to least loaded
        return self._get_least_loaded_user(candidates)


class UpdateTaskStatusAction(BaseRuleAction):
    """Action to update task status."""
    
    def __init__(self, new_status: TaskStatus):
        self.new_status = new_status
    
    def execute(self, context: RuleContext) -> bool:
        try:
            old_status = context.task.status
            context.task.status = self.new_status.value
            context.task.save(update_fields=['status', 'updated_at'])
            
            # Log status change
            TaskHistory.objects.create(
                task=context.task,
                changed_by=context.user,
                field_name='status',
                old_value=old_status,
                new_value=self.new_status.value,
                change_reason=f'Automated by workflow rule'
            )
            
            logger.info(f"Task {context.task_id} status changed from {old_status} to {self.new_status.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update task {context.task_id} status: {str(e)}")
            return False


class SendNotificationAction(BaseRuleAction):
    """Action to send notifications."""
    
    def __init__(self, notification_type: str, 
                 recipients: str = "assignees",  # assignees, creator, team, custom
                 custom_recipients: Optional[List[int]] = None,
                 template_name: Optional[str] = None,
                 message: Optional[str] = None):
        self.notification_type = notification_type
        self.recipients = recipients
        self.custom_recipients = custom_recipients or []
        self.template_name = template_name
        self.message = message
    
    def execute(self, context: RuleContext) -> bool:
        try:
            notification_service = NotificationService()
            recipients = self._get_recipients(context)
            
            if not recipients:
                logger.warning(f"No recipients found for notification on task {context.task_id}")
                return False
            
            for recipient in recipients:
                notification_service.send_task_notification(
                    task=context.task,
                    recipient=recipient,
                    notification_type=self.notification_type,
                    template_name=self.template_name,
                    custom_message=self.message
                )
            
            logger.info(f"Notifications sent for task {context.task_id} to {len(recipients)} recipients")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send notifications for task {context.task_id}: {str(e)}")
            return False
    
    def _get_recipients(self, context: RuleContext) -> List[User]:
        """Get notification recipients based on configuration."""
        recipients = []
        
        if self.recipients == "assignees":
            recipients.extend(context.task.assigned_to.all())
        elif self.recipients == "creator":
            recipients.append(context.task.created_by)
        elif self.recipients == "team":
            # Get team members if task has team association
            pass
        elif self.recipients == "custom" and self.custom_recipients:
            recipients.extend(User.objects.filter(id__in=self.custom_recipients))
        
        return list(set(recipients))  # Remove duplicates


class EscalateTaskAction(BaseRuleAction):
    """Action to escalate task priority or assignment."""
    
    def __init__(self, escalation_type: str = "priority",  # priority, assignment, both
                 new_priority: Optional[TaskPriority] = None,
                 escalate_to_user_ids: Optional[List[int]] = None):
        self.escalation_type = escalation_type
        self.new_priority = new_priority
        self.escalate_to_user_ids = escalate_to_user_ids or []
    
    def execute(self, context: RuleContext) -> bool:
        try:
            updated_fields = []
            
            if self.escalation_type in ["priority", "both"] and self.new_priority:
                old_priority = context.task.priority
                context.task.priority = self.new_priority.value
                updated_fields.append('priority')
                
                TaskHistory.objects.create(
                    task=context.task,
                    changed_by=context.user,
                    field_name='priority',
                    old_value=old_priority,
                    new_value=self.new_priority.value,
                    change_reason='Escalated by workflow rule'
                )
            
            if self.escalation_type in ["assignment", "both"] and self.escalate_to_user_ids:
                escalation_users = User.objects.filter(id__in=self.escalate_to_user_ids)
                context.task.assigned_to.add(*escalation_users)
            
            if updated_fields:
                updated_fields.append('updated_at')
                context.task.save(update_fields=updated_fields)
            
            logger.info(f"Task {context.task_id} escalated (type: {self.escalation_type})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to escalate task {context.task_id}: {str(e)}")
            return False


class UpdateParentTaskAction(BaseRuleAction):
    """Action to update parent task when subtask conditions are met."""
    
    def __init__(self, parent_status: Optional[TaskStatus] = None,
                 completion_threshold: float = 1.0):  # 1.0 = all subtasks complete
        self.parent_status = parent_status
        self.completion_threshold = completion_threshold
    
    def execute(self, context: RuleContext) -> bool:
        try:
            if not context.task.parent_task:
                return True  # No parent task, action successful by default
            
            parent = context.task.parent_task
            subtasks = Task.objects.filter(parent_task=parent, is_archived=False)
            
            if not subtasks.exists():
                return True
            
            completed_subtasks = subtasks.filter(status=TaskStatus.DONE.value).count()
            completion_ratio = completed_subtasks / subtasks.count()
            
            if completion_ratio >= self.completion_threshold and self.parent_status:
                parent.status = self.parent_status.value
                parent.save(update_fields=['status', 'updated_at'])
                
                TaskHistory.objects.create(
                    task=parent,
                    changed_by=context.user,
                    field_name='status',
                    old_value=parent.status,
                    new_value=self.parent_status.value,
                    change_reason=f'Updated due to subtask completion ({completion_ratio:.1%})'
                )
                
                logger.info(f"Parent task {parent.id} updated due to subtask {context.task_id} completion")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update parent task for {context.task_id}: {str(e)}")
            return False


@dataclass
class WorkflowRule:
    """Represents a complete workflow rule with conditions and actions."""
    
    name: str
    rule_type: RuleType
    trigger_events: List[TriggerEvent]
    conditions: BaseRuleCondition
    actions: List[BaseRuleAction]
    priority: int = 0
    enabled: bool = True
    description: Optional[str] = None
    
    def can_execute(self, context: RuleContext) -> bool:
        """Check if rule can be executed for given context."""
        if not self.enabled:
            return False
        
        if context.trigger_event not in self.trigger_events:
            return False
        
        try:
            return self.conditions.evaluate(context)
        except Exception as e:
            logger.error(f"Error evaluating conditions for rule '{self.name}': {str(e)}")
            return False
    
    def execute(self, context: RuleContext) -> bool:
        """Execute all actions if conditions are met."""
        if not self.can_execute(context):
            return False
        
        success_count = 0
        total_actions = len(self.actions)
        
        for action in self.actions:
            try:
                if action.execute(context):
                    success_count += 1
                else:
                    logger.warning(f"Action failed in rule '{self.name}' for task {context.task_id}")
            except Exception as e:
                logger.error(f"Error executing action in rule '{self.name}': {str(e)}")
        
        success = success_count == total_actions
        
        if success:
            logger.info(f"Rule '{self.name}' executed successfully for task {context.task_id}")
        else:
            logger.warning(f"Rule '{self.name}' partially failed: {success_count}/{total_actions} actions succeeded")
        
        return success


class WorkflowRulesEngine:
    """Main engine for managing and executing workflow rules."""
    
    def __init__(self):
        self._rules: List[WorkflowRule] = []
        self._initialize_default_rules()
    
    def register_rule(self, rule: WorkflowRule) -> None:
        """Register a new workflow rule."""
        if any(r.name == rule.name for r in self._rules):
            raise WorkflowRuleException(f"Rule with name '{rule.name}' already exists")
        
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        
        logger.info(f"Registered workflow rule: '{rule.name}'")
    
    def unregister_rule(self, rule_name: str) -> bool:
        """Unregister a workflow rule by name."""
        for i, rule in enumerate(self._rules):
            if rule.name == rule_name:
                del self._rules[i]
                logger.info(f"Unregistered workflow rule: '{rule_name}'")
                return True
        
        logger.warning(f"Rule '{rule_name}' not found for unregistration")
        return False
    
    def get_rule(self, rule_name: str) -> Optional[WorkflowRule]:
        """Get a rule by name."""
        return next((rule for rule in self._rules if rule.name == rule_name), None)
    
    def list_rules(self, rule_type: Optional[RuleType] = None, enabled_only: bool = True) -> List[WorkflowRule]:
        """List all registered rules, optionally filtered."""
        rules = self._rules
        
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        
        if rule_type:
            rules = [r for r in rules if r.rule_type == rule_type]
        
        return rules
    
    @transaction.atomic
    def execute_rules(self, context: RuleContext) -> Dict[str, bool]:
        """Execute all applicable rules for the given context."""
        results = {}
        applicable_rules = [
            rule for rule in self._rules
            if rule.enabled and context.trigger_event in rule.trigger_events
        ]
        
        logger.info(f"Executing {len(applicable_rules)} rules for task {context.task_id}, event: {context.trigger_event.value}")
        
        for rule in applicable_rules:
            try:
                result = rule.execute(context)
                results[rule.name] = result
            except Exception as e:
                logger.error(f"Unexpected error executing rule '{rule.name}': {str(e)}")
                results[rule.name] = False
        
        return results
    
    def _initialize_default_rules(self) -> None:
        """Initialize default workflow rules."""
        # Auto-assign high priority tasks to least loaded users
        high_priority_auto_assign = WorkflowRule(
            name="auto_assign_high_priority",
            rule_type=RuleType.AUTO_ASSIGNMENT,
            trigger_events=[TriggerEvent.TASK_CREATED, TriggerEvent.PRIORITY_CHANGED],
            conditions=TaskPriorityCondition([TaskPriority.HIGH, TaskPriority.CRITICAL]) & 
                      NotCondition(AssigneeWorkloadCondition(0, "eq")),  # Not already assigned
            actions=[
                AssignTaskAction(assignment_strategy="least_loaded"),
                SendNotificationAction("task_assigned", recipients="assignees")
            ],
            priority=100,
            description="Auto-assign high/critical priority tasks to least loaded users"
        )
        
        # Escalate overdue high priority tasks
        escalate_overdue_high_priority = WorkflowRule(
            name="escalate_overdue_high_priority",
            rule_type=RuleType.ESCALATION,
            trigger_events=[TriggerEvent.TASK_OVERDUE],
            conditions=TaskPriorityCondition([TaskPriority.HIGH, TaskPriority.CRITICAL]) &
                      TaskStatusCondition([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
            actions=[
                EscalateTaskAction("priority", TaskPriority.CRITICAL),
                SendNotificationAction("task_escalated", recipients="assignees")
            ],
            priority=90,
            description="Escalate overdue high priority tasks to critical"
        )
        
        # Notify before due date
        due_date_reminder = WorkflowRule(
            name="due_date_reminder_24h",
            rule_type=RuleType.NOTIFICATION,
            trigger_events=[TriggerEvent.DUE_DATE_APPROACHING],
            conditions=DueDateCondition(24) &
                      TaskStatusCondition([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
            actions=[
                SendNotificationAction("due_date_reminder", recipients="assignees")
            ],
            priority=50,
            description="Send reminder 24 hours before due date"
        )
        
        # Update parent task when all subtasks complete
        parent_task_completion = WorkflowRule(
            name="complete_parent_on_subtasks_done",
            rule_type=RuleType.DEPENDENCY,
            trigger_events=[TriggerEvent.SUBTASK_COMPLETED],
            conditions=TriggerEventCondition(TriggerEvent.ALL_SUBTASKS_COMPLETED),
            actions=[
                UpdateParentTaskAction(TaskStatus.DONE, 1.0),
                SendNotificationAction("parent_task_completed", recipients="creator")
            ],
            priority=80,
            description="Complete parent task when all subtasks are done"
        )
        
        # Register default rules
        for rule in [
            high_priority_auto_assign,
            escalate_overdue_high_priority,
            due_date_reminder,
            parent_task_completion
        ]:
            self._rules.append(rule)
        
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        
        logger.info(f"Initialized {len(self._rules)} default workflow rules")


# Global rules engine instance
workflow_rules_engine = WorkflowRulesEngine()


def trigger_workflow_rules(task: Task, event: TriggerEvent, 
                         user: Optional[User] = None, 
                         old_values: Optional[Dict[str, Any]] = None,
                         additional_data: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
    """
    Trigger workflow rules for a task event.
    
    Args:
        task: The task that triggered the event
        event: The type of event that occurred
        user: The user who triggered the event (optional)
        old_values: Previous values for comparison (optional)
        additional_data: Additional context data (optional)
    
    Returns:
        Dictionary mapping rule names to execution results
    """
    context = RuleContext(
        task=task,
        trigger_event=event,
        user=user,
        old_values=old_values,
        additional_data=additional_data
    )
    
    return workflow_rules_engine.execute_rules(context)
