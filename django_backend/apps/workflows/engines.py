"""
Workflow Engine Implementation for Task Management System.

This module provides enterprise-grade workflow automation capabilities including:
- Status transition validation and enforcement
- Rule-based task assignment algorithms  
- Template instantiation with variable substitution
- Recurring task generation and scheduling
- SLA tracking with escalation mechanisms
- Workload balancing and priority calculation
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple, Union

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.tasks.models import Task, TaskHistory
from apps.tasks.choices import TaskStatus, TaskPriority
from apps.users.models import Team

User = get_user_model()
logger = logging.getLogger(__name__)


class WorkflowException(Exception):
    """Base exception for workflow-related errors."""
    pass


class TransitionValidationError(WorkflowException):
    """Raised when a status transition is invalid."""
    pass


class AssignmentError(WorkflowException):
    """Raised when task assignment fails."""
    pass


class EscalationError(WorkflowException):
    """Raised when task escalation fails."""
    pass


class WorkflowRuleType(Enum):
    """Types of workflow rules that can be executed."""
    
    AUTO_ASSIGNMENT = "auto_assignment"
    ESCALATION = "escalation"
    NOTIFICATION = "notification"
    STATUS_CHANGE = "status_change"
    DEPENDENCY_CHECK = "dependency_check"


@dataclass
class WorkflowContext:
    """Context object containing data for workflow rule execution."""
    
    task: Task
    user: Optional[User] = None
    previous_status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=timezone.now)


@dataclass
class AssignmentCriteria:
    """Criteria for automatic task assignment."""
    
    required_skills: Set[str] = field(default_factory=set)
    max_workload: Optional[int] = None
    team_id: Optional[int] = None
    availability_required: bool = True
    priority_threshold: Optional[str] = None


@dataclass
class EscalationRule:
    """Configuration for task escalation."""
    
    trigger_condition: str
    escalation_delay: timedelta
    target_role: Optional[str] = None
    target_user_id: Optional[int] = None
    notification_template: Optional[str] = None


class WorkflowRule(Protocol):
    """Protocol defining the interface for workflow rules."""
    
    rule_type: WorkflowRuleType
    priority: int
    
    def can_execute(self, context: WorkflowContext) -> bool:
        """Determine if this rule can be executed in the given context."""
        ...
    
    def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute the workflow rule and return results."""
        ...


class BaseWorkflowRule(ABC):
    """Abstract base class for workflow rules."""
    
    def __init__(self, priority: int = 100):
        self.priority = priority
    
    @property
    @abstractmethod
    def rule_type(self) -> WorkflowRuleType:
        """Return the type of this workflow rule."""
        pass
    
    @abstractmethod
    def can_execute(self, context: WorkflowContext) -> bool:
        """Determine if this rule can be executed."""
        pass
    
    @abstractmethod
    def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute the workflow rule."""
        pass


class StatusTransitionValidator:
    """Validates task status transitions according to business rules."""
    
    # Define valid transitions as a state machine
    VALID_TRANSITIONS = {
        TaskStatus.TODO: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
        TaskStatus.IN_PROGRESS: {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.TODO},
        TaskStatus.BLOCKED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
        TaskStatus.DONE: {TaskStatus.TODO},  # Allow reopening completed tasks
        TaskStatus.CANCELLED: {TaskStatus.TODO},  # Allow reactivating cancelled tasks
    }
    
    @classmethod
    def is_valid_transition(cls, from_status: str, to_status: str) -> bool:
        """Check if a status transition is valid."""
        try:
            from_enum = TaskStatus(from_status)
            to_enum = TaskStatus(to_status)
            return to_enum in cls.VALID_TRANSITIONS.get(from_enum, set())
        except ValueError:
            return False
    
    @classmethod
    def validate_transition(cls, task: Task, new_status: str) -> None:
        """Validate a status transition, raising exception if invalid."""
        if not cls.is_valid_transition(task.status, new_status):
            raise TransitionValidationError(
                f"Invalid transition from {task.status} to {new_status} for task {task.id}"
            )


class WorkloadBalancer:
    """Implements algorithms for balancing workload across team members."""
    
    @staticmethod
    def get_user_workload_metrics(user: User) -> Dict[str, Union[int, Decimal]]:
        """Calculate comprehensive workload metrics for a user."""
        active_tasks = Task.objects.filter(
            assigned_to=user,
            status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED]
        )
        
        return {
            'active_task_count': active_tasks.count(),
            'total_estimated_hours': active_tasks.aggregate(
                total=Sum('estimated_hours')
            )['total'] or Decimal('0'),
            'high_priority_count': active_tasks.filter(
                priority=TaskPriority.HIGH
            ).count(),
            'overdue_count': active_tasks.filter(
                due_date__lt=timezone.now()
            ).count(),
        }
    
    @staticmethod
    def calculate_workload_score(metrics: Dict[str, Union[int, Decimal]]) -> float:
        """Calculate a normalized workload score (0-100)."""
        # Weighted scoring algorithm
        weights = {
            'active_task_count': 0.3,
            'total_estimated_hours': 0.4,
            'high_priority_count': 0.2,
            'overdue_count': 0.1,
        }
        
        # Normalize values (assuming reasonable maximums)
        normalizers = {
            'active_task_count': 20,  # Max 20 active tasks
            'total_estimated_hours': 160,  # Max 160 hours (4 weeks)
            'high_priority_count': 10,  # Max 10 high priority
            'overdue_count': 5,  # Max 5 overdue tasks
        }
        
        score = 0.0
        for metric, value in metrics.items():
            normalized = min(float(value) / normalizers[metric], 1.0)
            score += weights[metric] * normalized * 100
        
        return min(score, 100.0)
    
    @classmethod
    def find_least_loaded_user(
        cls, 
        candidates: List[User], 
        criteria: Optional[AssignmentCriteria] = None
    ) -> Optional[User]:
        """Find the user with the lowest workload from candidates."""
        if not candidates:
            return None
        
        user_scores = []
        for user in candidates:
            metrics = cls.get_user_workload_metrics(user)
            
            # Apply criteria filtering
            if criteria:
                if criteria.max_workload and metrics['active_task_count'] >= criteria.max_workload:
                    continue
            
            score = cls.calculate_workload_score(metrics)
            user_scores.append((user, score))
        
        if not user_scores:
            return None
        
        # Return user with lowest score
        return min(user_scores, key=lambda x: x[1])[0]


class PriorityCalculator:
    """Calculates task priority based on multiple business factors."""
    
    PRIORITY_WEIGHTS = {
        'due_date_urgency': 0.4,
        'business_impact': 0.3,
        'dependency_criticality': 0.2,
        'stakeholder_level': 0.1,
    }
    
    @classmethod
    def calculate_priority_score(cls, task: Task) -> float:
        """Calculate a numerical priority score for a task."""
        score = 0.0
        
        # Due date urgency (0-1, higher is more urgent)
        if task.due_date:
            days_until_due = (task.due_date - timezone.now()).days
            urgency = max(0, min(1, (30 - days_until_due) / 30))  # 30-day window
            score += cls.PRIORITY_WEIGHTS['due_date_urgency'] * urgency
        
        # Business impact based on current priority
        impact_scores = {
            TaskPriority.LOW: 0.2,
            TaskPriority.MEDIUM: 0.5,
            TaskPriority.HIGH: 0.8,
            TaskPriority.CRITICAL: 1.0,
        }
        score += cls.PRIORITY_WEIGHTS['business_impact'] * impact_scores.get(task.priority, 0.5)
        
        # Dependency criticality (how many tasks depend on this one)
        dependent_count = Task.objects.filter(parent_task=task).count()
        dependency_score = min(1.0, dependent_count / 5)  # Cap at 5 dependencies
        score += cls.PRIORITY_WEIGHTS['dependency_criticality'] * dependency_score
        
        # Stakeholder level (from metadata)
        stakeholder_level = task.metadata.get('stakeholder_level', 'medium')
        level_scores = {'low': 0.2, 'medium': 0.5, 'high': 0.8, 'executive': 1.0}
        score += cls.PRIORITY_WEIGHTS['stakeholder_level'] * level_scores.get(stakeholder_level, 0.5)
        
        return score
    
    @classmethod
    def suggest_priority(cls, task: Task) -> str:
        """Suggest an appropriate priority level based on calculated score."""
        score = cls.calculate_priority_score(task)
        
        if score >= 0.8:
            return TaskPriority.CRITICAL
        elif score >= 0.6:
            return TaskPriority.HIGH
        elif score >= 0.3:
            return TaskPriority.MEDIUM
        else:
            return TaskPriority.LOW


class AutoAssignmentRule(BaseWorkflowRule):
    """Rule for automatically assigning tasks based on criteria."""
    
    rule_type = WorkflowRuleType.AUTO_ASSIGNMENT
    
    def __init__(self, criteria: AssignmentCriteria, priority: int = 100):
        super().__init__(priority)
        self.criteria = criteria
    
    def can_execute(self, context: WorkflowContext) -> bool:
        """Check if auto-assignment can be executed."""
        return (
            not context.task.assigned_to.exists() and  # Task not assigned
            context.task.status == TaskStatus.TODO  # Task is ready for assignment
        )
    
    def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute auto-assignment logic."""
        try:
            candidates = self._find_assignment_candidates(context.task)
            
            if not candidates:
                logger.warning(f"No suitable candidates found for task {context.task.id}")
                return {'success': False, 'reason': 'No suitable candidates'}
            
            selected_user = WorkloadBalancer.find_least_loaded_user(candidates, self.criteria)
            
            if selected_user:
                context.task.assigned_to.add(selected_user)
                logger.info(f"Auto-assigned task {context.task.id} to user {selected_user.id}")
                
                return {
                    'success': True,
                    'assigned_user_id': selected_user.id,
                    'assignment_reason': 'auto_assignment_workload_balanced'
                }
            
            return {'success': False, 'reason': 'All candidates overloaded'}
            
        except Exception as e:
            logger.error(f"Auto-assignment failed for task {context.task.id}: {e}")
            raise AssignmentError(f"Auto-assignment failed: {e}")
    
    def _find_assignment_candidates(self, task: Task) -> List[User]:
        """Find potential users for task assignment based on criteria."""
        queryset = User.objects.filter(is_active=True)
        
        # Filter by team if specified
        if self.criteria.team_id:
            queryset = queryset.filter(team_memberships__team_id=self.criteria.team_id)
        
        # Filter by availability if required
        if self.criteria.availability_required:
            queryset = queryset.filter(
                Q(user_profile__availability_status='available') |
                Q(user_profile__availability_status__isnull=True)
            )
        
        # Additional filtering based on required skills could be added here
        # This would require a skills model and relationship
        
        return list(queryset)


class EscalationRule(BaseWorkflowRule):
    """Rule for escalating overdue or blocked tasks."""
    
    rule_type = WorkflowRuleType.ESCALATION
    
    def __init__(self, escalation_config: EscalationRule, priority: int = 200):
        super().__init__(priority)
        self.config = escalation_config
    
    def can_execute(self, context: WorkflowContext) -> bool:
        """Check if escalation should be triggered."""
        task = context.task
        
        # Check if task is overdue
        if task.due_date and task.due_date < timezone.now():
            overdue_duration = timezone.now() - task.due_date
            return overdue_duration >= self.config.escalation_delay
        
        # Check if task has been blocked for too long
        if task.status == TaskStatus.BLOCKED:
            # Get last status change from history
            last_change = TaskHistory.objects.filter(
                task=task,
                field_name='status',
                new_value=TaskStatus.BLOCKED
            ).order_by('-changed_at').first()
            
            if last_change:
                blocked_duration = timezone.now() - last_change.changed_at
                return blocked_duration >= self.config.escalation_delay
        
        return False
    
    def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute escalation logic."""
        try:
            escalation_target = self._determine_escalation_target(context.task)
            
            if not escalation_target:
                return {'success': False, 'reason': 'No escalation target found'}
            
            # Update task metadata to track escalation
            escalation_data = {
                'escalated_at': timezone.now().isoformat(),
                'escalated_to': escalation_target.id,
                'escalation_reason': self._get_escalation_reason(context.task),
                'original_assignees': list(context.task.assigned_to.values_list('id', flat=True))
            }
            
            context.task.metadata.setdefault('escalations', []).append(escalation_data)
            context.task.assigned_to.add(escalation_target)
            context.task.save(update_fields=['metadata'])
            
            logger.info(f"Escalated task {context.task.id} to user {escalation_target.id}")
            
            return {
                'success': True,
                'escalated_to': escalation_target.id,
                'escalation_reason': escalation_data['escalation_reason']
            }
            
        except Exception as e:
            logger.error(f"Escalation failed for task {context.task.id}: {e}")
            raise EscalationError(f"Escalation failed: {e}")
    
    def _determine_escalation_target(self, task: Task) -> Optional[User]:
        """Determine who the task should be escalated to."""
        if self.config.target_user_id:
            try:
                return User.objects.get(id=self.config.target_user_id, is_active=True)
            except User.DoesNotExist:
                pass
        
        # Escalate to team lead or manager
        current_assignees = task.assigned_to.all()
        if current_assignees:
            # Try to find a manager of current assignees
            for assignee in current_assignees:
                if hasattr(assignee, 'manager') and assignee.manager:
                    return assignee.manager
        
        # Fallback to any user with appropriate role
        if self.config.target_role:
            return User.objects.filter(
                groups__name=self.config.target_role,
                is_active=True
            ).first()
        
        return None
    
    def _get_escalation_reason(self, task: Task) -> str:
        """Determine the reason for escalation."""
        if task.due_date and task.due_date < timezone.now():
            return 'overdue'
        elif task.status == TaskStatus.BLOCKED:
            return 'blocked_too_long'
        else:
            return 'unknown'


class WorkflowEngine:
    """Main workflow engine that orchestrates rule execution."""
    
    def __init__(self):
        self.rules: List[WorkflowRule] = []
        self._initialize_default_rules()
    
    def _initialize_default_rules(self) -> None:
        """Initialize default workflow rules."""
        # Default auto-assignment rule
        default_assignment_criteria = AssignmentCriteria(
            max_workload=15,
            availability_required=True
        )
        self.add_rule(AutoAssignmentRule(default_assignment_criteria))
        
        # Default escalation rule for overdue tasks
        default_escalation_config = EscalationRule(
            trigger_condition='overdue',
            escalation_delay=timedelta(days=1),
            target_role='team_lead'
        )
        self.add_rule(EscalationRule(default_escalation_config, priority=200))
    
    def add_rule(self, rule: WorkflowRule) -> None:
        """Add a workflow rule to the engine."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def remove_rule(self, rule_type: WorkflowRuleType) -> None:
        """Remove all rules of a specific type."""
        self.rules = [r for r in self.rules if r.rule_type != rule_type]
    
    @transaction.atomic
    def process_task_event(
        self, 
        task: Task, 
        event_type: str, 
        user: Optional[User] = None,
        previous_status: Optional[str] = None,
        **metadata
    ) -> Dict[str, Any]:
        """Process a task event through the workflow engine."""
        context = WorkflowContext(
            task=task,
            user=user,
            previous_status=previous_status,
            metadata=metadata
        )
        
        results = {'executed_rules': [], 'errors': []}
        
        for rule in self.rules:
            try:
                if rule.can_execute(context):
                    logger.debug(f"Executing rule {rule.__class__.__name__} for task {task.id}")
                    result = rule.execute(context)
                    
                    results['executed_rules'].append({
                        'rule_type': rule.rule_type.value,
                        'rule_class': rule.__class__.__name__,
                        'result': result
                    })
                    
            except WorkflowException as e:
                logger.error(f"Workflow rule {rule.__class__.__name__} failed: {e}")
                results['errors'].append({
                    'rule_type': rule.rule_type.value,
                    'error': str(e)
                })
            
            except Exception as e:
                logger.exception(f"Unexpected error in rule {rule.__class__.__name__}: {e}")
                results['errors'].append({
                    'rule_type': rule.rule_type.value,
                    'error': f"Unexpected error: {e}"
                })
        
        return results
    
    def validate_status_transition(self, task: Task, new_status: str) -> None:
        """Validate a status transition before applying it."""
        StatusTransitionValidator.validate_transition(task, new_status)
    
    def suggest_task_priority(self, task: Task) -> str:
        """Suggest an appropriate priority for a task."""
        return PriorityCalculator.suggest_priority(task)
    
    def calculate_workload_balance(self, team: Optional[Team] = None) -> Dict[str, Any]:
        """Calculate workload balance metrics for a team or all users."""
        if team:
            users = User.objects.filter(team_memberships__team=team, is_active=True)
        else:
            users = User.objects.filter(is_active=True)
        
        user_metrics = {}
        total_score = 0
        
        for user in users:
            metrics = WorkloadBalancer.get_user_workload_metrics(user)
            score = WorkloadBalancer.calculate_workload_score(metrics)
            
            user_metrics[user.id] = {
                'user': user.username,
                'metrics': metrics,
                'workload_score': score
            }
            total_score += score
        
        avg_score = total_score / len(user_metrics) if user_metrics else 0
        max_score = max(m['workload_score'] for m in user_metrics.values()) if user_metrics else 0
        min_score = min(m['workload_score'] for m in user_metrics.values()) if user_metrics else 0
        
        return {
            'user_metrics': user_metrics,
            'balance_statistics': {
                'average_workload': avg_score,
                'max_workload': max_score,
                'min_workload': min_score,
                'balance_ratio': (max_score - min_score) / max_score if max_score > 0 else 0,
                'total_users': len(user_metrics)
            }
        }


# Global workflow engine instance
workflow_engine = WorkflowEngine()
