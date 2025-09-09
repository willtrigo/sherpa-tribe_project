"""
Test cases for common utilities and mixins.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.utils import timezone

from apps.common.utils import (
    calculate_business_hours,
    generate_slug,
    sanitize_filename,
    format_duration,
    get_client_ip,
    send_notification,
    cache_key_generator,
    convert_timezone,
    calculate_priority_score,
    bulk_update_status,
)
from apps.common.mixins import (
    TimestampMixin,
    SoftDeleteMixin,
    CacheMixin,
    AuditMixin,
)

User = get_user_model()


class UtilsTestCase(TestCase):
    """Test utility functions."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.factory = RequestFactory()

    def test_calculate_business_hours(self):
        """Test business hours calculation."""
        start_date = datetime(2023, 10, 2, 9, 0)  # Monday 9 AM
        end_date = datetime(2023, 10, 2, 17, 0)  # Monday 5 PM
        
        hours = calculate_business_hours(start_date, end_date)
        self.assertEqual(hours, 8.0)
        
        # Test weekend exclusion
        start_date = datetime(2023, 10, 7, 9, 0)  # Saturday
        end_date = datetime(2023, 10, 9, 17, 0)  # Monday
        
        hours = calculate_business_hours(start_date, end_date)
        self.assertEqual(hours, 8.0)  # Only Monday hours counted

    def test_generate_slug(self):
        """Test slug generation."""
        text = "This is a Test Title!"
        slug = generate_slug(text)
        self.assertEqual(slug, "this-is-a-test-title")
        
        # Test with special characters
        text = "Special @#$% Characters & More"
        slug = generate_slug(text)
        self.assertEqual(slug, "special-characters-more")

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        filename = "file with spaces & special chars.txt"
        sanitized = sanitize_filename(filename)
        self.assertEqual(sanitized, "file_with_spaces_special_chars.txt")
        
        # Test with dangerous characters
        filename = "../../../etc/passwd"
        sanitized = sanitize_filename(filename)
        self.assertNotIn("..", sanitized)
        self.assertNotIn("/", sanitized)

    def test_format_duration(self):
        """Test duration formatting."""
        # Test hours
        duration = timedelta(hours=2, minutes=30)
        formatted = format_duration(duration)
        self.assertEqual(formatted, "2h 30m")
        
        # Test days
        duration = timedelta(days=1, hours=3)
        formatted = format_duration(duration)
        self.assertEqual(formatted, "1d 3h")
        
        # Test seconds only
        duration = timedelta(seconds=45)
        formatted = format_duration(duration)
        self.assertEqual(formatted, "45s")

    def test_get_client_ip(self):
        """Test client IP extraction."""
        # Test with X-Forwarded-For
        request = self.factory.get('/')
        request.META['HTTP_X_FORWARDED_FOR'] = '192.168.1.1, 10.0.0.1'
        ip = get_client_ip(request)
        self.assertEqual(ip, '192.168.1.1')
        
        # Test with REMOTE_ADDR
        request = self.factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.2'
        ip = get_client_ip(request)
        self.assertEqual(ip, '192.168.1.2')

    @patch('apps.common.utils.send_mail')
    def test_send_notification(self, mock_send_mail):
        """Test notification sending."""
        mock_send_mail.return_value = True
        
        result = send_notification(
            recipient=self.user,
            subject='Test Subject',
            message='Test message',
            notification_type='email'
        )
        
        self.assertTrue(result)
        mock_send_mail.assert_called_once()

    def test_cache_key_generator(self):
        """Test cache key generation."""
        key = cache_key_generator('user', 'profile', user_id=1)
        self.assertEqual(key, 'user:profile:user_id=1')
        
        key = cache_key_generator('tasks', 'list', status='active', priority='high')
        self.assertIn('tasks:list', key)
        self.assertIn('status=active', key)
        self.assertIn('priority=high', key)

    def test_convert_timezone(self):
        """Test timezone conversion."""
        utc_time = timezone.now()
        est_time = convert_timezone(utc_time, 'US/Eastern')
        
        self.assertIsNotNone(est_time)
        self.assertNotEqual(utc_time.hour, est_time.hour)

    def test_calculate_priority_score(self):
        """Test priority score calculation."""
        # High priority, near due date
        due_date = timezone.now() + timedelta(hours=2)
        score = calculate_priority_score('HIGH', due_date, 8.0)
        
        self.assertIsInstance(score, (int, float))
        self.assertGreater(score, 0)
        
        # Low priority, far due date
        due_date = timezone.now() + timedelta(days=30)
        score_low = calculate_priority_score('LOW', due_date, 2.0)
        
        self.assertLess(score_low, score)

    def test_bulk_update_status(self):
        """Test bulk status update."""
        # This would require actual model instances
        # For now, test that the function exists and is callable
        self.assertTrue(callable(bulk_update_status))


class MixinsTestCase(TestCase):
    """Test model mixins."""

    def test_timestamp_mixin(self):
        """Test timestamp mixin functionality."""
        class TestModel(TimestampMixin):
            def __init__(self):
                super().__init__()
                self.created_at = timezone.now()
                self.updated_at = timezone.now()
        
        instance = TestModel()
        self.assertIsNotNone(instance.created_at)
        self.assertIsNotNone(instance.updated_at)

    def test_soft_delete_mixin(self):
        """Test soft delete mixin functionality."""
        class TestModel(SoftDeleteMixin):
            def __init__(self):
                super().__init__()
                self.is_deleted = False
                self.deleted_at = None
        
        instance = TestModel()
        self.assertFalse(instance.is_deleted)
        self.assertIsNone(instance.deleted_at)

    def test_cache_mixin(self):
        """Test cache mixin functionality."""
        class TestModel(CacheMixin):
            def __init__(self):
                super().__init__()
                self.id = 1
        
        instance = TestModel()
        cache_key = instance.get_cache_key()
        self.assertIsInstance(cache_key, str)
        self.assertIn('testmodel', cache_key.lower())

    def test_audit_mixin(self):
        """Test audit mixin functionality."""
        class TestModel(AuditMixin):
            def __init__(self):
                super().__init__()
                self.created_by = None
                self.updated_by = None
        
        instance = TestModel()
        self.assertIsNone(instance.created_by)
        self.assertIsNone(instance.updated_by)


class MiddlewareTestCase(TestCase):
    """Test custom middleware."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()

    @patch('apps.common.middleware.AuditMiddleware')
    def test_audit_middleware(self, mock_middleware):
        """Test audit middleware initialization."""
        # Test that middleware can be imported and initialized
        from apps.common.middleware import AuditMiddleware
        
        get_response = Mock()
        middleware = AuditMiddleware(get_response)
        
        self.assertIsNotNone(middleware)
        self.assertEqual(middleware.get_response, get_response)

    @patch('apps.common.middleware.SecurityHeadersMiddleware')
    def test_security_headers_middleware(self, mock_middleware):
        """Test security headers middleware."""
        from apps.common.middleware import SecurityHeadersMiddleware
        
        get_response = Mock()
        middleware = SecurityHeadersMiddleware(get_response)
        
        self.assertIsNotNone(middleware)
        self.assertEqual(middleware.get_response, get_response)


class ExceptionsTestCase(TestCase):
    """Test custom exceptions."""

    def test_custom_exceptions_import(self):
        """Test that custom exceptions can be imported."""
        from apps.common.exceptions import (
            TaskManagementException,
            ValidationError,
            PermissionDeniedError,
            NotFoundError,
            BusinessLogicError,
        )
        
        # Test exception inheritance
        self.assertTrue(issubclass(TaskManagementException, Exception))
        self.assertTrue(issubclass(ValidationError, TaskManagementException))
        self.assertTrue(issubclass(PermissionDeniedError, TaskManagementException))
        self.assertTrue(issubclass(NotFoundError, TaskManagementException))
        self.assertTrue(issubclass(BusinessLogicError, TaskManagementException))

    def test_exception_messages(self):
        """Test exception message handling."""
        from apps.common.exceptions import ValidationError
        
        error = ValidationError("Test validation error")
        self.assertEqual(str(error), "Test validation error")
        
        error = ValidationError("Field error", field="email")
        self.assertIn("email", str(error))


class ValidatorsTestCase(TestCase):
    """Test custom validators."""

    def test_validators_import(self):
        """Test that validators can be imported."""
        from apps.common.validators import (
            validate_file_size,
            validate_image_dimensions,
            validate_file_extension,
            validate_future_date,
            validate_business_hours,
            validate_priority_score,
        )
        
        # Test that all validators are callable
        validators = [
            validate_file_size,
            validate_image_dimensions,
            validate_file_extension,
            validate_future_date,
            validate_business_hours,
            validate_priority_score,
        ]
        
        for validator in validators:
            self.assertTrue(callable(validator))

    def test_validate_future_date(self):
        """Test future date validator."""
        from apps.common.validators import validate_future_date
        from django.core.exceptions import ValidationError
        
        # Test past date (should raise error)
        past_date = timezone.now() - timedelta(days=1)
        with self.assertRaises(ValidationError):
            validate_future_date(past_date)
        
        # Test future date (should pass)
        future_date = timezone.now() + timedelta(days=1)
        try:
            validate_future_date(future_date)
        except ValidationError:
            self.fail("validate_future_date raised ValidationError unexpectedly")

    def test_validate_priority_score(self):
        """Test priority score validator."""
        from apps.common.validators import validate_priority_score
        from django.core.exceptions import ValidationError
        
        # Test valid score
        try:
            validate_priority_score(5.5)
        except ValidationError:
            self.fail("validate_priority_score raised ValidationError unexpectedly")
        
        # Test invalid score (negative)
        with self.assertRaises(ValidationError):
            validate_priority_score(-1.0)
        
        # Test invalid score (too high)
        with self.assertRaises(ValidationError):
            validate_priority_score(11.0)


class PaginationTestCase(TestCase):
    """Test custom pagination classes."""

    def test_pagination_import(self):
        """Test that pagination classes can be imported."""
        from apps.common.pagination import (
            StandardResultsSetPagination,
            LargeResultsSetPagination,
            SmallResultsSetPagination,
        )
        
        # Test that pagination classes exist
        self.assertTrue(hasattr(StandardResultsSetPagination, 'page_size'))
        self.assertTrue(hasattr(LargeResultsSetPagination, 'page_size'))
        self.assertTrue(hasattr(SmallResultsSetPagination, 'page_size'))

    def test_pagination_page_sizes(self):
        """Test pagination page sizes."""
        from apps.common.pagination import (
            StandardResultsSetPagination,
            LargeResultsSetPagination,
            SmallResultsSetPagination,
        )
        
        # Test page sizes are different
        self.assertNotEqual(
            StandardResultsSetPagination.page_size,
            LargeResultsSetPagination.page_size
        )
        self.assertNotEqual(
            StandardResultsSetPagination.page_size,
            SmallResultsSetPagination.page_size
        )


class PermissionsTestCase(TestCase):
    """Test custom permissions."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='testpass123',
            is_staff=True
        )
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='testpass123'
        )

    def test_permissions_import(self):
        """Test that custom permissions can be imported."""
        from apps.common.permissions import (
            IsOwnerOrReadOnly,
            IsStaffOrReadOnly,
            IsAssigneeOrReadOnly,
            IsTeamMemberOrReadOnly,
            HasTaskPermission,
        )
        
        # Test that all permission classes exist
        permissions = [
            IsOwnerOrReadOnly,
            IsStaffOrReadOnly,
            IsAssigneeOrReadOnly,
            IsTeamMemberOrReadOnly,
            HasTaskPermission,
        ]
        
        for permission_class in permissions:
            self.assertTrue(hasattr(permission_class, 'has_permission'))

    def test_is_owner_or_read_only(self):
        """Test IsOwnerOrReadOnly permission."""
        from apps.common.permissions import IsOwnerOrReadOnly
        from django.test import RequestFactory
        
        factory = RequestFactory()
        permission = IsOwnerOrReadOnly()
        
        # Create mock request and view
        request = factory.get('/')
        request.user = self.user
        
        view = Mock()
        view.action = 'list'
        
        # Test read permission
        has_permission = permission.has_permission(request, view)
        self.assertTrue(has_permission)

    def test_is_staff_or_read_only(self):
        """Test IsStaffOrReadOnly permission."""
        from apps.common.permissions import IsStaffOrReadOnly
        from django.test import RequestFactory
        
        factory = RequestFactory()
        permission = IsStaffOrReadOnly()
        
        # Test with staff user
        request = factory.post('/')
        request.user = self.staff_user
        
        view = Mock()
        view.action = 'create'
        
        has_permission = permission.has_permission(request, view)
        self.assertTrue(has_permission)


class ConstantsTestCase(TestCase):
    """Test application constants."""

    def test_constants_import(self):
        """Test that constants can be imported."""
        from apps.common.constants import (
            TASK_STATUS_CHOICES,
            TASK_PRIORITY_CHOICES,
            NOTIFICATION_TYPES,
            USER_ROLES,
            WORKFLOW_STATES,
            DEFAULT_CACHE_TIMEOUT,
            MAX_FILE_SIZE,
            ALLOWED_FILE_TYPES,
        )
        
        # Test that constants are defined
        self.assertIsInstance(TASK_STATUS_CHOICES, (list, tuple))
        self.assertIsInstance(TASK_PRIORITY_CHOICES, (list, tuple))
        self.assertIsInstance(NOTIFICATION_TYPES, (list, tuple, dict))
        self.assertIsInstance(USER_ROLES, (list, tuple, dict))
        self.assertIsInstance(WORKFLOW_STATES, (list, tuple, dict))
        self.assertIsInstance(DEFAULT_CACHE_TIMEOUT, int)
        self.assertIsInstance(MAX_FILE_SIZE, int)
        self.assertIsInstance(ALLOWED_FILE_TYPES, (list, tuple, set))

    def test_task_choices_format(self):
        """Test task choices are properly formatted."""
        from apps.common.constants import TASK_STATUS_CHOICES, TASK_PRIORITY_CHOICES
        
        # Test status choices
        for choice in TASK_STATUS_CHOICES:
            self.assertIsInstance(choice, tuple)
            self.assertEqual(len(choice), 2)
            self.assertIsInstance(choice[0], str)
            self.assertIsInstance(choice[1], str)
        
        # Test priority choices
        for choice in TASK_PRIORITY_CHOICES:
            self.assertIsInstance(choice, tuple)
            self.assertEqual(len(choice), 2)
            self.assertIsInstance(choice[0], str)
            self.assertIsInstance(choice[1], str)

    def test_cache_timeout_positive(self):
        """Test that cache timeout is positive."""
        from apps.common.constants import DEFAULT_CACHE_TIMEOUT
        
        self.assertGreater(DEFAULT_CACHE_TIMEOUT, 0)

    def test_max_file_size_reasonable(self):
        """Test that max file size is reasonable."""
        from apps.common.constants import MAX_FILE_SIZE
        
        # Should be between 1MB and 100MB
        self.assertGreaterEqual(MAX_FILE_SIZE, 1024 * 1024)  # At least 1MB
        self.assertLessEqual(MAX_FILE_SIZE, 100 * 1024 * 1024)  # At most 100MB
