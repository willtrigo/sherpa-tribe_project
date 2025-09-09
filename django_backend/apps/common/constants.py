"""
Common constants for the task management system.

Defines system-wide constants and enumerations.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


# HTTP Status Code Messages
HTTP_STATUS_MESSAGES = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

# Common Choice Fields
class Priority(models.TextChoices):
    """Priority levels for tasks and other entities."""

    CRITICAL = 'critical', _('Critical')
    HIGH = 'high', _('High')
    MEDIUM = 'medium', _('Medium')
    LOW = 'low', _('Low')
    MINIMAL = 'minimal', _('Minimal')


class Status(models.TextChoices):
    """Generic status choices."""

    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    PENDING = 'pending', _('Pending')
    COMPLETED = 'completed', _('Completed')
    CANCELLED = 'cancelled', _('Cancelled')
    ARCHIVED = 'archived', _('Archived')


class TaskStatus(models.TextChoices):
    """Task-specific status choices."""

    BACKLOG = 'backlog', _('Backlog')
    TODO = 'todo', _('To Do')
    IN_PROGRESS = 'in_progress', _('In Progress')
    IN_REVIEW = 'in_review', _('In Review')
    BLOCKED = 'blocked', _('Blocked')
    TESTING = 'testing', _('Testing')
    DONE = 'done', _('Done')
    CANCELLED = 'cancelled', _('Cancelled')


class UserRole(models.TextChoices):
    """User role choices."""

    ADMIN = 'admin', _('Administrator')
    MANAGER = 'manager', _('Manager')
    TEAM_LEAD = 'team_lead', _('Team Lead')
    DEVELOPER = 'developer', _('Developer')
    DESIGNER = 'designer', _('Designer')
    TESTER = 'tester', _('Tester')
    VIEWER = 'viewer', _('Viewer')


class NotificationType(models.TextChoices):
    """Notification type choices."""

    INFO = 'info', _('Information')
    SUCCESS = 'success', _('Success')
    WARNING = 'warning', _('Warning')
    ERROR = 'error', _('Error')
    REMINDER = 'reminder', _('Reminder')
    ASSIGNMENT = 'assignment', _('Assignment')
    COMMENT = 'comment', _('Comment')
    STATUS_CHANGE = 'status_change', _('Status Change')
    DUE_DATE = 'due_date', _('Due Date')
    OVERDUE = 'overdue', _('Overdue')


class NotificationChannel(models.TextChoices):
    """Notification delivery channel choices."""

    EMAIL = 'email', _('Email')
    SMS = 'sms', _('SMS')
    PUSH = 'push', _('Push Notification')
    IN_APP = 'in_app', _('In-App')
    WEBHOOK = 'webhook', _('Webhook')
    SLACK = 'slack', _('Slack')
    TEAMS = 'teams', _('Microsoft Teams')


class FileType(models.TextChoices):
    """File type choices."""

    IMAGE = 'image', _('Image')
    DOCUMENT = 'document', _('Document')
    SPREADSHEET = 'spreadsheet', _('Spreadsheet')
    PRESENTATION = 'presentation', _('Presentation')
    ARCHIVE = 'archive', _('Archive')
    VIDEO = 'video', _('Video')
    AUDIO = 'audio', _('Audio')
    OTHER = 'other', _('Other')


class TimeUnit(models.TextChoices):
    """Time unit choices."""

    MINUTES = 'minutes', _('Minutes')
    HOURS = 'hours', _('Hours')
    DAYS = 'days', _('Days')
    WEEKS = 'weeks', _('Weeks')
    MONTHS = 'months', _('Months')
    YEARS = 'years', _('Years')


class RecurrencePattern(models.TextChoices):
    """Recurrence pattern choices."""

    DAILY = 'daily', _('Daily')
    WEEKLY = 'weekly', _('Weekly')
    BIWEEKLY = 'biweekly', _('Bi-weekly')
    MONTHLY = 'monthly', _('Monthly')
    QUARTERLY = 'quarterly', _('Quarterly')
    ANNUALLY = 'annually', _('Annually')
    CUSTOM = 'custom', _('Custom')


class WorkflowState(models.TextChoices):
    """Workflow state choices."""

    DRAFT = 'draft', _('Draft')
    ACTIVE = 'active', _('Active')
    PAUSED = 'paused', _('Paused')
    COMPLETED = 'completed', _('Completed')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')


# Numeric Constants
class Limits:
    """System limits and constraints."""

    # String length limits
    MAX_NAME_LENGTH = 200
    MAX_TITLE_LENGTH = 255
    MAX_SLUG_LENGTH = 100
    MAX_EMAIL_LENGTH = 254
    MAX_PHONE_LENGTH = 20
    MAX_URL_LENGTH = 2000
    MAX_DESCRIPTION_LENGTH = 5000

    # File size limits (in bytes)
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
    MAX_DOCUMENT_SIZE = 25 * 1024 * 1024  # 25 MB
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB

    # Pagination limits
    MIN_PAGE_SIZE = 1
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    # Task limits
    MAX_TASK_HIERARCHY_DEPTH = 5
    MAX_ASSIGNEES_PER_TASK = 10
    MAX_TAGS_PER_TASK = 20
    MAX_COMMENTS_PER_TASK = 1000

    # Time limits
    MIN_ESTIMATED_HOURS = 0.25  # 15 minutes
    MAX_ESTIMATED_HOURS = 1000  # ~6 months full-time

    # User limits
    MAX_TEAMS_PER_USER = 50
    MAX_PROJECTS_PER_USER = 100


class Defaults:
    """Default values for various fields."""

    # Task defaults
    DEFAULT_PRIORITY = Priority.MEDIUM
    DEFAULT_TASK_STATUS = TaskStatus.BACKLOG
    DEFAULT_ESTIMATED_HOURS = 1.0

    # User defaults
    DEFAULT_USER_ROLE = UserRole.DEVELOPER
    DEFAULT_TIMEZONE = 'UTC'
    DEFAULT_LANGUAGE = 'en'

    # Notification defaults
    DEFAULT_NOTIFICATION_CHANNEL = NotificationChannel.EMAIL

    # Pagination defaults
    DEFAULT_PAGE_SIZE = 20

    # Cache timeouts (in seconds)
    SHORT_CACHE_TIMEOUT = 300  # 5 minutes
    MEDIUM_CACHE_TIMEOUT = 1800  # 30 minutes
    LONG_CACHE_TIMEOUT = 3600  # 1 hour
    DAILY_CACHE_TIMEOUT = 86400  # 24 hours


class RegexPatterns:
    """Common regex patterns."""

    # Basic patterns
    EMAIL = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    PHONE_US = r'^\+?1?-?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})$'
    PHONE_INTERNATIONAL = r'^\+?[1-9]\d{1,14}$'

    # Username and slug patterns
    USERNAME = r'^[a-zA-Z0-9._-]{3,30}$'
    SLUG = r'^[a-z0-9-]+$'

    # Color patterns
    HEX_COLOR = r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$'
    RGB_COLOR = r'^rgb\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*\)$'

    # Version patterns
    SEMANTIC_VERSION = r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'

    # URL patterns
    URL_SLUG = r'^[\w-]+$'
    DOMAIN = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'


class ErrorCodes:
    """Application-specific error codes."""

    # Validation errors
    VALIDATION_FAILED = 'validation_failed'
    REQUIRED_FIELD = 'required_field'
    INVALID_FORMAT = 'invalid_format'
    INVALID_CHOICE = 'invalid_choice'
    UNIQUE_CONSTRAINT = 'unique_constraint'

    # Authentication errors
    AUTHENTICATION_FAILED = 'authentication_failed'
    INVALID_CREDENTIALS = 'invalid_credentials'
    TOKEN_EXPIRED = 'token_expired'
    TOKEN_INVALID = 'token_invalid'

    # Permission errors
    PERMISSION_DENIED = 'permission_denied'
    INSUFFICIENT_PRIVILEGES = 'insufficient_privileges'

    # Resource errors
    RESOURCE_NOT_FOUND = 'resource_not_found'
    RESOURCE_CONFLICT = 'resource_conflict'
    RESOURCE_LOCKED = 'resource_locked'

    # Business logic errors
    INVALID_STATE_TRANSITION = 'invalid_state_transition'
    DEADLINE_PASSED = 'deadline_passed'
    CAPACITY_EXCEEDED = 'capacity_exceeded'
    DEPENDENCY_VIOLATION = 'dependency_violation'

    # System errors
    INTERNAL_ERROR = 'internal_error'
    SERVICE_UNAVAILABLE = 'service_unavailable'
    RATE_LIMIT_EXCEEDED = 'rate_limit_exceeded'
    MAINTENANCE_MODE = 'maintenance_mode'


class EventTypes:
    """Event types for system logging and notifications."""

    # User events
    USER_CREATED = 'user.created'
    USER_UPDATED = 'user.updated'
    USER_DELETED = 'user.deleted'
    USER_LOGGED_IN = 'user.logged_in'
    USER_LOGGED_OUT = 'user.logged_out'

    # Task events
    TASK_CREATED = 'task.created'
    TASK_UPDATED = 'task.updated'
    TASK_DELETED = 'task.deleted'
    TASK_ASSIGNED = 'task.assigned'
    TASK_UNASSIGNED = 'task.unassigned'
    TASK_STATUS_CHANGED = 'task.status_changed'
    TASK_COMMENTED = 'task.commented'
    TASK_DUE_SOON = 'task.due_soon'
    TASK_OVERDUE = 'task.overdue'
    TASK_COMPLETED = 'task.completed'

    # Team events
    TEAM_CREATED = 'team.created'
    TEAM_UPDATED = 'team.updated'
    TEAM_MEMBER_ADDED = 'team.member_added'
    TEAM_MEMBER_REMOVED = 'team.member_removed'

    # System events
    SYSTEM_STARTUP = 'system.startup'
    SYSTEM_SHUTDOWN = 'system.shutdown'
    BACKUP_CREATED = 'system.backup_created'
    MAINTENANCE_START = 'system.maintenance_start'
    MAINTENANCE_END = 'system.maintenance_end'


# File extensions by category
FILE_EXTENSIONS = {
    FileType.IMAGE: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico'],
    FileType.DOCUMENT: ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt', 'pages'],
    FileType.SPREADSHEET: ['xls', 'xlsx', 'csv', 'ods', 'numbers'],
    FileType.PRESENTATION: ['ppt', 'pptx', 'odp', 'key'],
    FileType.ARCHIVE: ['zip', 'rar', '7z', 'tar', 'gz', 'bz2'],
    FileType.VIDEO: ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'],
    FileType.AUDIO: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a'],
}

# MIME types by file extension
MIME_TYPES = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'txt': 'text/plain',
    'csv': 'text/csv',
    'json': 'application/json',
    'zip': 'application/zip',
}

# Color constants for UI themes
COLORS = {
    'PRIMARY': '#007bff',
    'SECONDARY': '#6c757d',
    'SUCCESS': '#28a745',
    'DANGER': '#dc3545',
    'WARNING': '#ffc107',
    'INFO': '#17a2b8',
    'LIGHT': '#f8f9fa',
    'DARK': '#343a40',
}

# Priority colors
PRIORITY_COLORS = {
    Priority.CRITICAL: '#dc3545',  # Red
    Priority.HIGH: '#fd7e14',      # Orange
    Priority.MEDIUM: '#ffc107',    # Yellow
    Priority.LOW: '#28a745',       # Green
    Priority.MINIMAL: '#6c757d',   # Gray
}

# Status colors
STATUS_COLORS = {
    TaskStatus.BACKLOG: '#6c757d',      # Gray
    TaskStatus.TODO: '#007bff',         # Blue
    TaskStatus.IN_PROGRESS: '#fd7e14',  # Orange
    TaskStatus.IN_REVIEW: '#17a2b8',    # Cyan
    TaskStatus.BLOCKED: '#dc3545',      # Red
    TaskStatus.TESTING: '#6f42c1',      # Purple
    TaskStatus.DONE: '#28a745',         # Green
    TaskStatus.CANCELLED: '#6c757d',    # Gray
}
