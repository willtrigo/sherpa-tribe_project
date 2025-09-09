"""
Authentication models for Enterprise Task Management System.

This module contains the core authentication models including
custom User model extending Django's AbstractUser with additional
enterprise features and audit capabilities.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel, SoftDeleteMixin


class UserManager(BaseUserManager):
    """
    Custom user manager with enhanced functionality for enterprise features.
    
    Provides methods for creating regular users and superusers with
    proper validation and default settings.
    """
    
    def _create_user(self, email: str, password: str, **extra_fields) -> 'User':
        """
        Create and save a user with the given email and password.
        
        Args:
            email: User's email address
            password: User's password
            **extra_fields: Additional user fields
            
        Returns:
            User: Created user instance
            
        Raises:
            ValueError: If email is not provided
        """
        if not email:
            raise ValueError(_('The Email field must be set'))
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_user(self, email: str, password: str = None, **extra_fields) -> 'User':
        """
        Create and return a regular user with given email and password.
        
        Args:
            email: User's email address
            password: User's password
            **extra_fields: Additional user fields
            
        Returns:
            User: Created user instance
        """
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_active', True)
        return self._create_user(email, password, **extra_fields)
    
    def create_superuser(self, email: str, password: str = None, **extra_fields) -> 'User':
        """
        Create and return a superuser with given email and password.
        
        Args:
            email: User's email address
            password: User's password
            **extra_fields: Additional user fields
            
        Returns:
            User: Created superuser instance
            
        Raises:
            ValueError: If is_staff or is_superuser is not True
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
            
        return self._create_user(email, password, **extra_fields)
    
    def active_users(self):
        """
        Return queryset of active users only.
        
        Returns:
            QuerySet: Filtered queryset of active users
        """
        return self.get_queryset().filter(is_active=True, is_deleted=False)
    
    def inactive_users(self):
        """
        Return queryset of inactive users only.
        
        Returns:
            QuerySet: Filtered queryset of inactive users
        """
        return self.get_queryset().filter(is_active=False)


class User(AbstractUser, BaseModel, SoftDeleteMixin):
    """
    Custom User model extending AbstractUser with enterprise features.
    
    Provides additional fields for enterprise task management including
    department, role, contact information, and audit trail capabilities.
    Uses email as the primary authentication field instead of username.
    """
    
    class Role(models.TextChoices):
        """User role choices for role-based access control."""
        ADMIN = 'admin', _('Administrator')
        MANAGER = 'manager', _('Project Manager')
        TEAM_LEAD = 'team_lead', _('Team Lead')
        DEVELOPER = 'developer', _('Developer')
        ANALYST = 'analyst', _('Business Analyst')
        TESTER = 'tester', _('Quality Tester')
        VIEWER = 'viewer', _('Viewer')
    
    class Status(models.TextChoices):
        """User account status choices."""
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')
        SUSPENDED = 'suspended', _('Suspended')
        PENDING = 'pending', _('Pending Approval')
    
    class Department(models.TextChoices):
        """Department choices for organizational structure."""
        ENGINEERING = 'engineering', _('Engineering')
        PRODUCT = 'product', _('Product Management')
        DESIGN = 'design', _('Design')
        MARKETING = 'marketing', _('Marketing')
        SALES = 'sales', _('Sales')
        SUPPORT = 'support', _('Customer Support')
        HR = 'hr', _('Human Resources')
        FINANCE = 'finance', _('Finance')
        OPERATIONS = 'operations', _('Operations')
        OTHER = 'other', _('Other')
    
    # Authentication fields
    username = None  # Remove username field
    email = models.EmailField(
        _('email address'),
        unique=True,
        help_text=_('Required. Enter a valid email address.')
    )
    
    # Personal information
    first_name = models.CharField(_('first name'), max_length=150)
    last_name = models.CharField(_('last name'), max_length=150)
    
    phone_validator = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message=_('Phone number must be entered in the format: "+999999999". Up to 15 digits allowed.')
    )
    phone_number = models.CharField(
        _('phone number'),
        validators=[phone_validator],
        max_length=17,
        blank=True,
        null=True
    )
    
    # Professional information
    role = models.CharField(
        _('role'),
        max_length=20,
        choices=Role.choices,
        default=Role.DEVELOPER,
        help_text=_('User role for permissions and access control')
    )
    
    department = models.CharField(
        _('department'),
        max_length=20,
        choices=Department.choices,
        default=Department.ENGINEERING,
        help_text=_('User department for organizational structure')
    )
    
    job_title = models.CharField(
        _('job title'),
        max_length=100,
        blank=True,
        help_text=_('Official job title')
    )
    
    employee_id = models.CharField(
        _('employee ID'),
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        help_text=_('Unique employee identifier')
    )
    
    # Status and preferences
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        help_text=_('Current account status')
    )
    
    timezone = models.CharField(
        _('timezone'),
        max_length=50,
        default='UTC',
        help_text=_('User timezone for scheduling and notifications')
    )
    
    avatar = models.ImageField(
        _('avatar'),
        upload_to='avatars/%Y/%m/',
        blank=True,
        null=True,
        help_text=_('Profile picture')
    )
    
    # Capacity and workload management
    weekly_capacity_hours = models.DecimalField(
        _('weekly capacity hours'),
        max_digits=5,
        decimal_places=2,
        default=40.00,
        help_text=_('Standard weekly working hours')
    )
    
    current_workload_hours = models.DecimalField(
        _('current workload hours'),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text=_('Current assigned workload in hours')
    )
    
    # Professional details
    skills = models.JSONField(
        _('skills'),
        default=list,
        blank=True,
        help_text=_('List of user skills and competencies')
    )
    
    bio = models.TextField(
        _('biography'),
        blank=True,
        help_text=_('User biography or description')
    )
    
    # Authentication and security
    email_verified = models.BooleanField(
        _('email verified'),
        default=False,
        help_text=_('Whether user email has been verified')
    )
    
    phone_verified = models.BooleanField(
        _('phone verified'),
        default=False,
        help_text=_('Whether user phone number has been verified')
    )
    
    two_factor_enabled = models.BooleanField(
        _('two factor authentication enabled'),
        default=False,
        help_text=_('Whether 2FA is enabled for this account')
    )
    
    failed_login_attempts = models.PositiveIntegerField(
        _('failed login attempts'),
        default=0,
        help_text=_('Number of consecutive failed login attempts')
    )
    
    account_locked_until = models.DateTimeField(
        _('account locked until'),
        blank=True,
        null=True,
        help_text=_('Account lockout expiration time')
    )
    
    # Activity tracking
    last_login_ip = models.GenericIPAddressField(
        _('last login IP'),
        blank=True,
        null=True,
        help_text=_('IP address of last successful login')
    )
    
    last_activity = models.DateTimeField(
        _('last activity'),
        auto_now=True,
        help_text=_('Timestamp of last user activity')
    )
    
    # Notification preferences
    notification_preferences = models.JSONField(
        _('notification preferences'),
        default=dict,
        blank=True,
        help_text=_('User notification settings and preferences')
    )
    
    # Metadata
    metadata = models.JSONField(
        _('metadata'),
        default=dict,
        blank=True,
        help_text=_('Additional user metadata')
    )
    
    # Manager
    objects = UserManager()
    
    # Configuration
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    class Meta:
        db_table = 'auth_user'
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        ordering = ['last_name', 'first_name']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['employee_id']),
            models.Index(fields=['role', 'department']),
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(weekly_capacity_hours__gte=0),
                name='positive_weekly_capacity'
            ),
            models.CheckConstraint(
                check=models.Q(current_workload_hours__gte=0),
                name='positive_current_workload'
            ),
            models.CheckConstraint(
                check=models.Q(failed_login_attempts__gte=0),
                name='positive_failed_attempts'
            ),
        ]
    
    def __str__(self) -> str:
        """
        Return string representation of user.
        
        Returns:
            str: User's full name and email
        """
        return f"{self.get_full_name()} <{self.email}>"
    
    def __repr__(self) -> str:
        """
        Return detailed string representation for debugging.
        
        Returns:
            str: Detailed user representation
        """
        return f"<User: {self.email} ({self.role})>"
    
    @property
    def full_name(self) -> str:
        """
        Get user's full name.
        
        Returns:
            str: Concatenated first and last name
        """
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def initials(self) -> str:
        """
        Get user's initials.
        
        Returns:
            str: First letter of first and last name
        """
        first_initial = self.first_name[0].upper() if self.first_name else ''
        last_initial = self.last_name[0].upper() if self.last_name else ''
        return f"{first_initial}{last_initial}"
    
    @property
    def is_account_locked(self) -> bool:
        """
        Check if account is currently locked.
        
        Returns:
            bool: True if account is locked, False otherwise
        """
        if not self.account_locked_until:
            return False
        return timezone.now() < self.account_locked_until
    
    @property
    def available_capacity(self) -> float:
        """
        Calculate available capacity in hours.
        
        Returns:
            float: Available hours (capacity - current workload)
        """
        return float(self.weekly_capacity_hours - self.current_workload_hours)
    
    @property
    def workload_percentage(self) -> float:
        """
        Calculate current workload as percentage of capacity.
        
        Returns:
            float: Workload percentage (0-100+)
        """
        if self.weekly_capacity_hours == 0:
            return 0.0
        return float(self.current_workload_hours / self.weekly_capacity_hours * 100)
    
    @property
    def is_overloaded(self) -> bool:
        """
        Check if user is overloaded (workload > capacity).
        
        Returns:
            bool: True if overloaded, False otherwise
        """
        return self.current_workload_hours > self.weekly_capacity_hours
    
    def get_full_name(self) -> str:
        """
        Return user's full name.
        
        Returns:
            str: Full name or email if name is not available
        """
        full_name = self.full_name
        return full_name if full_name else self.email
    
    def get_short_name(self) -> str:
        """
        Return user's short name (first name).
        
        Returns:
            str: First name or email if first name is not available
        """
        return self.first_name if self.first_name else self.email
    
    def update_last_activity(self) -> None:
        """Update last activity timestamp to current time."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])
    
    def lock_account(self, duration_minutes: int = 30) -> None:
        """
        Lock user account for specified duration.
        
        Args:
            duration_minutes: Duration to lock account in minutes
        """
        self.account_locked_until = timezone.now() + timezone.timedelta(minutes=duration_minutes)
        self.save(update_fields=['account_locked_until'])
    
    def unlock_account(self) -> None:
        """Unlock user account by clearing lock timestamp and failed attempts."""
        self.account_locked_until = None
        self.failed_login_attempts = 0
        self.save(update_fields=['account_locked_until', 'failed_login_attempts'])
    
    def increment_failed_login(self, max_attempts: int = 5) -> None:
        """
        Increment failed login attempts and lock account if threshold reached.
        
        Args:
            max_attempts: Maximum allowed failed attempts before locking
        """
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.lock_account()
        else:
            self.save(update_fields=['failed_login_attempts'])
    
    def reset_failed_login_attempts(self) -> None:
        """Reset failed login attempts counter."""
        if self.failed_login_attempts > 0:
            self.failed_login_attempts = 0
            self.save(update_fields=['failed_login_attempts'])
    
    def update_workload(self, hours_delta: float) -> None:
        """
        Update current workload by adding/subtracting hours.
        
        Args:
            hours_delta: Hours to add (positive) or subtract (negative)
        """
        new_workload = max(0, self.current_workload_hours + hours_delta)
        self.current_workload_hours = new_workload
        self.save(update_fields=['current_workload_hours'])
    
    def get_notification_preference(self, preference_key: str, default=None):
        """
        Get specific notification preference.
        
        Args:
            preference_key: The preference key to lookup
            default: Default value if key not found
            
        Returns:
            Any: Preference value or default
        """
        return self.notification_preferences.get(preference_key, default)
    
    def set_notification_preference(self, preference_key: str, value) -> None:
        """
        Set specific notification preference.
        
        Args:
            preference_key: The preference key to set
            value: The preference value
        """
        self.notification_preferences[preference_key] = value
        self.save(update_fields=['notification_preferences'])
    
    def has_skill(self, skill: str) -> bool:
        """
        Check if user has specific skill.
        
        Args:
            skill: Skill name to check
            
        Returns:
            bool: True if user has skill, False otherwise
        """
        return skill.lower() in [s.lower() for s in self.skills]
    
    def add_skill(self, skill: str) -> None:
        """
        Add skill to user's skill list.
        
        Args:
            skill: Skill name to add
        """
        if not self.has_skill(skill):
            self.skills.append(skill)
            self.save(update_fields=['skills'])
    
    def remove_skill(self, skill: str) -> None:
        """
        Remove skill from user's skill list.
        
        Args:
            skill: Skill name to remove
        """
        self.skills = [s for s in self.skills if s.lower() != skill.lower()]
        self.save(update_fields=['skills'])
    
    def can_be_assigned_hours(self, hours: float) -> bool:
        """
        Check if user can be assigned additional hours.
        
        Args:
            hours: Hours to potentially assign
            
        Returns:
            bool: True if user can handle additional hours
        """
        return (self.current_workload_hours + hours) <= self.weekly_capacity_hours
    
    def get_teams(self):
        """
        Get teams this user belongs to.
        
        Returns:
            QuerySet: Teams the user is a member of
        """
        # This will be implemented when Team model is created
        # return self.team_memberships.select_related('team')
        pass
    
    def save(self, *args, **kwargs) -> None:
        """
        Override save method to handle additional logic.
        
        Args:
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments
        """
        # Ensure email is lowercase
        if self.email:
            self.email = self.email.lower().strip()
        
        # Generate employee_id if not provided
        if not self.employee_id and self.pk is None:
            # This would typically be generated by a service
            # For now, we'll leave it to be set manually or by signals
            pass
        
        # Set username to email for compatibility
        if not self.username and self.email:
            self.username = self.email
        
        super().save(*args, **kwargs)


class UserSession(BaseModel):
    """
    Model to track user sessions for security and analytics.
    
    Stores session information including IP address, user agent,
    and session lifecycle for security monitoring.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sessions',
        verbose_name=_('user')
    )
    
    session_key = models.CharField(
        _('session key'),
        max_length=40,
        unique=True,
        help_text=_('Django session key')
    )
    
    ip_address = models.GenericIPAddressField(
        _('IP address'),
        help_text=_('IP address of the session')
    )
    
    user_agent = models.TextField(
        _('user agent'),
        blank=True,
        help_text=_('Browser user agent string')
    )
    
    location = models.JSONField(
        _('location'),
        default=dict,
        blank=True,
        help_text=_('Geographical location data')
    )
    
    is_active = models.BooleanField(
        _('is active'),
        default=True,
        help_text=_('Whether session is currently active')
    )
    
    last_activity = models.DateTimeField(
        _('last activity'),
        auto_now=True,
        help_text=_('Timestamp of last session activity')
    )
    
    expires_at = models.DateTimeField(
        _('expires at'),
        help_text=_('Session expiration timestamp')
    )
    
    class Meta:
        db_table = 'auth_user_session'
        verbose_name = _('User Session')
        verbose_name_plural = _('User Sessions')
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['session_key']),
            models.Index(fields=['ip_address']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self) -> str:
        """
        Return string representation of session.
        
        Returns:
            str: Session description with user and IP
        """
        return f"{self.user.email} - {self.ip_address}"
    
    @property
    def is_expired(self) -> bool:
        """
        Check if session is expired.
        
        Returns:
            bool: True if session is expired
        """
        return timezone.now() > self.expires_at
    
    def deactivate(self) -> None:
        """Deactivate the session."""
        self.is_active = False
        self.save(update_fields=['is_active'])
