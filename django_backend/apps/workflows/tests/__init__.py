"""
Workflow Testing Module Initialization

This module provides comprehensive test utilities, fixtures, and base classes
for testing the workflow engine components. It includes factory patterns,
mock objects, and shared test utilities to ensure consistent and maintainable
testing across all workflow-related functionality.

Test Categories:
    - Unit Tests: Individual component testing
    - Integration Tests: Cross-component workflow testing
    - Performance Tests: Workflow execution timing and resource usage
    - Edge Case Tests: Boundary conditions and error scenarios

Usage:
    from apps.workflows.tests import (
        WorkflowTestCase,
        WorkflowEngineTestMixin,
        create_test_workflow,
        mock_task_execution
    )
"""

from typing import Dict, Any, List, Optional, Type, Union, Callable
from unittest import TestCase
from unittest.mock import Mock, MagicMock, patch
from django.test import TestCase as DjangoTestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from decimal import Decimal
import json
import uuid
import factory
from factory.django import DjangoModelFactory
from faker import Faker

# Import workflow-related models and engines
from apps.workflows.models import (
    Workflow, WorkflowStep, WorkflowExecution, 
    WorkflowRule, WorkflowTransition
)
from apps.workflows.engines import WorkflowEngine, WorkflowExecutor
from apps.workflows.rules import RuleEngine, ValidationRule
from apps.tasks.models import Task, TaskStatus, TaskPriority
from apps.users.models import User, Team


fake = Faker()
User = get_user_model()

# Test Data Constants
class WorkflowTestConstants:
    """Constants used across workflow tests for consistent data generation"""
    
    DEFAULT_WORKFLOW_NAME = "Test Workflow"
    DEFAULT_STEP_NAME = "Test Step"
    DEFAULT_RULE_NAME = "Test Rule"
    
    # Workflow Types
    WORKFLOW_TYPES = [
        'task_approval', 'bug_triage', 'feature_deployment', 
        'security_review', 'quality_assurance', 'user_onboarding'
    ]
    
    # Step Types
    STEP_TYPES = [
        'manual', 'automatic', 'conditional', 'parallel', 
        'sequential', 'approval', 'notification', 'validation'
    ]
    
    # Rule Types
    RULE_TYPES = [
        'assignment', 'validation', 'escalation', 'notification',
        'status_change', 'priority_update', 'deadline_check'
    ]
    
    # Status Values
    EXECUTION_STATUSES = ['pending', 'running', 'completed', 'failed', 'cancelled']
    STEP_STATUSES = ['not_started', 'in_progress', 'completed', 'skipped', 'failed']


class WorkflowModelFactory(DjangoModelFactory):
    """Factory for creating Workflow model instances with realistic test data"""
    
    class Meta:
        model = Workflow
        django_get_or_create = ('name', 'version')
    
    name = factory.LazyAttribute(lambda obj: f"Workflow_{fake.word()}_{uuid.uuid4().hex[:8]}")
    description = factory.LazyAttribute(lambda obj: fake.paragraph(nb_sentences=3))
    version = factory.Sequence(lambda n: f"v{n // 10 + 1}.{n % 10}")
    workflow_type = factory.LazyAttribute(lambda obj: fake.random_element(WorkflowTestConstants.WORKFLOW_TYPES))
    is_active = True
    created_at = factory.LazyFunction(timezone.now)
    updated_at = factory.LazyFunction(timezone.now)
    metadata = factory.LazyAttribute(lambda obj: {
        'created_by_test': True,
        'complexity_score': fake.random_int(1, 10),
        'expected_duration_hours': fake.random_int(1, 72),
        'tags': fake.words(nb=fake.random_int(2, 5))
    })


class WorkflowStepFactory(DjangoModelFactory):
    """Factory for creating WorkflowStep model instances"""
    
    class Meta:
        model = WorkflowStep
        django_get_or_create = ('workflow', 'name', 'order')
    
    workflow = factory.SubFactory(WorkflowModelFactory)
    name = factory.LazyAttribute(lambda obj: f"Step_{fake.word()}_{uuid.uuid4().hex[:6]}")
    description = factory.LazyAttribute(lambda obj: fake.sentence())
    step_type = factory.LazyAttribute(lambda obj: fake.random_element(WorkflowTestConstants.STEP_TYPES))
    order = factory.Sequence(lambda n: n + 1)
    is_required = factory.LazyAttribute(lambda obj: fake.boolean(chance_of_getting_true=80))
    timeout_hours = factory.LazyAttribute(lambda obj: fake.random_int(1, 48) if fake.boolean() else None)
    retry_count = factory.LazyAttribute(lambda obj: fake.random_int(0, 5))
    configuration = factory.LazyAttribute(lambda obj: {
        'auto_assign': fake.boolean(),
        'require_approval': fake.boolean(),
        'notification_enabled': fake.boolean(),
        'escalation_hours': fake.random_int(1, 24) if fake.boolean() else None
    })


class WorkflowRuleFactory(DjangoModelFactory):
    """Factory for creating WorkflowRule model instances"""
    
    class Meta:
        model = WorkflowRule
        django_get_or_create = ('workflow', 'name')
    
    workflow = factory.SubFactory(WorkflowModelFactory)
    name = factory.LazyAttribute(lambda obj: f"Rule_{fake.word()}_{uuid.uuid4().hex[:6]}")
    rule_type = factory.LazyAttribute(lambda obj: fake.random_element(WorkflowTestConstants.RULE_TYPES))
    conditions = factory.LazyAttribute(lambda obj: {
        'field': fake.random_element(['status', 'priority', 'assigned_to', 'created_at']),
        'operator': fake.random_element(['equals', 'not_equals', 'greater_than', 'less_than', 'contains']),
        'value': fake.word(),
        'logical_operator': fake.random_element(['AND', 'OR']) if fake.boolean() else None
    })
    actions = factory.LazyAttribute(lambda obj: {
        'action_type': fake.random_element(['assign', 'notify', 'update_status', 'escalate']),
        'parameters': {
            'target': fake.word(),
            'message_template': fake.sentence() if fake.boolean() else None
        }
    })
    is_active = True
    priority = factory.LazyAttribute(lambda obj: fake.random_int(1, 10))


class WorkflowExecutionFactory(DjangoModelFactory):
    """Factory for creating WorkflowExecution model instances"""
    
    class Meta:
        model = WorkflowExecution
        django_get_or_create = ('workflow', 'execution_id')
    
    workflow = factory.SubFactory(WorkflowModelFactory)
    execution_id = factory.LazyAttribute(lambda obj: str(uuid.uuid4()))
    status = factory.LazyAttribute(lambda obj: fake.random_element(WorkflowTestConstants.EXECUTION_STATUSES))
    started_at = factory.LazyFunction(timezone.now)
    completed_at = factory.LazyAttribute(lambda obj: 
        timezone.now() + timedelta(hours=fake.random_int(1, 24)) 
        if obj.status == 'completed' else None
    )
    context_data = factory.LazyAttribute(lambda obj: {
        'task_id': fake.random_int(1, 1000),
        'user_id': fake.random_int(1, 100),
        'request_source': fake.random_element(['api', 'web', 'scheduler']),
        'environment': fake.random_element(['development', 'staging', 'production'])
    })
    error_details = factory.LazyAttribute(lambda obj: 
        {
            'error_code': fake.random_element(['TIMEOUT', 'VALIDATION_ERROR', 'RESOURCE_UNAVAILABLE']),
            'message': fake.sentence(),
            'stack_trace': fake.text(max_nb_chars=500)
        } if obj.status == 'failed' else None
    )


class MockWorkflowEngine:
    """Mock workflow engine for testing without actual workflow execution"""
    
    def __init__(self, return_success: bool = True, execution_time: float = 0.1):
        self.return_success = return_success
        self.execution_time = execution_time
        self.executed_workflows = []
        self.call_count = 0
    
    def execute_workflow(self, workflow: 'Workflow', context: Dict[str, Any]) -> Dict[str, Any]:
        """Mock workflow execution with configurable results"""
        self.call_count += 1
        self.executed_workflows.append({
            'workflow_id': workflow.id,
            'workflow_name': workflow.name,
            'context': context,
            'timestamp': timezone.now()
        })
        
        if self.return_success:
            return {
                'success': True,
                'execution_id': str(uuid.uuid4()),
                'status': 'completed',
                'execution_time': self.execution_time,
                'steps_completed': fake.random_int(1, 10)
            }
        else:
            return {
                'success': False,
                'execution_id': str(uuid.uuid4()),
                'status': 'failed',
                'error': 'Mock execution failure',
                'error_code': 'MOCK_ERROR'
            }
    
    def validate_workflow(self, workflow: 'Workflow') -> Dict[str, Any]:
        """Mock workflow validation"""
        return {
            'valid': self.return_success,
            'errors': [] if self.return_success else ['Mock validation error'],
            'warnings': ['Mock warning'] if fake.boolean() else []
        }


class WorkflowTestMixin:
    """Mixin providing common workflow testing utilities and assertions"""
    
    def setUp(self):
        """Set up common test fixtures and mocks"""
        super().setUp() if hasattr(super(), 'setUp') else None
        
        # Create test users
        self.test_user = self.create_test_user()
        self.admin_user = self.create_test_user(is_staff=True, is_superuser=True)
        
        # Create mock engines
        self.mock_engine = MockWorkflowEngine()
        self.mock_rule_engine = Mock(spec=RuleEngine)
        
        # Patch workflow components
        self.engine_patcher = patch('apps.workflows.engines.WorkflowEngine', return_value=self.mock_engine)
        self.rule_engine_patcher = patch('apps.workflows.rules.RuleEngine', return_value=self.mock_rule_engine)
        
        self.mock_workflow_engine = self.engine_patcher.start()
        self.mock_rule_engine_instance = self.rule_engine_patcher.start()
    
    def tearDown(self):
        """Clean up test fixtures and stop patches"""
        self.engine_patcher.stop()
        self.rule_engine_patcher.stop()
        super().tearDown() if hasattr(super(), 'tearDown') else None
    
    def create_test_user(self, **kwargs) -> User:
        """Create a test user with optional custom attributes"""
        defaults = {
            'username': f'testuser_{uuid.uuid4().hex[:8]}',
            'email': fake.email(),
            'first_name': fake.first_name(),
            'last_name': fake.last_name(),
            'is_active': True
        }
        defaults.update(kwargs)
        return User.objects.create_user(**defaults)
    
    def create_test_workflow(self, **kwargs) -> 'Workflow':
        """Create a test workflow with optional custom attributes"""
        return WorkflowModelFactory.create(**kwargs)
    
    def create_test_workflow_with_steps(self, step_count: int = 3, **workflow_kwargs) -> 'Workflow':
        """Create a workflow with a specified number of steps"""
        workflow = self.create_test_workflow(**workflow_kwargs)
        
        for i in range(step_count):
            WorkflowStepFactory.create(
                workflow=workflow,
                order=i + 1,
                name=f"Step {i + 1}"
            )
        
        return workflow
    
    def create_complex_workflow(self) -> 'Workflow':
        """Create a complex workflow for integration testing"""
        workflow = self.create_test_workflow(
            name="Complex Test Workflow",
            workflow_type="task_approval"
        )
        
        # Create sequential steps
        steps = []
        step_configs = [
            {'name': 'Initial Review', 'step_type': 'manual', 'is_required': True},
            {'name': 'Automated Validation', 'step_type': 'automatic', 'is_required': True},
            {'name': 'Manager Approval', 'step_type': 'approval', 'is_required': True},
            {'name': 'Final Notification', 'step_type': 'notification', 'is_required': False}
        ]
        
        for i, config in enumerate(step_configs):
            step = WorkflowStepFactory.create(
                workflow=workflow,
                order=i + 1,
                **config
            )
            steps.append(step)
        
        # Create rules
        WorkflowRuleFactory.create(
            workflow=workflow,
            name="High Priority Auto-Assignment",
            rule_type="assignment",
            conditions={'field': 'priority', 'operator': 'equals', 'value': 'high'}
        )
        
        WorkflowRuleFactory.create(
            workflow=workflow,
            name="Overdue Escalation",
            rule_type="escalation",
            conditions={'field': 'due_date', 'operator': 'less_than', 'value': 'now'}
        )
        
        return workflow
    
    def assert_workflow_execution_success(self, result: Dict[str, Any]):
        """Assert that a workflow execution was successful"""
        self.assertTrue(result.get('success'), f"Workflow execution failed: {result}")
        self.assertIn('execution_id', result)
        self.assertEqual(result.get('status'), 'completed')
    
    def assert_workflow_execution_failure(self, result: Dict[str, Any], expected_error_code: str = None):
        """Assert that a workflow execution failed as expected"""
        self.assertFalse(result.get('success'), "Expected workflow execution to fail")
        self.assertIn('error', result)
        if expected_error_code:
            self.assertEqual(result.get('error_code'), expected_error_code)
    
    def assert_workflow_step_order(self, workflow: 'Workflow'):
        """Assert that workflow steps are properly ordered"""
        steps = workflow.steps.all().order_by('order')
        for i, step in enumerate(steps):
            self.assertEqual(step.order, i + 1, f"Step {step.name} has incorrect order")
    
    def assert_workflow_rules_active(self, workflow: 'Workflow'):
        """Assert that all workflow rules are properly configured"""
        rules = workflow.rules.filter(is_active=True)
        self.assertGreater(rules.count(), 0, "Workflow should have at least one active rule")
        
        for rule in rules:
            self.assertIsNotNone(rule.conditions, f"Rule {rule.name} missing conditions")
            self.assertIsNotNone(rule.actions, f"Rule {rule.name} missing actions")


class WorkflowTestCase(WorkflowTestMixin, DjangoTestCase):
    """Base test case for workflow unit tests with database transactions"""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data once for the entire test class"""
        super().setUpTestData() if hasattr(super(), 'setUpTestData') else None
        
        # Create shared test data that won't be modified
        cls.shared_workflow = WorkflowModelFactory.create(
            name="Shared Test Workflow",
            is_active=True
        )


class WorkflowTransactionTestCase(WorkflowTestMixin, TransactionTestCase):
    """Test case for workflow tests requiring database transaction control"""
    
    def setUp(self):
        """Set up test environment with transaction support"""
        super().setUp()
        
        # Enable transaction testing features
        self.atomic_requests = True
    
    def test_workflow_atomic_execution(self):
        """Test that workflow execution is atomic and handles rollbacks properly"""
        workflow = self.create_test_workflow()
        
        with transaction.atomic():
            # Simulate workflow execution that might fail
            execution = WorkflowExecutionFactory.create(
                workflow=workflow,
                status='running'
            )
            
            # Test rollback scenario
            try:
                raise ValidationError("Simulated validation error")
            except ValidationError:
                # Verify that the transaction was rolled back
                self.assertFalse(
                    WorkflowExecution.objects.filter(id=execution.id).exists()
                )


class WorkflowPerformanceTestMixin:
    """Mixin for performance testing of workflow components"""
    
    def setUp(self):
        super().setUp() if hasattr(super(), 'setUp') else None
        self.performance_threshold_seconds = 5.0
    
    def assert_execution_time_within_threshold(self, execution_time: float, custom_threshold: float = None):
        """Assert that execution time is within acceptable limits"""
        threshold = custom_threshold or self.performance_threshold_seconds
        self.assertLessEqual(
            execution_time, 
            threshold,
            f"Execution time {execution_time}s exceeded threshold {threshold}s"
        )
    
    def measure_workflow_execution_time(self, workflow: 'Workflow', context: Dict[str, Any]) -> float:
        """Measure and return workflow execution time"""
        start_time = timezone.now()
        self.mock_engine.execute_workflow(workflow, context)
        end_time = timezone.now()
        
        return (end_time - start_time).total_seconds()


# Utility functions for test data creation
def create_test_workflow_context(task_id: int = None, user_id: int = None, **kwargs) -> Dict[str, Any]:
    """Create a realistic workflow context for testing"""
    context = {
        'task_id': task_id or fake.random_int(1, 1000),
        'user_id': user_id or fake.random_int(1, 100),
        'timestamp': timezone.now().isoformat(),
        'source': 'test',
        'environment': 'testing',
        'request_id': str(uuid.uuid4())
    }
    context.update(kwargs)
    return context


def mock_task_execution(success: bool = True, delay: float = 0.0) -> Callable:
    """Decorator to mock task execution with configurable results"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            if delay > 0:
                import time
                time.sleep(delay)
            
            if success:
                return func(*args, **kwargs)
            else:
                raise Exception("Mocked task execution failure")
        return wrapper
    return decorator


# Export commonly used test utilities
__all__ = [
    'WorkflowTestCase',
    'WorkflowTransactionTestCase', 
    'WorkflowTestMixin',
    'WorkflowPerformanceTestMixin',
    'WorkflowModelFactory',
    'WorkflowStepFactory',
    'WorkflowRuleFactory',
    'WorkflowExecutionFactory',
    'MockWorkflowEngine',
    'WorkflowTestConstants',
    'create_test_workflow_context',
    'mock_task_execution'
]
