from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
import re


def validate_due_date(value):
    """
    Validate that due date is not in the past.
    Allow some flexibility for tasks being created at the exact due time.
    """
    if value and value < timezone.now() - timezone.timedelta(minutes=5):
        raise ValidationError(
            _('Due date cannot be in the past.'),
            code='invalid_due_date'
        )


def validate_estimated_hours(value):
    """
    Validate estimated hours is within reasonable bounds.
    """
    if value is not None:
        if value <= 0:
            raise ValidationError(
                _('Estimated hours must be greater than 0.'),
                code='invalid_estimated_hours'
            )
        
        # Maximum 1000 hours per task (reasonable upper bound)
        if value > Decimal('1000.00'):
            raise ValidationError(
                _('Estimated hours cannot exceed 1000 hours.'),
                code='estimated_hours_too_high'
            )
        
        # Minimum 0.1 hours (6 minutes)
        if value < Decimal('0.1'):
            raise ValidationError(
                _('Estimated hours must be at least 0.1 hours (6 minutes).'),
                code='estimated_hours_too_low'
            )


def validate_actual_hours(value):
    """
    Validate actual hours is within reasonable bounds.
    """
    if value is not None:
        if value < 0:
            raise ValidationError(
                _('Actual hours cannot be negative.'),
                code='negative_actual_hours'
            )
        
        # Maximum 2000 hours per task (more flexible than estimated)
        if value > Decimal('2000.00'):
            raise ValidationError(
                _('Actual hours cannot exceed 2000 hours.'),
                code='actual_hours_too_high'
            )


def validate_tag_name(value):
    """
    Validate tag name format and content.
    """
    if not value:
        raise ValidationError(
            _('Tag name cannot be empty.'),
            code='empty_tag_name'
        )
    
    # Only allow alphanumeric characters, hyphens, and underscores
    if not re.match(r'^[a-zA-Z0-9_-]+$', value):
        raise ValidationError(
            _('Tag name can only contain letters, numbers, hyphens, and underscores.'),
            code='invalid_tag_format'
        )
    
    # Minimum length
    if len(value) < 2:
        raise ValidationError(
            _('Tag name must be at least 2 characters long.'),
            code='tag_name_too_short'
        )
    
    # Maximum length (redundant with model field but good practice)
    if len(value) > 50:
        raise ValidationError(
            _('Tag name cannot exceed 50 characters.'),
            code='tag_name_too_long'
        )


def validate_hex_color(value):
    """
    Validate hex color code format.
    """
    if not value:
        return
    
    # Check format: #RRGGBB
    if not re.match(r'^#[0-9A-Fa-f]{6}$', value):
        raise ValidationError(
            _('Color must be a valid hex color code (e.g., #FF0000).'),
            code='invalid_hex_color'
        )


def validate_completion_percentage(value):
    """
    Validate completion percentage is between 0 and 100.
    """
    if value is not None:
        if not (0 <= value <= 100):
            raise ValidationError(
                _('Completion percentage must be between 0 and 100.'),
                code='invalid_completion_percentage'
            )


def validate_priority_weight(value):
    """
    Validate priority weight is within acceptable range.
    """
    if value is not None:
        if not (1 <= value <= 10):
            raise ValidationError(
                _('Priority weight must be between 1 and 10.'),
                code='invalid_priority_weight'
            )


def validate_task_title(value):
    """
    Validate task title content and format.
    """
    if not value or not value.strip():
        raise ValidationError(
            _('Task title cannot be empty or contain only whitespace.'),
            code='empty_task_title'
        )
    
    # Remove extra whitespace
    value = value.strip()
    
    # Minimum length
    if len(value) < 3:
        raise ValidationError(
            _('Task title must be at least 3 characters long.'),
            code='title_too_short'
        )
    
    # Check for reasonable content (not just special characters)
    if not re.search(r'[a-zA-Z0-9]', value):
        raise ValidationError(
            _('Task title must contain at least one alphanumeric character.'),
            code='title_no_content'
        )


def validate_task_description(value):
    """
    Validate task description content.
    """
    if not value or not value.strip():
        raise ValidationError(
            _('Task description cannot be empty or contain only whitespace.'),
            code='empty_task_description'
        )
    
    # Minimum meaningful length
    if len(value.strip()) < 10:
        raise ValidationError(
            _('Task description must be at least 10 characters long.'),
            code='description_too_short'
        )


def validate_comment_content(value):
    """
    Validate comment content.
    """
    if not value or not value.strip():
        raise ValidationError(
            _('Comment cannot be empty or contain only whitespace.'),
            code='empty_comment'
        )
    
    # Minimum length
    if len(value.strip()) < 2:
        raise ValidationError(
            _('Comment must be at least 2 characters long.'),
            code='comment_too_short'
        )
    
    # Maximum length for performance
    if len(value) > 10000:
        raise ValidationError(
            _('Comment cannot exceed 10,000 characters.'),
            code='comment_too_long'
        )


def validate_team_name(value):
    """
    Validate team name format and content.
    """
    if not value or not value.strip():
        raise ValidationError(
            _('Team name cannot be empty or contain only whitespace.'),
            code='empty_team_name'
        )
    
    # Remove extra whitespace
    value = value.strip()
    
    # Minimum length
    if len(value) < 2:
        raise ValidationError(
            _('Team name must be at least 2 characters long.'),
            code='team_name_too_short'
        )
    
    # Check for prohibited patterns
    if value.lower() in ['admin', 'system', 'root', 'administrator']:
        raise ValidationError(
            _('This team name is reserved and cannot be used.'),
            code='reserved_team_name'
        )


def validate_metadata_json(value):
    """
    Validate metadata JSON structure and content.
    """
    if not value:
        return
    
    if not isinstance(value, dict):
        raise ValidationError(
            _('Metadata must be a valid JSON object.'),
            code='invalid_metadata_format'
        )
    
    # Check for reasonable size to prevent abuse
    import json
    json_str = json.dumps(value)
    if len(json_str) > 50000:  # 50KB limit
        raise ValidationError(
            _('Metadata JSON cannot exceed 50KB in size.'),
            code='metadata_too_large'
        )
    
    # Validate no dangerous keys
    dangerous_keys = ['__proto__', 'constructor', 'prototype']
    if any(key in value for key in dangerous_keys):
        raise ValidationError(
            _('Metadata contains prohibited keys.'),
            code='dangerous_metadata_keys'
        )


def validate_recurrence_pattern(value):
    """
    Validate recurrence pattern JSON structure.
    """
    if not value:
        return
    
    if not isinstance(value, dict):
        raise ValidationError(
            _('Recurrence pattern must be a valid JSON object.'),
            code='invalid_recurrence_format'
        )
    
    # Check for required fields if pattern is specified
    if value and 'type' not in value:
        raise ValidationError(
            _('Recurrence pattern must specify a type.'),
            code='missing_recurrence_type'
        )
    
    # Validate interval if specified
    if 'interval' in value:
        interval = value['interval']
        if not isinstance(interval, int) or interval <= 0:
            raise ValidationError(
                _('Recurrence interval must be a positive integer.'),
                code='invalid_recurrence_interval'
            )
        
        if interval > 365:  # Reasonable upper bound
            raise ValidationError(
                _('Recurrence interval cannot exceed 365.'),
                code='recurrence_interval_too_high'
            )


def validate_business_hours(start_time, end_time):
    """
    Validate business hours time range.
    """
    if start_time and end_time:
        if start_time >= end_time:
            raise ValidationError(
                _('Business hours start time must be before end time.'),
                code='invalid_business_hours'
            )


def validate_sla_hours(value):
    """
    Validate SLA hours configuration.
    """
    if value is not None:
        if value <= 0:
            raise ValidationError(
                _('SLA hours must be greater than 0.'),
                code='invalid_sla_hours'
            )
        
        # Maximum 30 days (720 hours) for SLA
        if value > 720:
            raise ValidationError(
                _('SLA hours cannot exceed 720 hours (30 days).'),
                code='sla_hours_too_high'
            )


class TaskStatusTransitionValidator:
    """
    Validator for task status transitions to enforce business rules.
    """
    
    def __init__(self, task, new_status, user=None):
        self.task = task
        self.new_status = new_status
        self.user = user
    
    def validate(self):
        """
        Validate if the status transition is allowed.
        """
        from apps.tasks.choices import TaskStatus, WorkflowTransition
        
        current_status = self.task.status
        
        # No validation needed if status isn't changing
        if current_status == self.new_status:
            return
        
        # Define allowed transitions
        allowed_transitions = {
            TaskStatus.TODO: [TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
            TaskStatus.IN_PROGRESS: [TaskStatus.IN_REVIEW, TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
            TaskStatus.IN_REVIEW: [TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.CANCELLED],
            TaskStatus.BLOCKED: [TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
            TaskStatus.DONE: [TaskStatus.IN_PROGRESS],  # Allow reopening
            TaskStatus.CANCELLED: [TaskStatus.TODO, TaskStatus.IN_PROGRESS]  # Allow reactivation
        }
        
        valid_next_statuses = allowed_transitions.get(current_status, [])
        
        if self.new_status not in valid_next_statuses:
            raise ValidationError(
                _(f'Cannot transition from {current_status} to {self.new_status}.'),
                code='invalid_status_transition'
            )
        
        # Additional business rule validations
        self._validate_business_rules()
    
    def _validate_business_rules(self):
        """
        Validate business-specific rules for status transitions.
        """
        from apps.tasks.choices import TaskStatus
        
        # Cannot mark as done if has incomplete subtasks
        if (self.new_status == TaskStatus.DONE and 
            self.task.subtasks.filter(is_deleted=False).exclude(status=TaskStatus.DONE).exists()):
            raise ValidationError(
                _('Cannot mark task as done while it has incomplete subtasks.'),
                code='incomplete_subtasks'
            )
        
        # Cannot mark as in review without description or proper content
        if (self.new_status == TaskStatus.IN_REVIEW and 
            (not self.task.description or len(self.task.description.strip()) < 10)):
            raise ValidationError(
                _('Task must have adequate description before submitting for review.'),
                code='insufficient_task_content'
            )
