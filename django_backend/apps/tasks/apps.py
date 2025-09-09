"""
Task management application configuration.

This module configures the tasks application for the Enterprise Task Management System,
including signal registration, application metadata, and initialization hooks.
"""

from django.apps import AppConfig
from django.core.checks import Error, register
from django.db import connection
from django.utils.translation import gettext_lazy as _


class TasksConfig(AppConfig):
    """
    Configuration class for the tasks application.
    
    Handles application initialization, signal registration, and system checks
    for the task management functionality.
    """
    
    # Application metadata
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.tasks'
    label = 'tasks'
    verbose_name = _('Task Management')
    
    def ready(self) -> None:
        """
        Perform application initialization when Django starts.
        
        This method is called when the application registry is fully populated.
        It registers signals, performs system checks, and initializes components
        that require the Django environment to be fully loaded.
        
        Raises:
            ImportError: If required modules cannot be imported.
        """
        try:
            # Import and register signal handlers
            self._register_signals()
            
            # Register custom system checks
            self._register_system_checks()
            
            # Initialize task-related components
            self._initialize_components()
            
        except ImportError as exc:
            # Log import errors but don't prevent Django from starting
            # in case of missing optional dependencies
            import logging
            logger = logging.getLogger(f'{self.name}.config')
            logger.warning(
                'Failed to initialize some task components: %s', 
                str(exc)
            )
    
    def _register_signals(self) -> None:
        """
        Register Django signals for task-related operations.
        
        Imports and connects signal handlers for:
        - Task lifecycle events (create, update, delete)
        - Assignment notifications
        - Status change workflows
        - Audit trail logging
        """
        # Import signals module to register handlers
        # This is done inside ready() to avoid circular imports
        from . import signals  # noqa: F401
        
        # Import and register Celery task signals if available
        try:
            from . import tasks  # noqa: F401
        except ImportError:
            pass
    
    def _register_system_checks(self) -> None:
        """
        Register custom Django system checks for the tasks application.
        
        These checks validate configuration and ensure the application
        is properly configured for production use.
        """
        @register('tasks')
        def check_task_configuration(app_configs, **kwargs) -> list[Error]:
            """
            Validate task application configuration.
            
            Args:
                app_configs: List of application configurations to check.
                **kwargs: Additional keyword arguments.
                
            Returns:
                List of Error objects representing configuration issues.
            """
            errors = []
            
            # Check if required database extensions are available
            if self._is_postgresql_backend():
                errors.extend(self._check_postgresql_features())
            
            # Check Celery configuration
            errors.extend(self._check_celery_configuration())
            
            # Check Redis configuration for caching
            errors.extend(self._check_redis_configuration())
            
            return errors
    
    def _initialize_components(self) -> None:
        """
        Initialize task management components.
        
        Sets up:
        - Task workflow engines
        - Priority calculation algorithms
        - Search indexing (if configured)
        - Notification systems
        """
        # Initialize workflow engine
        try:
            from .workflows.engines import WorkflowEngine
            WorkflowEngine.initialize()
        except ImportError:
            pass
        
        # Initialize search indexing if PostgreSQL full-text search is available
        if self._is_postgresql_backend():
            try:
                from .search import SearchIndexManager
                SearchIndexManager.initialize()
            except (ImportError, AttributeError):
                pass
    
    def _is_postgresql_backend(self) -> bool:
        """
        Check if PostgreSQL is being used as the database backend.
        
        Returns:
            bool: True if PostgreSQL is the database backend.
        """
        try:
            return 'postgresql' in connection.settings_dict['ENGINE'].lower()
        except (KeyError, AttributeError):
            return False
    
    def _check_postgresql_features(self) -> list[Error]:
        """
        Validate PostgreSQL-specific features and extensions.
        
        Returns:
            List of Error objects for missing PostgreSQL features.
        """
        errors = []
        
        # Check for required PostgreSQL extensions
        required_extensions = ['pg_trgm', 'unaccent']
        
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT extname FROM pg_extension WHERE extname = ANY(%s)",
                    [required_extensions]
                )
                available_extensions = {row[0] for row in cursor.fetchall()}
                
                missing_extensions = set(required_extensions) - available_extensions
                
                for extension in missing_extensions:
                    errors.append(
                        Error(
                            f'PostgreSQL extension "{extension}" is not installed',
                            hint=f'Run: CREATE EXTENSION IF NOT EXISTS {extension};',
                            obj=self.name,
                            id='tasks.E001'
                        )
                    )
        except Exception:
            # Don't fail if we can't check extensions
            pass
        
        return errors
    
    def _check_celery_configuration(self) -> list[Error]:
        """
        Validate Celery configuration for background tasks.
        
        Returns:
            List of Error objects for Celery configuration issues.
        """
        errors = []
        
        try:
            from django.conf import settings
            
            # Check if Celery broker is configured
            if not hasattr(settings, 'CELERY_BROKER_URL'):
                errors.append(
                    Error(
                        'CELERY_BROKER_URL is not configured',
                        hint='Configure Redis or RabbitMQ as Celery broker',
                        obj=self.name,
                        id='tasks.E002'
                    )
                )
            
            # Check if result backend is configured
            if not hasattr(settings, 'CELERY_RESULT_BACKEND'):
                errors.append(
                    Error(
                        'CELERY_RESULT_BACKEND is not configured',
                        hint='Configure Redis as Celery result backend',
                        obj=self.name,
                        id='tasks.E003'
                    )
                )
                
        except ImportError:
            pass
        
        return errors
    
    def _check_redis_configuration(self) -> list[Error]:
        """
        Validate Redis configuration for caching.
        
        Returns:
            List of Error objects for Redis configuration issues.
        """
        errors = []
        
        try:
            from django.conf import settings
            from django.core.cache import cache
            
            # Check if Redis cache is configured
            if 'redis' not in str(settings.CACHES.get('default', {}).get('BACKEND', '')).lower():
                errors.append(
                    Error(
                        'Redis cache backend is not configured',
                        hint='Configure Redis as the default cache backend',
                        obj=self.name,
                        id='tasks.E004'
                    )
                )
            else:
                # Test Redis connection
                try:
                    cache.set('health_check', 'ok', 10)
                    if cache.get('health_check') != 'ok':
                        raise ConnectionError('Cache write/read failed')
                except Exception as exc:
                    errors.append(
                        Error(
                            f'Redis connection failed: {exc}',
                            hint='Check Redis server status and connection settings',
                            obj=self.name,
                            id='tasks.E005'
                        )
                    )
                        
        except (ImportError, AttributeError):
            pass
        
        return errors
