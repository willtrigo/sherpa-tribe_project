"""
Users application module.

This module handles user management, authentication, and team functionalities
for the Enterprise Task Management System.

The users app provides:
- Extended Django User model with additional fields
- User profile management
- Team creation and management
- User preference handling
- Integration with task assignment workflows

Dependencies:
- Django's built-in authentication system
- Custom managers for advanced user queries
- Signal handlers for user lifecycle events
"""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """
    Configuration class for the users application.
    
    Handles app-specific configuration including:
    - Auto field configuration
    - Signal registration
    - App initialization tasks
    """
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    verbose_name = 'User Management'
    
    def ready(self) -> None:
        """
        Perform initialization tasks when the app is ready.
        
        This method is called when Django has loaded all models and is ready
        to handle requests. It's the appropriate place to register signals
        and perform other initialization tasks.
        """
        try:
            # Import and register signal handlers
            from . import signals  # noqa: F401
        except ImportError:
            # Gracefully handle missing signals module during development
            pass


# Export the config class as default_app_config for Django discovery
default_app_config = 'apps.users.UsersConfig'

# Version information
__version__ = '1.0.0'
__author__ = 'Enterprise Task Management Team'

# Module-level constants
USER_CACHE_TIMEOUT = 300  # 5 minutes
TEAM_CACHE_PREFIX = 'team:'
USER_PROFILE_CACHE_PREFIX = 'user_profile:'

# Export commonly used items for easier imports
__all__ = [
    'UsersConfig',
    'USER_CACHE_TIMEOUT',
    'TEAM_CACHE_PREFIX', 
    'USER_PROFILE_CACHE_PREFIX',
]
