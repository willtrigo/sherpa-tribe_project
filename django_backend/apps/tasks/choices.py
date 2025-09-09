from django.db import models
from django.utils.translation import gettext_lazy as _


class TaskStatus(models.TextChoices):
    """Task status choices with professional workflow states."""
    
    TODO = 'todo', _('To Do')
    IN_PROGRESS = 'in_progress', _('In Progress')
    IN_REVIEW = 'in_review', _('In Review')
    BLOCKED = 'blocked', _('Blocked')
    DONE = 'done', _('Done')
    CANCELLED = 'cancelled', _('Cancelled')
    
    @classmethod
    def get_active_statuses(cls):
        """Get statuses that represent active work."""
        return [cls.TODO, cls.IN_PROGRESS, cls.IN_REVIEW, cls.BLOCKED]
    
    @classmethod
    def get_completed_statuses(cls):
        """Get statuses that represent completed work."""
        return [cls.DONE, cls.CANCELLED]
    
    @classmethod
    def get_workflow_order(cls):
        """Get typical workflow progression order."""
        return [cls.TODO, cls.IN_PROGRESS, cls.IN_REVIEW, cls.DONE]


class TaskPriority(models.TextChoices):
    """Task priority levels with clear hierarchy."""
    
    LOW = 'low', _('Low')
    MEDIUM = 'medium', _('Medium')
    HIGH = 'high', _('High')
    CRITICAL = 'critical', _('Critical')
    
    @classmethod
    def get_priority_order(cls):
        """Get priorities in ascending order of urgency."""
        return [cls.LOW, cls.MEDIUM, cls.HIGH, cls.CRITICAL]
    
    @classmethod
    def get_priority_weights(cls):
        """Get numeric weights for priority calculations."""
        return {
            cls.LOW: 1,
            cls.MEDIUM: 2,
            cls.HIGH: 3,
            cls.CRITICAL: 4
        }


class CommentType(models.TextChoices):
    """Comment type choices for categorization."""
    
    GENERAL = 'general', _('General Comment')
    STATUS_UPDATE = 'status_update', _('Status Update')
    QUESTION = 'question', _('Question')
    SOLUTION = 'solution', _('Solution')
    ISSUE = 'issue', _('Issue Report')
    APPROVAL = 'approval', _('Approval/Review')
    
    
class TaskHistoryAction(models.TextChoices):
    """Task history action types for audit trail."""
    
    CREATED = 'created', _('Created')
    UPDATED = 'updated', _('Updated')
    STATUS_CHANGED = 'status_changed', _('Status Changed')
    PRIORITY_CHANGED = 'priority_changed', _('Priority Changed')
    ASSIGNED = 'assigned', _('Assigned')
    UNASSIGNED = 'unassigned', _('Unassigned')
    DUE_DATE_CHANGED = 'due_date_changed', _('Due Date Changed')
    DESCRIPTION_CHANGED = 'description_changed', _('Description Changed')
    TITLE_CHANGED = 'title_changed', _('Title Changed')
    TAGS_CHANGED = 'tags_changed', _('Tags Changed')
    COMMENTED = 'commented', _('Commented')
    ATTACHMENT_ADDED = 'attachment_added', _('Attachment Added')
    ATTACHMENT_REMOVED = 'attachment_removed', _('Attachment Removed')
    DELETED = 'deleted', _('Deleted')
    RESTORED = 'restored', _('Restored')
    ARCHIVED = 'archived', _('Archived')
    UNARCHIVED = 'unarchived', _('Unarchived')


class TeamRole(models.TextChoices):
    """Team member role choices."""
    
    MEMBER = 'member', _('Member')
    LEAD = 'lead', _('Team Lead')
    ADMIN = 'admin', _('Team Admin')
    OBSERVER = 'observer', _('Observer')
    
    @classmethod
    def get_management_roles(cls):
        """Get roles with management permissions."""
        return [cls.LEAD, cls.ADMIN]


class AssignmentRole(models.TextChoices):
    """Task assignment role choices."""
    
    ASSIGNEE = 'assignee', _('Assignee')
    REVIEWER = 'reviewer', _('Reviewer')
    OBSERVER = 'observer', _('Observer')
    COLLABORATOR = 'collaborator', _('Collaborator')
    APPROVER = 'approver', _('Approver')


class RecurrencePattern(models.TextChoices):
    """Recurrence pattern choices for recurring tasks."""
    
    DAILY = 'daily', _('Daily')
    WEEKLY = 'weekly', _('Weekly')
    MONTHLY = 'monthly', _('Monthly')
    QUARTERLY = 'quarterly', _('Quarterly')
    YEARLY = 'yearly', _('Yearly')
    CUSTOM = 'custom', _('Custom Pattern')


class NotificationEvent(models.TextChoices):
    """Notification event types."""
    
    TASK_ASSIGNED = 'task_assigned', _('Task Assigned')
    TASK_UPDATED = 'task_updated', _('Task Updated')
    TASK_STATUS_CHANGED = 'task_status_changed', _('Task Status Changed')
    TASK_DUE_SOON = 'task_due_soon', _('Task Due Soon')
    TASK_OVERDUE = 'task_overdue', _('Task Overdue')
    TASK_COMPLETED = 'task_completed', _('Task Completed')
    COMMENT_ADDED = 'comment_added', _('Comment Added')
    TASK_MENTIONED = 'task_mentioned', _('Mentioned in Task')
    DEADLINE_REMINDER = 'deadline_reminder', _('Deadline Reminder')


class WorkflowTransition(models.TextChoices):
    """Workflow transition types for business logic."""
    
    START = 'start', _('Start Work')
    SUBMIT = 'submit', _('Submit for Review')
    APPROVE = 'approve', _('Approve')
    REJECT = 'reject', _('Reject')
    COMPLETE = 'complete', _('Complete')
    CANCEL = 'cancel', _('Cancel')
    REOPEN = 'reopen', _('Reopen')
    BLOCK = 'block', _('Block')
    UNBLOCK = 'unblock', _('Unblock')
    
    @classmethod
    def get_valid_transitions(cls):
        """Get valid status transitions mapping."""
        return {
            TaskStatus.TODO: [cls.START, cls.CANCEL],
            TaskStatus.IN_PROGRESS: [cls.SUBMIT, cls.COMPLETE, cls.CANCEL, cls.BLOCK],
            TaskStatus.IN_REVIEW: [cls.APPROVE, cls.REJECT],
            TaskStatus.BLOCKED: [cls.UNBLOCK, cls.CANCEL],
            TaskStatus.DONE: [cls.REOPEN],
            TaskStatus.CANCELLED: [cls.REOPEN]
        }
    
    @classmethod
    def get_transition_target_status(cls):
        """Get target status for each transition."""
        return {
            cls.START: TaskStatus.IN_PROGRESS,
            cls.SUBMIT: TaskStatus.IN_REVIEW,
            cls.APPROVE: TaskStatus.DONE,
            cls.REJECT: TaskStatus.IN_PROGRESS,
            cls.COMPLETE: TaskStatus.DONE,
            cls.CANCEL: TaskStatus.CANCELLED,
            cls.REOPEN: TaskStatus.TODO,
            cls.BLOCK: TaskStatus.BLOCKED,
            cls.UNBLOCK: TaskStatus.IN_PROGRESS
        }
