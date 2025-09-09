"""
Common validators for the task management system.

Provides reusable validation functions and classes.
"""

import re
from typing import Any, List, Optional, Union
from datetime import datetime, date

from django.core.exceptions import ValidationError
from django.core.validators import BaseValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class MinLengthValidator(BaseValidator):
    """Validator for minimum length with custom error message."""

    message = _('Ensure this value has at least %(limit_value)d characters (it has %(show_value)d).')
    code = 'min_length'

    def compare(self, a: int, b: int) -> bool:
        return a < b

    def clean(self, x: str) -> int:
        return len(x)


class MaxLengthValidator(BaseValidator):
    """Validator for maximum length with custom error message."""

    message = _('Ensure this value has at most %(limit_value)d characters (it has %(show_value)d).')
    code = 'max_length'

    def compare(self, a: int, b: int) -> bool:
        return a > b

    def clean(self, x: str) -> int:
        return len(x)


def validate_future_date(value: Union[date, datetime]) -> None:
    """Validate that a date is in the future."""

    if isinstance(value, datetime):
        current = timezone.now()
        if timezone.is_naive(value):
            current = current.replace(tzinfo=None)
    else:
        current = timezone.now().date()

    if value <= current:
        raise ValidationError(
            _('Date must be in the future.'),
            code='future_date_required'
        )


def validate_past_date(value: Union[date, datetime]) -> None:
    """Validate that a date is in the past."""

    if isinstance(value, datetime):
        current = timezone.now()
        if timezone.is_naive(value):
            current = current.replace(tzinfo=None)
    else:
        current = timezone.now().date()

    if value >= current:
        raise ValidationError(
            _('Date must be in the past.'),
            code='past_date_required'
        )


def validate_business_hours(value: Union[date, datetime]) -> None:
    """Validate that a datetime falls within business hours (9 AM - 5 PM, Mon-Fri)."""

    if isinstance(value, date) and not isinstance(value, datetime):
        # Cannot validate time for date-only values
        return

    if isinstance(value, datetime):
        # Convert to local timezone if needed
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        # Check if it's a weekday (Monday = 0, Sunday = 6)
        if value.weekday() >= 5:  # Saturday or Sunday
            raise ValidationError(
                _('Date must be on a weekday (Monday-Friday).'),
                code='business_days_only'
            )

        # Check if it's within business hours (9 AM - 5 PM)
        if not (9 <= value.hour < 17):
            raise ValidationError(
                _('Time must be within business hours (9 AM - 5 PM).'),
                code='business_hours_only'
            )


def validate_positive_number(value: Union[int, float]) -> None:
    """Validate that a number is positive."""
    if value <= 0:
        raise ValidationError(
            _('Value must be positive.'),
            code='positive_number_required'
        )


def validate_non_negative_number(value: Union[int, float]) -> None:
    """Validate that a number is non-negative."""
    if value < 0:
        raise ValidationError(
            _('Value cannot be negative.'),
            code='non_negative_required'
        )


def validate_percentage(value: Union[int, float]) -> None:
    """Validate that a number is a valid percentage (0-100)."""
    if not (0 <= value <= 100):
        raise ValidationError(
            _('Value must be between 0 and 100.'),
            code='invalid_percentage'
        )


def validate_priority_level(value: int) -> None:
    """Validate priority level (1-5)."""
    if not (1 <= value <= 5):
        raise ValidationError(
            _('Priority must be between 1 and 5.'),
            code='invalid_priority'
        )


def validate_estimated_hours(value: float) -> None:
    """Validate estimated hours for tasks."""
    if value <= 0:
        raise ValidationError(
            _('Estimated hours must be positive.'),
            code='positive_hours_required'
        )

    if value > 1000:  # Reasonable upper limit
        raise ValidationError(
            _('Estimated hours cannot exceed 1000.'),
            code='hours_too_high'
        )


def validate_slug_format(value: str) -> None:
    """Validate that a string follows slug format (lowercase, hyphens, underscores)."""
    pattern = r'^[a-z0-9_-]+
    if not re.match(pattern, value):
        raise ValidationError(
            _('Value must contain only lowercase letters, numbers, hyphens, and underscores.'),
            code='invalid_slug_format'
        )


def validate_color_hex(value: str) -> None:
    """Validate hex color code format."""
    pattern = r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})
    if not re.match(pattern, value):
        raise ValidationError(
            _('Value must be a valid hex color code (e.g., #FF0000 or #F00).'),
            code='invalid_hex_color'
        )


def validate_json_keys(allowed_keys: List[str]) -> callable:
    """Create a validator that checks JSON field keys."""

    def validator(value: dict) -> None:
        if not isinstance(value, dict):
            raise ValidationError(
                _('Value must be a JSON object.'),
                code='invalid_json_object'
            )

        invalid_keys = set(value.keys()) - set(allowed_keys)
        if invalid_keys:
            raise ValidationError(
                _('Invalid keys found: %(keys)s. Allowed keys: %(allowed)s') % {
                    'keys': ', '.join(invalid_keys),
                    'allowed': ', '.join(allowed_keys)
                },
                code='invalid_json_keys'
            )

    return validator


def validate_file_extension(allowed_extensions: List[str]) -> callable:
    """Create a validator for file extensions."""

    def validator(value) -> None:
        if hasattr(value, 'name'):
            extension = value.name.split('.')[-1].lower()
            if extension not in [ext.lower() for ext in allowed_extensions]:
                raise ValidationError(
                    _('File extension "%(extension)s" is not allowed. '
                      'Allowed extensions: %(allowed)s') % {
                        'extension': extension,
                        'allowed': ', '.join(allowed_extensions)
                    },
                    code='invalid_file_extension'
                )

    return validator


def validate_file_size(max_size_mb: float) -> callable:
    """Create a validator for file size."""

    def validator(value) -> None:
        if hasattr(value, 'size'):
            max_size_bytes = max_size_mb * 1024 * 1024
            if value.size > max_size_bytes:
                raise ValidationError(
                    _('File size %(size)s MB exceeds maximum allowed size of %(max_size)s MB.') % {
                        'size': round(value.size / (1024 * 1024), 2),
                        'max_size': max_size_mb
                    },
                    code='file_too_large'
                )

    return validator


class RegexValidator:
    """Custom regex validator with better error messages."""

    def __init__(self, pattern: str, message: str = None, code: str = None):
        self.pattern = re.compile(pattern)
        self.message = message or _('Value does not match required pattern.')
        self.code = code or 'invalid_format'

    def __call__(self, value: str) -> None:
        if not self.pattern.match(value):
            raise ValidationError(self.message, code=self.code)


class ConditionalValidator:
    """Validator that applies based on a condition."""

    def __init__(self, condition: callable, validator: callable):
        self.condition = condition
        self.validator = validator

    def __call__(self, value: Any) -> None:
        if self.condition(value):
            self.validator(value)


class ChainValidator:
    """Validator that applies multiple validators in sequence."""

    def __init__(self, *validators):
        self.validators = validators

    def __call__(self, value: Any) -> None:
        for validator in self.validators:
            validator(value)


# Common regex patterns
EMAIL_PATTERN = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}
PHONE_PATTERN = r'^\+?1?-?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})
USERNAME_PATTERN = r'^[a-zA-Z0-9._-]{3,30}
PASSWORD_PATTERN = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}

# Pre-configured validators
validate_email_format = RegexValidator(
    EMAIL_PATTERN,
    _('Enter a valid email address.'),
    'invalid_email'
)

validate_phone_format = RegexValidator(
    PHONE_PATTERN,
    _('Enter a valid phone number.'),
    'invalid_phone'
)

validate_username_format = RegexValidator(
    USERNAME_PATTERN,
    _('Username must be 3-30 characters long and contain only letters, numbers, dots, hyphens, and underscores.'),
    'invalid_username'
)

validate_strong_password = RegexValidator(
    PASSWORD_PATTERN,
    _('Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, one digit, and one special character.'),
    'weak_password'
)

# Common file validators
validate_image_extension = validate_file_extension(['jpg', 'jpeg', 'png', 'gif', 'webp'])
validate_document_extension = validate_file_extension(['pdf', 'doc', 'docx', 'txt', 'rtf'])
validate_spreadsheet_extension = validate_file_extension(['xls', 'xlsx', 'csv'])

validate_small_file_size = validate_file_size(5)  # 5 MB
validate_medium_file_size = validate_file_size(25)  # 25 MB
validate_large_file_size = validate_file_size(100)  # 100 MB

# Metadata validators
validate_task_metadata_keys = validate_json_keys([
    'labels', 'external_id', 'source', 'custom_fields', 
    'integrations', 'workflow_data', 'analytics'
])

validate_user_metadata_keys = validate_json_keys([
    'preferences', 'settings', 'profile_data', 'integrations',
    'notifications', 'analytics', 'custom_fields'
])
