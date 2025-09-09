"""
Common exceptions for the task management system.

Provides custom exception classes for consistent error handling.
"""

from typing import Any, Dict, Optional, Union

from rest_framework import status
from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.core.exceptions import ValidationError as DjangoValidationError


class TaskManagementException(Exception):
    """Base exception for task management system."""

    default_message = "An error occurred in the task management system"
    default_code = "task_management_error"

    def __init__(
        self, 
        message: str = None, 
        code: str = None, 
        details: Dict[str, Any] = None
    ):
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationException(TaskManagementException):
    """Exception raised when validation fails."""

    default_message = "Validation failed"
    default_code = "validation_error"


class BusinessLogicException(TaskManagementException):
    """Exception raised when business logic rules are violated."""

    default_message = "Business logic violation"
    default_code = "business_logic_error"


class PermissionDeniedException(TaskManagementException):
    """Exception raised when user lacks required permissions."""

    default_message = "Permission denied"
    default_code = "permission_denied"


class ResourceNotFoundException(TaskManagementException):
    """Exception raised when a requested resource is not found."""

    default_message = "Resource not found"
    default_code = "resource_not_found"


class ConflictException(TaskManagementException):
    """Exception raised when there's a conflict with current state."""

    default_message = "Conflict with current state"
    default_code = "conflict_error"


class RateLimitException(TaskManagementException):
    """Exception raised when rate limit is exceeded."""

    default_message = "Rate limit exceeded"
    default_code = "rate_limit_exceeded"


class ServiceUnavailableException(TaskManagementException):
    """Exception raised when a service is temporarily unavailable."""

    default_message = "Service temporarily unavailable"
    default_code = "service_unavailable"


class InvalidOperationException(TaskManagementException):
    """Exception raised when an invalid operation is attempted."""

    default_message = "Invalid operation"
    default_code = "invalid_operation"


class TaskStateException(BusinessLogicException):
    """Exception raised when task state transitions are invalid."""

    default_message = "Invalid task state transition"
    default_code = "invalid_task_state"


class AssignmentException(BusinessLogicException):
    """Exception raised when task assignment fails."""

    default_message = "Task assignment failed"
    default_code = "assignment_error"


class WorkflowException(BusinessLogicException):
    """Exception raised when workflow processing fails."""

    default_message = "Workflow processing failed"
    default_code = "workflow_error"


class NotificationException(TaskManagementException):
    """Exception raised when notification delivery fails."""

    default_message = "Notification delivery failed"
    default_code = "notification_error"


def custom_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[Response]:
    """
    Custom exception handler for DRF that provides consistent error responses.

    Args:
        exc: The exception that was raised
        context: Context information about the request and view

    Returns:
        Response with standardized error format or None
    """

    # Handle our custom exceptions
    if isinstance(exc, TaskManagementException):
        return Response(
            {
                'error': {
                    'message': exc.message,
                    'code': exc.code,
                    'details': exc.details
                }
            },
            status=_get_status_code_for_exception(exc)
        )

    # Handle Django validation errors
    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                'error': {
                    'message': 'Validation failed',
                    'code': 'validation_error',
                    'details': _format_django_validation_error(exc)
                }
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Call DRF's default exception handler for other exceptions
    response = exception_handler(exc, context)

    if response is not None:
        # Standardize DRF error responses
        if isinstance(response.data, dict):
            # If it's already in our format, leave it alone
            if 'error' not in response.data:
                custom_response_data = {
                    'error': {
                        'message': _get_error_message_from_response(response.data),
                        'code': _get_error_code_from_status(response.status_code),
                        'details': response.data
                    }
                }
                response.data = custom_response_data

    return response


def _get_status_code_for_exception(exc: TaskManagementException) -> int:
    """Get appropriate HTTP status code for custom exception."""

    status_mapping = {
        ValidationException: status.HTTP_400_BAD_REQUEST,
        BusinessLogicException: status.HTTP_422_UNPROCESSABLE_ENTITY,
        PermissionDeniedException: status.HTTP_403_FORBIDDEN,
        ResourceNotFoundException: status.HTTP_404_NOT_FOUND,
        ConflictException: status.HTTP_409_CONFLICT,
        RateLimitException: status.HTTP_429_TOO_MANY_REQUESTS,
        ServiceUnavailableException: status.HTTP_503_SERVICE_UNAVAILABLE,
        InvalidOperationException: status.HTTP_400_BAD_REQUEST,
        TaskStateException: status.HTTP_422_UNPROCESSABLE_ENTITY,
        AssignmentException: status.HTTP_422_UNPROCESSABLE_ENTITY,
        WorkflowException: status.HTTP_422_UNPROCESSABLE_ENTITY,
        NotificationException: status.HTTP_500_INTERNAL_SERVER_ERROR,
    }

    for exception_class, status_code in status_mapping.items():
        if isinstance(exc, exception_class):
            return status_code

    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _format_django_validation_error(exc: DjangoValidationError) -> Dict[str, Any]:
    """Format Django validation error for consistent response."""

    if hasattr(exc, 'error_dict'):
        # Field-specific errors
        return {field: [str(error) for error in errors] 
                for field, errors in exc.error_dict.items()}
    elif hasattr(exc, 'error_list'):
        # Non-field errors
        return {'non_field_errors': [str(error) for error in exc.error_list]}
    else:
        # Fallback
        return {'non_field_errors': [str(exc)]}


def _get_error_message_from_response(data: Union[Dict, list, str]) -> str:
    """Extract a user-friendly error message from response data."""

    if isinstance(data, dict):
        # Check for common error message fields
        for field in ['detail', 'message', 'error']:
            if field in data:
                value = data[field]
                if isinstance(value, str):
                    return value
                elif isinstance(value, list) and value:
                    return str(value[0])

        # Check for non_field_errors
        if 'non_field_errors' in data:
            errors = data['non_field_errors']
            if isinstance(errors, list) and errors:
                return str(errors[0])

        # Use the first error found
        for key, value in data.items():
            if isinstance(value, list) and value:
                return f"{key}: {value[0]}"
            elif isinstance(value, str):
                return f"{key}: {value}"

    elif isinstance(data, list) and data:
        return str(data[0])

    elif isinstance(data, str):
        return data

    return "An error occurred"


def _get_error_code_from_status(status_code: int) -> str:
    """Get error code based on HTTP status code."""

    code_mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "unprocessable_entity",
        429: "rate_limit_exceeded",
        500: "internal_server_error",
        503: "service_unavailable",
    }

    return code_mapping.get(status_code, "unknown_error")
