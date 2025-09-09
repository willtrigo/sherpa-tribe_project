from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField

from apps.common.models import TimeStampedModel, SoftDeleteModel
from apps.tasks.managers import TaskManager, ActiveTaskManager
from apps.tasks.choices import TaskStatus, TaskPriority
from apps.tasks.validators import validate_due_date, validate_estimated_hours

User = get_user_model()


class Tag(TimeStampedModel):
    """Tag model for categorizing tasks."""
    
    name = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Unique tag name")
    )
    color = models.CharField(
        max_length=7,
        default="#007bff",
        help_text=_("Hex color code for the tag")
    )
    description = models.TextField(
        blank=True,
        help_text=_("Optional tag description")
    )
    
    class Meta:
        db_table = 'tasks_tag'
        verbose_name = _('Tag')
        verbose_name_plural = _('Tags')
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
        ]
    
    def __str__(self):
        return self.name
    
    def clean(self):
        super().clean()
        self.name = self.name.lower().strip()


class TaskTemplate(TimeStampedModel):
    """Template model for creating standardized tasks."""
    
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text=_("Template name")
    )
    title_template = models.CharField(
        max_length=200,
        help_text=_("Task title template with variables")
    )
    description_template = models.TextField(
        help_text=_("Task description template with variables")
    )
    default_priority = models.CharField(
        max_length=20,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
        help_text=_("Default priority for tasks created from this template")
    )
    default_estimated_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(0.1)],
        null=True,
        blank=True,
        help_text=_("Default estimated hours")
    )
    default_tags = models.ManyToManyField(
        Tag,
        blank=True,
        help_text=_("Default tags for tasks created from this template")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this template is active")
    )
    
    class Meta:
        db_table = 'tasks_template'
        verbose_name = _('Task Template')
        verbose_name_plural = _('Task Templates')
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Task(TimeStampedModel, SoftDeleteModel):
    """Main task model with comprehensive features."""
    
    title = models.CharField(
        max_length=200,
        db_index=True,
        help_text=_("Task title")
    )
    description = models.TextField(
        help_text=_("Detailed task description")
    )
    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.TODO,
        db_index=True,
        help_text=_("Current task status")
    )
    priority = models.CharField(
        max_length=20,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
        db_index=True,
        help_text=_("Task priority level")
    )
    due_date = models.DateTimeField(
        validators=[validate_due_date],
        db_index=True,
        help_text=_("Task due date and time")
    )
    estimated_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[validate_estimated_hours, MinValueValidator(0.1)],
        help_text=_("Estimated hours to complete the task")
    )
    actual_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True,
        help_text=_("Actual hours spent on the task")
    )
    
    # Relationships
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_tasks',
        help_text=_("User who created the task")
    )
    assigned_to = models.ManyToManyField(
        User,
        through='TaskAssignment',
        related_name='assigned_tasks',
        blank=True,
        help_text=_("Users assigned to this task")
    )
    tags = models.ManyToManyField(
        Tag,
        blank=True,
        help_text=_("Tags associated with this task")
    )
    parent_task = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subtasks',
        help_text=_("Parent task if this is a subtask")
    )
    
    # Metadata and tracking
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional metadata in JSON format")
    )
    search_vector = SearchVectorField(null=True, blank=True)
    
    # Progress tracking
    completion_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_("Task completion percentage")
    )
    
    # Business logic fields
    is_recurring = models.BooleanField(
        default=False,
        help_text=_("Whether this is a recurring task")
    )
    recurrence_pattern = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Recurrence pattern configuration")
    )
    
    # Managers
    objects = TaskManager()
    active_objects = ActiveTaskManager()
    
    class Meta:
        db_table = 'tasks_task'
        verbose_name = _('Task')
        verbose_name_plural = _('Tasks')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['due_date', 'status']),
            models.Index(fields=['parent_task']),
            GinIndex(fields=['search_vector']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(completion_percentage__gte=0) & models.Q(completion_percentage__lte=100),
                name='valid_completion_percentage'
            ),
            models.CheckConstraint(
                check=models.Q(estimated_hours__gt=0),
                name='positive_estimated_hours'
            ),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    def clean(self):
        super().clean()
        
        # Prevent self-referencing parent task
        if self.parent_task and self.parent_task.pk == self.pk:
            raise ValidationError(_("A task cannot be its own parent."))
        
        # Validate circular dependencies
        if self.parent_task:
            self._validate_no_circular_dependency()
    
    def _validate_no_circular_dependency(self):
        """Validate that there are no circular dependencies in parent-child relationships."""
        visited = set()
        current = self.parent_task
        
        while current:
            if current.pk in visited:
                raise ValidationError(_("Circular dependency detected in task hierarchy."))
            visited.add(current.pk)
            current = current.parent_task
    
    def save(self, *args, **kwargs):
        # Auto-complete parent task when all subtasks are completed
        if self.status == TaskStatus.DONE and self.parent_task:
            with transaction.atomic():
                super().save(*args, **kwargs)
                self._check_parent_completion()
        else:
            super().save(*args, **kwargs)
    
    def _check_parent_completion(self):
        """Check if parent task should be auto-completed."""
        if not self.parent_task:
            return
            
        all_subtasks = self.parent_task.subtasks.filter(is_deleted=False)
        completed_subtasks = all_subtasks.filter(status=TaskStatus.DONE)
        
        if all_subtasks.count() == completed_subtasks.count() and all_subtasks.count() > 0:
            self.parent_task.status = TaskStatus.DONE
            self.parent_task.completion_percentage = 100
            self.parent_task.save(update_fields=['status', 'completion_percentage'])
    
    @property
    def is_overdue(self):
        """Check if task is overdue."""
        from django.utils import timezone
        return self.due_date < timezone.now() and self.status != TaskStatus.DONE
    
    @property
    def has_subtasks(self):
        """Check if task has subtasks."""
        return self.subtasks.filter(is_deleted=False).exists()
    
    @property
    def subtask_count(self):
        """Get count of subtasks."""
        return self.subtasks.filter(is_deleted=False).count()
    
    @property
    def completed_subtask_count(self):
        """Get count of completed subtasks."""
        return self.subtasks.filter(is_deleted=False, status=TaskStatus.DONE).count()
    
    def calculate_progress(self):
        """Calculate task progress based on subtasks or manual input."""
        if self.has_subtasks:
            total = self.subtask_count
            completed = self.completed_subtask_count
            return int((completed / total) * 100) if total > 0 else 0
        return self.completion_percentage
    
    def get_all_assignees(self):
        """Get all users assigned to this task."""
        return self.assigned_to.all()
    
    def get_active_assignments(self):
        """Get active task assignments."""
        return self.assignments.filter(is_active=True)


class TaskAssignment(TimeStampedModel):
    """Through model for Task-User many-to-many relationship with additional fields."""
    
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='task_assignments'
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='assigned_tasks_by_me',
        help_text=_("User who made the assignment")
    )
    assigned_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("When the assignment was made")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this assignment is active")
    )
    role = models.CharField(
        max_length=50,
        default='assignee',
        help_text=_("Role of the user in this task")
    )
    
    class Meta:
        db_table = 'tasks_assignment'
        verbose_name = _('Task Assignment')
        verbose_name_plural = _('Task Assignments')
        unique_together = [['task', 'user']]
        indexes = [
            models.Index(fields=['task', 'is_active']),
            models.Index(fields=['user', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.user.username} -> {self.task.title}"


class Comment(TimeStampedModel, SoftDeleteModel):
    """Comment model for task discussions."""
    
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='comments',
        help_text=_("Task this comment belongs to")
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='task_comments',
        help_text=_("User who wrote the comment")
    )
    content = models.TextField(
        help_text=_("Comment content")
    )
    parent_comment = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
        help_text=_("Parent comment if this is a reply")
    )
    is_internal = models.BooleanField(
        default=False,
        help_text=_("Whether this comment is internal only")
    )
    
    class Meta:
        db_table = 'tasks_comment'
        verbose_name = _('Comment')
        verbose_name_plural = _('Comments')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'created_at']),
            models.Index(fields=['author']),
        ]
    
    def __str__(self):
        return f"Comment by {self.author.username} on {self.task.title}"
    
    @property
    def is_reply(self):
        """Check if this comment is a reply."""
        return self.parent_comment is not None


class TaskHistory(TimeStampedModel):
    """Audit log for task changes."""
    
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='history',
        help_text=_("Task this history entry belongs to")
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='task_history',
        help_text=_("User who made the change")
    )
    action = models.CharField(
        max_length=50,
        db_index=True,
        help_text=_("Type of action performed")
    )
    field_name = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Name of the field that was changed")
    )
    old_value = models.TextField(
        blank=True,
        help_text=_("Previous value")
    )
    new_value = models.TextField(
        blank=True,
        help_text=_("New value")
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional change metadata")
    )
    
    class Meta:
        db_table = 'tasks_history'
        verbose_name = _('Task History')
        verbose_name_plural = _('Task Histories')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'created_at']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action']),
        ]
    
    def __str__(self):
        return f"{self.user.username} {self.action} {self.task.title}"


class Team(TimeStampedModel, SoftDeleteModel):
    """Team model for organizing users and tasks."""
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Team name")
    )
    description = models.TextField(
        blank=True,
        help_text=_("Team description")
    )
    members = models.ManyToManyField(
        User,
        through='TeamMembership',
        related_name='teams',
        blank=True,
        help_text=_("Team members")
    )
    lead = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='led_teams',
        help_text=_("Team lead")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this team is active")
    )
    
    class Meta:
        db_table = 'tasks_team'
        verbose_name = _('Team')
        verbose_name_plural = _('Teams')
        ordering = ['name']
    
    def __str__(self):
        return self.name


class TeamMembership(TimeStampedModel):
    """Through model for Team-User relationship."""
    
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(
        max_length=50,
        default='member',
        help_text=_("User's role in the team")
    )
    joined_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("When the user joined the team")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this membership is active")
    )
    
    class Meta:
        db_table = 'tasks_team_membership'
        verbose_name = _('Team Membership')
        verbose_name_plural = _('Team Memberships')
        unique_together = [['team', 'user']]
    
    def __str__(self):
        return f"{self.user.username} in {self.team.name}"
