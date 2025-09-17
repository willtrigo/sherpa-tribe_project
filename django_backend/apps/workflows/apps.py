"""
Django application configuration for the workflows module.

This module handles task workflow management, automation rules,
and business logic for the task management system.
"""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class WorkflowsConfig(AppConfig):
    """
    Application configuration for the workflows module.
    
    Handles workflow engine initialization, signal connections,
    and automation rule registration for task lifecycle management.
    """
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.workflows'
    verbose_name = 'Task Workflows & Automation'
    
    def ready(self) -> None:
        """
        Initialize workflow system components when Django starts.
        
        This method is called once Django has fully loaded all models
        and is ready to receive requests. It performs the following:
        
        - Imports and registers signal handlers
        - Initializes workflow engines and automation rules
        - Sets up workflow state validators
        - Registers custom workflow permissions
        """
        self._register_signal_handlers()
        self._initialize_workflow_engines()
        self._setup_automation_rules()
        
    def _register_signal_handlers(self) -> None:
        """
        Register Django signals for workflow automation.
        
        Imports signal handlers that respond to model changes
        and trigger appropriate workflow transitions.
        """
        try:
            # Import signal handlers - these will auto-register via decorators
            from apps.workflows import signals  # noqa: F401
        except ImportError as exc:
            # Log the import error but don't crash the application
            # This allows for graceful degradation if signals aren't implemented yet
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Could not import workflow signals: {exc}. "
                "Workflow automation may be limited."
            )
    
    def _initialize_workflow_engines(self) -> None:
        """
        Initialize workflow engines and state machines.
        
        Sets up the workflow engine registry and loads
        predefined workflow templates and rules.
        """
        try:
            from apps.workflows.engines import WorkflowEngineRegistry
            from apps.workflows.rules import AutomationRuleRegistry
            
            # Initialize the workflow engine registry
            workflow_registry = WorkflowEngineRegistry.get_instance()
            workflow_registry.initialize_default_workflows()
            
            # Initialize automation rule registry
            rule_registry = AutomationRuleRegistry.get_instance()
            rule_registry.load_default_rules()
            
        except ImportError as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Could not initialize workflow engines: {exc}. "
                "Advanced workflow features may be unavailable."
            )
    
    def _setup_automation_rules(self) -> None:
        """
        Configure automation rules and business logic validators.
        
        Registers custom automation rules, SLA policies,
        and workflow transition validators.
        """
        try:
            from apps.workflows.rules import (
                register_default_automation_rules,
                register_sla_policies,
                register_transition_validators
            )
            
            # Register core automation rules
            register_default_automation_rules()
            
            # Register SLA tracking and escalation policies
            register_sla_policies()
            
            # Register workflow state transition validators
            register_transition_validators()
            
        except ImportError as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Could not setup automation rules: {exc}. "
                "Some workflow automation features may be disabled."
            )
    
    @staticmethod
    def create_default_workflows(sender, **kwargs) -> None:
        """
        Post-migration signal handler to create default workflow templates.
        
        Args:
            sender: The sender of the post_migrate signal
            **kwargs: Additional signal arguments
            
        This method creates default workflow templates and automation
        rules after database migrations are complete.
        """
        if sender.name != 'apps.workflows':
            return
            
        try:
            from apps.workflows.models import (
                WorkflowTemplate,
                AutomationRule,
                WorkflowState
            )
            
            # Create default workflow states if they don't exist
            default_states = [
                ('new', 'New', 'Task has been created'),
                ('in_progress', 'In Progress', 'Task is being worked on'),
                ('review', 'Under Review', 'Task is being reviewed'),
                ('completed', 'Completed', 'Task has been completed'),
                ('cancelled', 'Cancelled', 'Task has been cancelled'),
            ]
            
            for code, name, description in default_states:
                WorkflowState.objects.get_or_create(
                    code=code,
                    defaults={
                        'name': name,
                        'description': description,
                        'is_active': True,
                    }
                )
            
            # Create default workflow template
            default_template, created = WorkflowTemplate.objects.get_or_create(
                name='Standard Task Workflow',
                defaults={
                    'description': 'Standard workflow for task management',
                    'is_default': True,
                    'is_active': True,
                }
            )
            
            if created:
                # Set up default state transitions
                states = WorkflowState.objects.filter(
                    code__in=['new', 'in_progress', 'review', 'completed', 'cancelled']
                )
                default_template.allowed_states.set(states)
            
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(
                f"Error creating default workflows: {exc}. "
                "Manual workflow setup may be required."
            )


# Connect the post-migrate signal
post_migrate.connect(
    WorkflowsConfig.create_default_workflows,
    dispatch_uid='workflows_create_defaults'
)
