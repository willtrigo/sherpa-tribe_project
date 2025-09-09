"""
Common application configuration.
"""

from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Configuration for the common application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.common'
    verbose_name = 'Common Components'

    def ready(self) -> None:
        """
        Initialize application when Django starts.
        Import any signals or perform startup tasks here.
        """
        # Import signals to ensure they are registered
        try:
            from . import signals  # noqa: F401
        except ImportError:
            pass
