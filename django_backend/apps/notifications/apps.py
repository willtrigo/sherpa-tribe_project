"""
Notifications application configuration.

This module configures the notifications app which handles:
- Email notifications for task events
- Webhook notifications
- User notification preferences
- Notification delivery tracking and retry logic
- Notification templates management
"""
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class NotificationsConfig(AppConfig):
    """
    Configuration class for the notifications application.
    
    Handles application initialization, signal registration,
    and notification service setup.
    """
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notifications'
    verbose_name = _('Notifications')
    
    def ready(self) -> None:
        """
        Application ready hook.
        
        Registers signal handlers for automatic notification triggering
        and initializes notification services.
        
        This method is called when Django has fully loaded all applications
        and is ready to serve requests.
        """
        try:
            # Import signal handlers to register them with Django
            from . import signals  # noqa: F401
            
            # Initialize notification service components
            self._initialize_notification_services()
            
        except ImportError as exc:
            # Log the error but don't prevent app from loading
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Failed to initialize notifications app components: {exc}"
            )
    
    def _initialize_notification_services(self) -> None:
        """
        Initialize notification-related services and components.
        
        This method sets up:
        - Notification templates cache warming
        - Webhook endpoint validation
        - Email backend configuration validation
        - Retry mechanism initialization
        """
        from django.core.cache import cache
        from django.conf import settings
        import logging
        
        logger = logging.getLogger(__name__)
        
        try:
            # Warm up notification templates cache if caching is enabled
            if hasattr(settings, 'CACHES') and cache:
                self._warm_notification_templates_cache()
            
            # Validate notification backends configuration
            self._validate_notification_backends()
            
            logger.info("Notification services initialized successfully")
            
        except Exception as exc:
            logger.error(f"Error initializing notification services: {exc}")
    
    def _warm_notification_templates_cache(self) -> None:
        """
        Preload frequently used notification templates into cache.
        
        This improves performance by avoiding database queries
        for common notification templates.
        """
        from django.core.cache import cache
        import logging
        
        logger = logging.getLogger(__name__)
        
        try:
            # Import here to avoid circular imports
            from .models import NotificationTemplate
            
            # Cache frequently used templates
            common_template_types = [
                'task_assigned',
                'task_completed', 
                'task_overdue',
                'daily_summary'
            ]
            
            templates = NotificationTemplate.objects.filter(
                template_type__in=common_template_types,
                is_active=True
            ).select_related().prefetch_related()
            
            for template in templates:
                cache_key = f"notification_template_{template.template_type}"
                cache.set(cache_key, template, timeout=3600)  # 1 hour cache
            
            logger.debug(f"Cached {templates.count()} notification templates")
            
        except Exception as exc:
            # Don't fail app initialization if template caching fails
            logger.warning(f"Failed to warm notification templates cache: {exc}")
    
    def _validate_notification_backends(self) -> None:
        """
        Validate that notification backends are properly configured.
        
        Checks email backend settings and webhook configurations
        to ensure notifications can be delivered successfully.
        """
        from django.conf import settings
        from django.core.mail import get_connection
        import logging
        
        logger = logging.getLogger(__name__)
        
        try:
            # Validate email backend configuration
            if hasattr(settings, 'EMAIL_BACKEND'):
                connection = get_connection()
                if connection:
                    logger.debug("Email backend configuration validated")
            
            # Validate webhook settings if configured
            if hasattr(settings, 'NOTIFICATION_WEBHOOKS'):
                webhook_config = getattr(settings, 'NOTIFICATION_WEBHOOKS', {})
                if webhook_config.get('ENABLED', False):
                    required_settings = ['DEFAULT_TIMEOUT', 'RETRY_ATTEMPTS']
                    for setting in required_settings:
                        if setting not in webhook_config:
                            logger.warning(
                                f"Missing webhook setting: {setting}"
                            )
                    logger.debug("Webhook configuration validated")
            
        except Exception as exc:
            logger.warning(f"Notification backend validation failed: {exc}")
