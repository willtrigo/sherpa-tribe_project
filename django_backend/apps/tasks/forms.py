"""
Task management forms for the Enterprise Task Management System.

This module provides professionally structured forms for task operations including
creation, editing, assignment, and comment management with comprehensive validation
and optimized queries.
"""

from typing import Any, Dict, Optional, Type, Union
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Q
from django.forms.widgets import DateTimeInput, Select, SelectMultiple, Textarea, TextInput
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Task, Comment, Tag, TaskAssignment
from .choices import TaskStatus, TaskPriority
from ..users.models import Team


User = get_user_model()


class BaseTaskForm(forms.ModelForm):
    """Base form class for task-related forms with common functionality."""
    
    def __init__(self, *args: Any, user: Optional[User] = None, **kwargs: Any) -> None:
        """Initialize form with user context and optimized queries."""
        self.user = user
        super().__init__(*args, **kwargs)
        self._configure_base_widgets()
        
    def _configure_base_widgets(self) -> None:
        """Configure common widget attributes for consistent UI."""
        widget_configs = {
            'title': {'class': 'form-control form-control-lg', 'placeholder': _('Enter task title')},
            'description': {'class': 'form-control', 'rows': 4, 'placeholder': _('Task description')},
            'status': {'class': 'form-select'},
            'priority': {'class': 'form-select'},
            'due_date': {'class': 'form-control', 'type': 'datetime-local'},
            'estimated_hours': {'class': 'form-control', 'step': '0.5', 'min': '0'},
        }
        
        for field_name, attrs in widget_configs.items():
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update(attrs)


class TaskCreationForm(BaseTaskForm):
    """Professional form for creating new tasks with comprehensive validation."""
    
    assigned_to = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'multiple': True,
            'data-placeholder': _('Select assignees')
        }),
        required=False,
        help_text=_('Hold Ctrl/Cmd to select multiple users')
    )
    
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'multiple': True,
            'data-placeholder': _('Select tags')
        }),
        required=False,
        help_text=_('Categorize your task with relevant tags')
    )
    
    parent_task = forms.ModelChoiceField(
        queryset=Task.objects.none(),
        widget=Select(attrs={
            'class': 'form-select',
            'data-placeholder': _('Select parent task')
        }),
        required=False,
        help_text=_('Create subtask under existing task')
    )
    
    class Meta:
        model = Task
        fields = [
            'title', 'description', 'status', 'priority', 'due_date',
            'estimated_hours', 'assigned_to', 'tags', 'parent_task', 'metadata'
        ]
        widgets = {
            'title': TextInput(attrs={'maxlength': 200}),
            'description': Textarea(attrs={'maxlength': 2000}),
            'status': Select(choices=TaskStatus.choices),
            'priority': Select(choices=TaskPriority.choices),
            'due_date': DateTimeInput(attrs={'type': 'datetime-local'}),
            'estimated_hours': forms.NumberInput(attrs={'step': '0.25', 'min': '0.25'}),
            'metadata': forms.HiddenInput(),
        }
        
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with optimized querysets and user-specific data."""
        super().__init__(*args, **kwargs)
        self._configure_querysets()
        self._set_initial_values()
        
    def _configure_querysets(self) -> None:
        """Configure optimized querysets for form fields."""
        if self.user:
            # Optimize user queryset with select_related for team info
            self.fields['assigned_to'].queryset = (
                User.objects
                .select_related('profile')
                .filter(is_active=True)
                .order_by('first_name', 'last_name')
            )
            
            # Get available parent tasks (exclude archived and completed)
            self.fields['parent_task'].queryset = (
                Task.objects
                .select_related('created_by')
                .filter(
                    Q(created_by=self.user) | Q(assigned_to=self.user),
                    is_archived=False
                )
                .exclude(status=TaskStatus.COMPLETED)
                .order_by('-created_at')
            )
        
        # Configure tags queryset
        self.fields['tags'].queryset = Tag.objects.filter(is_active=True).order_by('name')
        
    def _set_initial_values(self) -> None:
        """Set intelligent initial values based on user context."""
        if not self.instance.pk:
            self.fields['status'].initial = TaskStatus.TODO
            self.fields['priority'].initial = TaskPriority.MEDIUM
            self.fields['due_date'].initial = timezone.now() + timezone.timedelta(days=7)
            
    def clean_due_date(self) -> Optional[timezone.datetime]:
        """Validate due date is in the future and within reasonable limits."""
        due_date = self.cleaned_data.get('due_date')
        if not due_date:
            return due_date
            
        now = timezone.now()
        if due_date <= now:
            raise ValidationError(_('Due date must be in the future.'))
            
        # Prevent dates too far in the future (2 years)
        max_future = now + timezone.timedelta(days=730)
        if due_date > max_future:
            raise ValidationError(_('Due date cannot be more than 2 years in the future.'))
            
        return due_date
        
    def clean_estimated_hours(self) -> Optional[float]:
        """Validate estimated hours are within reasonable bounds."""
        hours = self.cleaned_data.get('estimated_hours')
        if hours is not None:
            if hours <= 0:
                raise ValidationError(_('Estimated hours must be greater than 0.'))
            if hours > 1000:  # Reasonable upper limit
                raise ValidationError(_('Estimated hours cannot exceed 1000.'))
        return hours
        
    def clean(self) -> Dict[str, Any]:
        """Perform cross-field validation."""
        cleaned_data = super().clean()
        parent_task = cleaned_data.get('parent_task')
        assigned_to = cleaned_data.get('assigned_to')
        
        # Validate parent task logic
        if parent_task and parent_task.parent_task:
            # Prevent deeply nested hierarchies (max 2 levels)
            raise ValidationError({
                'parent_task': _('Cannot create subtask under another subtask.')
            })
            
        # Validate assignment logic
        if assigned_to and assigned_to.count() > 10:
            raise ValidationError({
                'assigned_to': _('Cannot assign task to more than 10 users.')
            })
            
        return cleaned_data
        
    def save(self, commit: bool = True) -> Task:
        """Save task with proper user attribution and metadata."""
        task = super().save(commit=False)
        
        if self.user and not task.created_by_id:
            task.created_by = self.user
            
        # Set metadata for creation context
        if not task.metadata:
            task.metadata = {}
        task.metadata.update({
            'created_via': 'web_form',
            'creation_timestamp': timezone.now().isoformat(),
        })
        
        if commit:
            task.save()
            self.save_m2m()
            
        return task


class TaskEditForm(BaseTaskForm):
    """Professional form for editing existing tasks with status validation."""
    
    actual_hours = forms.DecimalField(
        max_digits=8,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.25',
            'min': '0'
        }),
        help_text=_('Actual time spent on this task')
    )
    
    class Meta:
        model = Task
        fields = [
            'title', 'description', 'status', 'priority', 'due_date',
            'estimated_hours', 'actual_hours', 'metadata'
        ]
        widgets = {
            'title': TextInput(attrs={'maxlength': 200}),
            'description': Textarea(attrs={'maxlength': 2000}),
            'status': Select(choices=TaskStatus.choices),
            'priority': Select(choices=TaskPriority.choices),
            'due_date': DateTimeInput(attrs={'type': 'datetime-local'}),
            'estimated_hours': forms.NumberInput(attrs={'step': '0.25'}),
        }
        
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with current task state validation."""
        super().__init__(*args, **kwargs)
        self._configure_status_transitions()
        
    def _configure_status_transitions(self) -> None:
        """Configure valid status transitions based on current state."""
        if self.instance and self.instance.pk:
            current_status = self.instance.status
            valid_transitions = self._get_valid_status_transitions(current_status)
            
            self.fields['status'].choices = [
                (status, label) for status, label in TaskStatus.choices
                if status in valid_transitions
            ]
            
    def _get_valid_status_transitions(self, current_status: str) -> list[str]:
        """Define business rules for status transitions."""
        transitions = {
            TaskStatus.TODO: [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
            TaskStatus.IN_PROGRESS: [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.ON_HOLD, TaskStatus.CANCELLED],
            TaskStatus.ON_HOLD: [TaskStatus.ON_HOLD, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
            TaskStatus.COMPLETED: [TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS],  # Allow reopening
            TaskStatus.CANCELLED: [TaskStatus.CANCELLED, TaskStatus.TODO],  # Allow reactivation
        }
        return transitions.get(current_status, list(TaskStatus.values))
        
    def clean(self) -> Dict[str, Any]:
        """Validate status transitions and completion requirements."""
        cleaned_data = super().clean()
        new_status = cleaned_data.get('status')
        
        if self.instance and self.instance.pk:
            old_status = self.instance.status
            
            # Validate completion requirements
            if (new_status == TaskStatus.COMPLETED and 
                old_status != TaskStatus.COMPLETED):
                self._validate_completion_requirements(cleaned_data)
                
        return cleaned_data
        
    def _validate_completion_requirements(self, cleaned_data: Dict[str, Any]) -> None:
        """Validate requirements for marking task as completed."""
        # Check for incomplete subtasks
        if self.instance.subtasks.filter(
            is_archived=False
        ).exclude(status=TaskStatus.COMPLETED).exists():
            raise ValidationError({
                'status': _('Cannot complete task with incomplete subtasks.')
            })
            
        # Encourage actual hours logging
        if not cleaned_data.get('actual_hours') and not self.instance.actual_hours:
            self.add_error('actual_hours', _(
                'Consider logging actual hours spent for better project tracking.'
            ))


class TaskAssignmentForm(forms.Form):
    """Professional form for bulk task assignment operations."""
    
    assigned_to = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'multiple': True,
            'size': '6'
        }),
        help_text=_('Select users to assign this task to')
    )
    
    assignment_note = forms.CharField(
        max_length=500,
        required=False,
        widget=Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': _('Optional note about this assignment')
        }),
        help_text=_('Add context or instructions for assignees')
    )
    
    notify_assignees = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text=_('Send notification to newly assigned users')
    )
    
    def __init__(self, *args: Any, task: Optional[Task] = None, user: Optional[User] = None, **kwargs: Any) -> None:
        """Initialize with task and user context."""
        self.task = task
        self.user = user
        super().__init__(*args, **kwargs)
        self._configure_assignee_queryset()
        
    def _configure_assignee_queryset(self) -> None:
        """Configure optimized queryset for potential assignees."""
        queryset = (
            User.objects
            .select_related('profile')
            .filter(is_active=True)
            .order_by('first_name', 'last_name')
        )
        
        # If task exists, show current assignments as selected
        if self.task:
            current_assignees = self.task.assigned_to.all()
            self.fields['assigned_to'].initial = current_assignees
            
        self.fields['assigned_to'].queryset = queryset
        
    def clean_assigned_to(self) -> QuerySet[User]:
        """Validate assignment constraints."""
        assignees = self.cleaned_data.get('assigned_to')
        
        if not assignees:
            raise ValidationError(_('At least one assignee must be selected.'))
            
        if assignees.count() > 15:
            raise ValidationError(_('Cannot assign task to more than 15 users.'))
            
        return assignees
        
    def save(self, task: Task) -> list[TaskAssignment]:
        """Create task assignments with metadata."""
        if not self.is_valid():
            raise ValueError("Form must be valid before saving")
            
        assignees = self.cleaned_data['assigned_to']
        note = self.cleaned_data.get('assignment_note', '')
        
        # Clear existing assignments
        TaskAssignment.objects.filter(task=task).delete()
        
        # Create new assignments
        assignments = []
        for user in assignees:
            assignment = TaskAssignment.objects.create(
                task=task,
                user=user,
                assigned_by=self.user,
                assignment_note=note,
                metadata={
                    'assignment_method': 'manual_form',
                    'assigned_at': timezone.now().isoformat(),
                }
            )
            assignments.append(assignment)
            
        return assignments


class TaskCommentForm(forms.ModelForm):
    """Professional form for adding comments to tasks."""
    
    class Meta:
        model = Comment
        fields = ['content', 'is_internal']
        widgets = {
            'content': Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('Add your comment here...'),
                'maxlength': 2000
            }),
            'is_internal': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        
    def __init__(self, *args: Any, task: Optional[Task] = None, user: Optional[User] = None, **kwargs: Any) -> None:
        """Initialize with task and user context."""
        self.task = task
        self.user = user
        super().__init__(*args, **kwargs)
        self._configure_permissions()
        
    def _configure_permissions(self) -> None:
        """Configure form based on user permissions."""
        if self.user and not self.user.has_perm('tasks.add_internal_comment'):
            # Hide internal comment option for users without permission
            self.fields['is_internal'].widget = forms.HiddenInput()
            self.fields['is_internal'].initial = False
            
    def clean_content(self) -> str:
        """Validate comment content."""
        content = self.cleaned_data.get('content', '').strip()
        
        if not content:
            raise ValidationError(_('Comment cannot be empty.'))
            
        if len(content) < 10:
            raise ValidationError(_('Comment must be at least 10 characters long.'))
            
        return content
        
    def save(self, commit: bool = True) -> Comment:
        """Save comment with proper attribution."""
        comment = super().save(commit=False)
        
        if self.task:
            comment.task = self.task
        if self.user:
            comment.created_by = self.user
            
        if commit:
            comment.save()
            
        return comment


class TaskFilterForm(forms.Form):
    """Professional form for filtering and searching tasks."""
    
    search = forms.CharField(
        max_length=200,
        required=False,
        widget=TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Search tasks by title or description...'),
            'data-search-target': 'tasks'
        })
    )
    
    status = forms.MultipleChoiceField(
        choices=TaskStatus.choices,
        required=False,
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'size': '4'
        })
    )
    
    priority = forms.MultipleChoiceField(
        choices=TaskPriority.choices,
        required=False,
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'size': '3'
        })
    )
    
    assigned_to = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'size': '4'
        })
    )
    
    created_by = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=Select(attrs={
            'class': 'form-select',
            'data-placeholder': _('All creators')
        })
    )
    
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        widget=SelectMultiple(attrs={
            'class': 'form-select',
            'size': '4'
        })
    )
    
    due_date_from = forms.DateTimeField(
        required=False,
        widget=DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        })
    )
    
    due_date_to = forms.DateTimeField(
        required=False,
        widget=DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        })
    )
    
    is_overdue = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def __init__(self, *args: Any, user: Optional[User] = None, **kwargs: Any) -> None:
        """Initialize with user-specific filter options."""
        self.user = user
        super().__init__(*args, **kwargs)
        self._configure_choice_fields()
        
    def _configure_choice_fields(self) -> None:
        """Configure querysets for choice fields."""
        if self.user:
            # Configure user-based querysets
            active_users = (
                User.objects
                .filter(is_active=True)
                .order_by('first_name', 'last_name')
            )
            
            self.fields['assigned_to'].queryset = active_users
            self.fields['created_by'].queryset = active_users
            
        # Configure tags
        self.fields['tags'].queryset = (
            Tag.objects
            .filter(is_active=True)
            .order_by('name')
        )
        
    def clean(self) -> Dict[str, Any]:
        """Validate date range consistency."""
        cleaned_data = super().clean()
        due_from = cleaned_data.get('due_date_from')
        due_to = cleaned_data.get('due_date_to')
        
        if due_from and due_to and due_from > due_to:
            raise ValidationError({
                'due_date_to': _('End date must be after start date.')
            })
            
        return cleaned_data
