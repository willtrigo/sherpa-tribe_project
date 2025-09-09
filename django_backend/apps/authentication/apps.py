
"""
Authentication application configuration module.

This module defines the Django application configuration for the authentication app,
which handles user authentication, JWT token management, and related functionality
for the Enterprise Task Management System.

The configuration includes signal handling setup for user authentication events
and proper app initialization for the containerized Django application.
"""

from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.core.signals import setting_changed
from django.db.models.signals import post_save, pre_delete
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model


class AuthenticationConfig(AppConfig):
    """
    Django application configuration for authentication module.
    
    This configuration class handles:
    - Application metadata and naming
    - Signal registration for authentication events
    - Model initialization and validation
    - Cache invalidation on authentication changes
    """
    
    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "apps.authentication"
    verbose_name: str = _("Authentication & Authorization")
    label: str = "authentication"
    
    def ready(self) -> None:
        """
        Perform application initialization tasks when Django starts.
        
        This method is called once Django has loaded all models and is ready
        to start processing requests. It registers signal handlers and performs
        any necessary setup for the authentication system.
        
        Signal handlers registered:
        - User authentication events
        - Token lifecycle management
        - Cache invalidation for auth changes
        - Audit logging for security events
        
        Raises:
            ImportError: If required authentication modules cannot be imported
            AttributeError: If signal connections fail due to missing methods
        """
        try:
            # Import and register authentication signal handlers
            self._register_authentication_signals()
            self._register_token_signals()
            self._register_security_signals()
            self._register_cache_invalidation_signals()
            
        except ImportError as exc:
            # Log import errors but don't crash the application
            import logging
            logger = logging.getLogger(__name__)
            logger.error(
                "Failed to import authentication signals: %s. "
                "Some authentication features may not work correctly.",
                exc,
                exc_info=True
            )
    
    def _register_authentication_signals(self) -> None:
        """Register signals for user authentication events."""
        from django.contrib.auth.signals import (
            user_logged_in,
            user_logged_out,
            user_login_failed,
        )
        
        # Import signal handlers lazily to avoid circular imports
        from .signals import (
            handle_user_login,
            handle_user_logout,
            handle_login_failure,
        )
        
        user_logged_in.connect(
            handle_user_login,
            dispatch_uid="authentication_user_logged_in",
            weak=False
        )
        
        user_logged_out.connect(
            handle_user_logout,
            dispatch_uid="authentication_user_logged_out",
            weak=False
        )
        
        user_login_failed.connect(
            handle_login_failure,
            dispatch_uid="authentication_user_login_failed",
            weak=False
        )
    
    def _register_token_signals(self) -> None:
        """Register signals for JWT token lifecycle management."""
        from .signals import (
            handle_token_creation,
            handle_token_refresh,
            handle_token_blacklist,
        )
        
        # Connect to custom token signals
        from .models import RefreshToken
        
        post_save.connect(
            handle_token_creation,
            sender=RefreshToken,
            dispatch_uid="authentication_token_created",
            weak=False
        )
        
        pre_delete.connect(
            handle_token_blacklist,
            sender=RefreshToken,
            dispatch_uid="authentication_token_blacklisted",
            weak=False
        )
    
    def _register_security_signals(self) -> None:
        """Register signals for security audit and monitoring."""
        from .signals import (
            handle_password_change,
            handle_account_lockout,
            handle_suspicious_activity,
        )
        
        # Import User model safely
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        post_save.connect(
            handle_password_change,
            sender=User,
            dispatch_uid="authentication_password_changed",
            weak=False
        )
        
        # Register custom security event signals
        from .signals import (
            account_locked,
            suspicious_activity_detected,
        )
        
        account_locked.connect(
            handle_account_lockout,
            dispatch_uid="authentication_account_locked",
            weak=False
        )
        
        suspicious_activity_detected.connect(
            handle_suspicious_activity,
            dispatch_uid="authentication_suspicious_activity",
            weak=False
        )
    
    def _register_cache_invalidation_signals(self) -> None:
        """Register signals for authentication-related cache invalidation."""
        from .signals import (
            invalidate_user_cache,
            invalidate_permission_cache,
        )
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        post_save.connect(
            invalidate_user_cache,
            sender=User,
            dispatch_uid="authentication_invalidate_user_cache",
            weak=False
        )
        
        # Invalidate cache when settings change
        setting_changed.connect(
            invalidate_permission_cache,
            dispatch_uid="authentication_invalidate_permission_cache",
            weak=False
        )
