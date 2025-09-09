from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampMixin, SoftDeleteMixin


class User(AbstractUser, TimestampMixin, SoftDeleteMixin):
    """
    Custom user model extending Django's AbstractUser.
    """

    class Role(models.TextChoices):
        ADMIN = 'admin', _('Administrator')
        MANAGER = 'manager', _('Manager')
        DEVELOPER = 'developer', _('Developer')
        TESTER = 'tester', _('Tester')
        VIEWER = 'viewer', _('Viewer')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')
        SUSPENDED = 'suspended', _('Suspended')

    # Personal information
    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message=_('Phone number must be entered in the format: "+999999999". Up to 15 digits allowed.')
    )

    phone_number = models.CharField(
        validators=[phone_regex], 
        max_length=17, 
        blank=True,
        help_text=_('Contact phone number')
    )

    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        help_text=_('User profile picture')
    )

    bio = models.TextField(
        max_length=500,
        blank=True,
        help_text=_('Brief biography or description')
    )

    # Work-related fields
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.DEVELOPER,
        help_text=_('User role in the system')
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        help_text=_('Current user status')
    )

    department = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('Department or division')
    )

    job_title = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('Job title or position')
    )

    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        help_text=_('Direct manager')
    )

    # Preferences
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        help_text=_('User timezone')
    )

    language = models.CharField(
        max_length=10,
        default='en',
        help_text=_('Preferred language')
    )

    # Notification preferences
    email_notifications = models.BooleanField(
        default=True,
        help_text=_('Receive email notifications')
    )

    task_assignment_notifications = models.BooleanField(
        default=True,
        help_text=_('Notify when assigned to tasks')
    )

    task_due_notifications = models.BooleanField(
        default=True,
        help_text=_('Notify when tasks are due')
    )

    # Work capacity
    max_concurrent_tasks = models.PositiveIntegerField(
        default=5,
        help_text=_('Maximum number of concurrent tasks')
    )

    working_hours_per_day = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text=_('Standard working hours per day')
    )

    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Additional user metadata')
    )

    objects = models.Manager()  # Default manager

    class Meta:
        db_table = 'users'
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        ordering = ['username']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role']),
            models.Index(fields=['status']),
            models.Index(fields=['department']),
        ]

    def __str__(self):
        return f"{self.get_full_name() or self.username}"

    @property
    def full_name(self):
        """Return the user's full name."""
        return self.get_full_name() or self.username

    @property
    def is_manager(self):
        """Check if user has manager role or above."""
        return self.role in [self.Role.ADMIN, self.Role.MANAGER]

    @property
    def is_admin(self):
        """Check if user has admin role."""
        return self.role == self.Role.ADMIN

    @property
    def active_tasks_count(self):
        """Get count of active tasks assigned to user."""
        return self.assigned_tasks.filter(
            status__in=['todo', 'in_progress'],
            is_archived=False
        ).count()

    def can_be_assigned_more_tasks(self):
        """Check if user can be assigned more tasks."""
        return self.active_tasks_count < self.max_concurrent_tasks

    def get_workload_percentage(self):
        """Calculate current workload as percentage."""
        if self.max_concurrent_tasks == 0:
            return 100
        return (self.active_tasks_count / self.max_concurrent_tasks) * 100


class Team(TimestampMixin, SoftDeleteMixin):
    """
    Team model for organizing users into groups.
    """
    
    class TeamType(models.TextChoices):
        DEVELOPMENT = 'development', _('Development')
        TESTING = 'testing', _('Testing')
        DESIGN = 'design', _('Design')
        MANAGEMENT = 'management', _('Management')
        SUPPORT = 'support', _('Support')
        OTHER = 'other', _('Other')

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_('Team name')
    )

    description = models.TextField(
        blank=True,
        help_text=_('Team description and purpose')
    )

    team_type = models.CharField(
        max_length=20,
        choices=TeamType.choices,
        default=TeamType.DEVELOPMENT,
        help_text=_('Type of team')
    )

    lead = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='led_teams',
        help_text=_('Team leader')
    )

    members = models.ManyToManyField(
        'users.User',
        through='TeamMembership',
        related_name='teams',
        blank=True,
        help_text=_('Team members')
    )

    # Team settings
    is_active = models.BooleanField(
        default=True,
        help_text=_('Whether the team is active')
    )

    max_members = models.PositiveIntegerField(
        default=10,
        help_text=_('Maximum number of team members')
    )

    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Additional team metadata')
    )

    class Meta:
        db_table = 'teams'
        verbose_name = _('Team')
        verbose_name_plural = _('Teams')
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['team_type']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        """Get count of active team members."""
        return self.members.filter(is_active=True).count()

    @property
    def can_add_members(self):
        """Check if team can accept more members."""
        return self.member_count < self.max_members

    def get_active_tasks_count(self):
        """Get count of active tasks assigned to team members."""
        return self.members.aggregate(
            total=models.Count(
                'assigned_tasks',
                filter=models.Q(
                    assigned_tasks__status__in=['todo', 'in_progress'],
                    assigned_tasks__is_archived=False
                )
            )
        )['total'] or 0


class TeamMembership(TimestampMixin):
    """
    Through model for Team-User relationship with additional fields.
    """

    class Role(models.TextChoices):
        LEADER = 'leader', _('Leader')
        SENIOR = 'senior', _('Senior Member')
        MEMBER = 'member', _('Member')
        JUNIOR = 'junior', _('Junior Member')
        INTERN = 'intern', _('Intern')

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='team_memberships'
    )

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='memberships'
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
        help_text=_('Role within the team')
    )

    joined_date = models.DateField(
        auto_now_add=True,
        help_text=_('Date when user joined the team')
    )

    is_active = models.BooleanField(
        default=True,
        help_text=_('Whether the membership is active')
    )

    # Performance tracking
    tasks_completed = models.PositiveIntegerField(
        default=0,
        help_text=_('Number of tasks completed as team member')
    )

    class Meta:
        db_table = 'team_memberships'
        verbose_name = _('Team Membership')
        verbose_name_plural = _('Team Memberships')
        unique_together = ('user', 'team')
        ordering = ['-joined_date']
        indexes = [
            models.Index(fields=['user', 'team']),
            models.Index(fields=['role']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.user} - {self.team} ({self.role})"
