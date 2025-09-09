"""
Common utility functions for the task management system.

Provides reusable helper functions and utilities.
"""

import hashlib
import secrets
import string
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from django.core.serializers.json import DjangoJSONEncoder


def generate_random_string(
    length: int = 32,
    include_digits: bool = True,
    include_uppercase: bool = True,
    include_lowercase: bool = True,
    include_symbols: bool = False
) -> str:
    """
    Generate a cryptographically secure random string.

    Args:
        length: Length of the string to generate
        include_digits: Include digits (0-9)
        include_uppercase: Include uppercase letters (A-Z)
        include_lowercase: Include lowercase letters (a-z)
        include_symbols: Include symbols (!@#$%^&*)

    Returns:
        Random string of specified length
    """
    characters = ''

    if include_digits:
        characters += string.digits
    if include_uppercase:
        characters += string.ascii_uppercase
    if include_lowercase:
        characters += string.ascii_lowercase
    if include_symbols:
        characters += '!@#$%^&*'

    if not characters:
        raise ValueError("At least one character type must be included")

    return ''.join(secrets.choice(characters) for _ in range(length))


def generate_unique_slug(
    text: str,
    max_length: int = 50,
    model_class = None,
    slug_field: str = 'slug',
    instance = None
) -> str:
    """
    Generate a unique slug from text.

    Args:
        text: Text to convert to slug
        max_length: Maximum length of the slug
        model_class: Model class to check uniqueness against
        slug_field: Field name for the slug
        instance: Current instance (for updates)

    Returns:
        Unique slug string
    """
    base_slug = slugify(text)[:max_length]
    unique_slug = base_slug

    if model_class:
        counter = 1
        while True:
            # Check if slug exists
            filter_kwargs = {slug_field: unique_slug}
            queryset = model_class.objects.filter(**filter_kwargs)

            # Exclude current instance if updating
            if instance and hasattr(instance, 'pk') and instance.pk:
                queryset = queryset.exclude(pk=instance.pk)

            if not queryset.exists():
                break

            # Generate new slug with counter
            counter += 1
            suffix = f"-{counter}"
            max_base_length = max_length - len(suffix)
            unique_slug = f"{base_slug[:max_base_length]}{suffix}"

    return unique_slug


def calculate_time_difference(
    start_time: Union[datetime, date],
    end_time: Union[datetime, date],
    unit: str = 'hours'
) -> float:
    """
    Calculate time difference between two datetime objects.

    Args:
        start_time: Start datetime
        end_time: End datetime
        unit: Unit of measurement ('seconds', 'minutes', 'hours', 'days')

    Returns:
        Time difference in specified units
    """
    if isinstance(start_time, date) and not isinstance(start_time, datetime):
        start_time = datetime.combine(start_time, datetime.min.time())
    if isinstance(end_time, date) and not isinstance(end_time, datetime):
        end_time = datetime.combine(end_time, datetime.min.time())

    delta = end_time - start_time

    if unit == 'seconds':
        return delta.total_seconds()
    elif unit == 'minutes':
        return delta.total_seconds() / 60
    elif unit == 'hours':
        return delta.total_seconds() / 3600
    elif unit == 'days':
        return delta.days + (delta.seconds / 86400)
    else:
        raise ValueError(f"Unsupported time unit: {unit}")


def is_business_day(date_obj: Union[datetime, date]) -> bool:
    """Check if a date is a business day (Monday-Friday)."""
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()

    return date_obj.weekday() < 5  # Monday=0, Sunday=6


def add_business_days(start_date: Union[datetime, date], days: int) -> Union[datetime, date]:
    """
    Add business days to a date, skipping weekends.

    Args:
        start_date: Starting date
        days: Number of business days to add

    Returns:
        Date after adding business days
    """
    current_date = start_date
    days_added = 0

    while days_added < days:
        current_date += timedelta(days=1)
        if is_business_day(current_date):
            days_added += 1

    return current_date


def calculate_business_hours_between(
    start_datetime: datetime,
    end_datetime: datetime,
    business_start_hour: int = 9,
    business_end_hour: int = 17
) -> float:
    """
    Calculate business hours between two datetimes.

    Args:
        start_datetime: Start datetime
        end_datetime: End datetime
        business_start_hour: Start of business day (24-hour format)
        business_end_hour: End of business day (24-hour format)

    Returns:
        Number of business hours
    """
    if start_datetime >= end_datetime:
        return 0

    total_hours = 0
    current_date = start_datetime.date()
    end_date = end_datetime.date()

    while current_date <= end_date:
        if is_business_day(current_date):
            day_start = datetime.combine(current_date, datetime.min.time().replace(hour=business_start_hour))
            day_end = datetime.combine(current_date, datetime.min.time().replace(hour=business_end_hour))

            # Adjust for timezone if needed
            if timezone.is_aware(start_datetime):
                day_start = timezone.make_aware(day_start)
                day_end = timezone.make_aware(day_end)

            # Calculate hours for this day
            actual_start = max(start_datetime, day_start)
            actual_end = min(end_datetime, day_end)

            if actual_start < actual_end:
                day_hours = (actual_end - actual_start).total_seconds() / 3600
                total_hours += day_hours

        current_date += timedelta(days=1)

    return total_hours


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2h 30m", "1d 4h")
    """
    if seconds < 60:
        return f"{int(seconds)}s"

    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if hours < 24:
        if remaining_minutes > 0:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"

    days = hours // 24
    remaining_hours = hours % 24

    if remaining_hours > 0:
        return f"{days}d {remaining_hours}h"
    return f"{days}d"


def calculate_percentage(part: Union[int, float], total: Union[int, float]) -> float:
    """
    Calculate percentage with handling for zero division.

    Args:
        part: Part value
        total: Total value

    Returns:
        Percentage (0-100)
    """
    if total == 0:
        return 0.0

    return round((part / total) * 100, 2)


def safe_divide(dividend: Union[int, float], divisor: Union[int, float], default: float = 0.0) -> float:
    """
    Perform division with handling for zero division.

    Args:
        dividend: Dividend
        divisor: Divisor
        default: Default value if divisor is zero

    Returns:
        Division result or default value
    """
    if divisor == 0:
        return default

    return dividend / divisor


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to maximum length with optional suffix.

    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add if truncated

    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text

    truncated_length = max_length - len(suffix)
    return text[:truncated_length] + suffix


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize filename by removing invalid characters.

    Args:
        filename: Original filename
        max_length: Maximum length for filename

    Returns:
        Sanitized filename
    """
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')

    # Remove leading/trailing spaces and dots
    filename = filename.strip(' .')

    # Truncate if necessary
    if len(filename) > max_length:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        max_name_length = max_length - len(ext) - 1 if ext else max_length
        filename = f"{name[:max_name_length]}.{ext}" if ext else name[:max_length]

    return filename or 'unnamed_file'


def hash_string(text: str, algorithm: str = 'sha256') -> str:
    """
    Generate hash of a string.

    Args:
        text: Text to hash
        algorithm: Hashing algorithm ('md5', 'sha1', 'sha256', 'sha512')

    Returns:
        Hexadecimal hash string
    """
    algorithms = {
        'md5': hashlib.md5,
        'sha1': hashlib.sha1,
        'sha256': hashlib.sha256,
        'sha512': hashlib.sha512,
    }

    if algorithm not in algorithms:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    return algorithms[algorithm](text.encode('utf-8')).hexdigest()


def deep_merge_dict(dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries.

    Args:
        dict1: First dictionary
        dict2: Second dictionary (takes precedence)

    Returns:
        Merged dictionary
    """
    result = dict1.copy()

    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dict(result[key], value)
        else:
            result[key] = value

    return result


def flatten_dict(data: Dict[str, Any], separator: str = '.', prefix: str = '') -> Dict[str, Any]:
    """
    Flatten nested dictionary.

    Args:
        data: Dictionary to flatten
        separator: Separator for nested keys
        prefix: Prefix for keys

    Returns:
        Flattened dictionary
    """
    result = {}

    for key, value in data.items():
        new_key = f"{prefix}{separator}{key}" if prefix else key

        if isinstance(value, dict):
            result.update(flatten_dict(value, separator, new_key))
        else:
            result[new_key] = value

    return result


def send_notification_email(
    recipient_email: str,
    subject: str,
    template_name: str,
    context: Dict[str, Any],
    from_email: str = None
) -> bool:
    """
    Send notification email using Django template.

    Args:
        recipient_email: Recipient email address
        subject: Email subject
        template_name: Template name for email body
        context: Context for template rendering
        from_email: Sender email (uses default if not provided)

    Returns:
        True if email was sent successfully
    """
    try:
        html_content = render_to_string(template_name, context)

        send_mail(
            subject=subject,
            message='',  # Plain text version
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_content,
            fail_silently=False
        )
        return True
    except Exception:
        return False


def get_client_ip(request) -> str:
    """
    Get client IP address from request.

    Args:
        request: Django request object

    Returns:
        Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')

    return ip


def get_user_agent(request) -> str:
    """
    Get user agent string from request.

    Args:
        request: Django request object

    Returns:
        User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


class CustomJSONEncoder(DjangoJSONEncoder):
    """Custom JSON encoder for additional data types."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, set):
            return list(obj)
        return super().default(obj)


def serialize_for_cache(data: Any) -> str:
    """
    Serialize data for caching.

    Args:
        data: Data to serialize

    Returns:
        JSON string
    """
    import json
    return json.dumps(data, cls=CustomJSONEncoder, ensure_ascii=False)


def deserialize_from_cache(json_str: str) -> Any:
    """
    Deserialize data from cache.

    Args:
        json_str: JSON string from cache

    Returns:
        Deserialized data
    """
    import json
    return json.loads(json_str)


def validate_and_convert_ids(ids: Union[str, List[str]]) -> List[str]:
    """
    Validate and convert IDs to list format.

    Args:
        ids: Single ID string or list of ID strings

    Returns:
        List of validated ID strings
    """
    if isinstance(ids, str):
        ids = [ids]

    validated_ids = []
    for id_str in ids:
        if isinstance(id_str, str) and id_str.strip():
            validated_ids.append(id_str.strip())

    return validated_ids


def chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Split list into chunks of specified size.

    Args:
        data: List to chunk
        chunk_size: Size of each chunk

    Returns:
        List of chunks
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


def get_model_fields(model_class, include_relations: bool = False) -> List[str]:
    """
    Get list of field names for a model.

    Args:
        model_class: Django model class
        include_relations: Whether to include relation fields

    Returns:
        List of field names
    """
    fields = []

    for field in model_class._meta.get_fields():
        if not include_relations and field.is_relation:
            continue
        fields.append(field.name)

    return fields


def build_absolute_uri(request, path: str) -> str:
    """
    Build absolute URI from request and path.

    Args:
        request: Django request object
        path: Relative path

    Returns:
        Absolute URI
    """
    return request.build_absolute_uri(path)


def retry_on_exception(max_retries: int = 3, delay: float = 1.0):
    """
    Decorator to retry function on exception.

    Args:
        max_retries: Maximum number of retries
        delay: Delay between retries in seconds

    Returns:
        Decorator function
    """
    import time
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        time.sleep(delay * (2 ** attempt))  # Exponential backoff
                    else:
                        raise last_exception

            raise last_exception

        return wrapper
    return decorator


def log_execution_time(logger):
    """
    Decorator to log function execution time.

    Args:
        logger: Logger instance

    Returns:
        Decorator function
    """
    import time
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(f"{func.__name__} executed in {execution_time:.4f} seconds")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"{func.__name__} failed after {execution_time:.4f} seconds: {str(e)}")
                raise

        return wrapper
    return decorator


def get_quarter_date_range(year: int, quarter: int) -> tuple[date, date]:
    """
    Get date range for a quarter.

    Args:
        year: Year
        quarter: Quarter (1-4)

    Returns:
        Tuple of (start_date, end_date)
    """
    if not 1 <= quarter <= 4:
        raise ValueError("Quarter must be between 1 and 4")

    start_month = (quarter - 1) * 3 + 1
    start_date = date(year, start_month, 1)

    if quarter == 4:
        end_date = date(year, 12, 31)
    else:
        next_quarter_start = date(year, start_month + 3, 1)
        end_date = next_quarter_start - timedelta(days=1)

    return start_date, end_date


# Convenience functions for common operations
def now() -> datetime:
    """Get current timezone-aware datetime."""
    return timezone.now()


def today() -> date:
    """Get current date."""
    return timezone.now().date()


def tomorrow() -> date:
    """Get tomorrow's date."""
    return today() + timedelta(days=1)


def yesterday() -> date:
    """Get yesterday's date."""
    return today() - timedelta(days=1)
