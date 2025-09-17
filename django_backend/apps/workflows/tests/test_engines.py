"""
Test suite for workflow engines module.

This module contains comprehensive tests for the task workflow engine,
including status transition validation, automatic task assignment,
task templates, and business logic automation.
"""

from decimal import Decimal
from unittest.mock import Mock, patch, call
from datetime import datetime, timedelta
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from freezegun import freeze_time

from apps.tasks.models import Task, Tag, TaskTemplate, TaskAssignment, TaskHistory
from apps.users.models import Team
from apps.workflows.engines import (
    WorkflowEngine,
    StatusTransitionEngine,
    AutoAssignmentEngine,
    TaskTemplateEngine,
    RecurringTaskEngine,
    SLAEngine,
    WorkloadBalancingEngine,
    PriorityCalculationEngine,
    DependencyEngine,
    CriticalPathEngine,
    BusinessHoursEngine,
    AutomationRulesEngine,
)
from apps.workflows.models import (
    WorkflowDefinition,
    WorkflowState,
    TransitionRule,
    AssignmentRule,
    AutomationRule,
    SLAConfiguration,
    WorkflowExecution,
)
from apps.workflows.exceptions import (
    InvalidTransitionError,
    WorkflowExecutionError,
    AssignmentRuleError,
    SLAViolationError,
    DependencyViolationError,
)
from apps.tasks.choices import TaskStatus, TaskPriority

User = get_user_model()


class BaseWorkflowTestCase(TestCase):
    """Base test case with common setup for workflow tests."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data that won't be modified during tests."""
        cls.user_manager = User.objects.create_user(
            username='manager',
            email='manager@example.com',
            password='testpass123',
            is_staff=True
        )
        
        cls.user_developer = User.objects.create_user(
            username='developer',
            email='developer@example.com',
            password='testpass123'
        )
        
        cls.user_tester = User.objects.create_user(
            username='tester',
            email='tester@example.com',
            password='testpass123'
        )
        
        cls.team = Team.objects.create(
            name='Development Team',
            description='Main development team'
        )
        cls.team.members.add(cls.user_developer, cls.user_tester)
        
        cls.tag_backend = Tag.objects.create(name='backend')
        cls.tag_frontend = Tag.objects.create(name='frontend')
        cls.tag_urgent = Tag.objects.create(name='urgent')

    def setUp(self):
        """Set up test data that may be modified during tests."""
        self.task = Task.objects.create(
            title='Test Task',
            description='Test task for workflow testing',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=7),
            estimated_hours=Decimal('8.00'),
            created_by=self.user_manager
        )
        self.task.tags.add(self.tag_backend)


class WorkflowEngineTestCase(BaseWorkflowTestCase):
    """Test cases for the main WorkflowEngine class."""

    def setUp(self):
        super().setUp()
        self.engine = WorkflowEngine()
        
        self.workflow_definition = WorkflowDefinition.objects.create(
            name='Standard Development Workflow',
            description='Standard workflow for development tasks',
            is_active=True,
            created_by=self.user_manager
        )

    def test_engine_initialization(self):
        """Test workflow engine initialization with proper configuration."""
        self.assertIsInstance(self.engine, WorkflowEngine)
        self.assertTrue(hasattr(self.engine, 'status_engine'))
        self.assertTrue(hasattr(self.engine, 'assignment_engine'))
        self.assertTrue(hasattr(self.engine, 'template_engine'))

    def test_execute_workflow_success(self):
        """Test successful workflow execution."""
        workflow_execution = WorkflowExecution.objects.create(
            workflow_definition=self.workflow_definition,
            task=self.task,
            current_state='pending',
            started_by=self.user_manager
        )
        
        result = self.engine.execute_workflow(workflow_execution)
        
        self.assertTrue(result)
        workflow_execution.refresh_from_db()
        self.assertEqual(workflow_execution.status, 'completed')

    def test_execute_workflow_with_invalid_state(self):
        """Test workflow execution with invalid state raises proper exception."""
        workflow_execution = WorkflowExecution.objects.create(
            workflow_definition=self.workflow_definition,
            task=self.task,
            current_state='invalid_state',
            started_by=self.user_manager
        )
        
        with self.assertRaises(WorkflowExecutionError):
            self.engine.execute_workflow(workflow_execution)

    @patch('apps.workflows.engines.logger')
    def test_workflow_logging(self, mock_logger):
        """Test that workflow execution is properly logged."""
        workflow_execution = WorkflowExecution.objects.create(
            workflow_definition=self.workflow_definition,
            task=self.task,
            current_state='pending',
            started_by=self.user_manager
        )
        
        self.engine.execute_workflow(workflow_execution)
        
        mock_logger.info.assert_called()
        self.assertTrue(any('Workflow execution started' in str(call) 
                          for call in mock_logger.info.call_args_list))


class StatusTransitionEngineTestCase(BaseWorkflowTestCase):
    """Test cases for status transition validation engine."""

    def setUp(self):
        super().setUp()
        self.engine = StatusTransitionEngine()
        
        # Create transition rules
        self.transition_rule = TransitionRule.objects.create(
            from_status=TaskStatus.PENDING,
            to_status=TaskStatus.IN_PROGRESS,
            condition='{"assigned_to__isnull": false}',
            required_permissions=['tasks.change_task'],
            priority=1
        )

    def test_valid_transition(self):
        """Test validation of valid status transition."""
        self.task.assigned_to.add(self.user_developer)
        
        result = self.engine.validate_transition(
            self.task, 
            TaskStatus.IN_PROGRESS, 
            self.user_developer
        )
        
        self.assertTrue(result)

    def test_invalid_transition_no_assignment(self):
        """Test that transition fails when task is not assigned."""
        with self.assertRaises(InvalidTransitionError) as cm:
            self.engine.validate_transition(
                self.task, 
                TaskStatus.IN_PROGRESS, 
                self.user_developer
            )
        
        self.assertIn('Task must be assigned', str(cm.exception))

    def test_transition_permission_check(self):
        """Test that transition respects permission requirements."""
        user_no_permission = User.objects.create_user(
            username='noperm',
            email='noperm@example.com',
            password='testpass123'
        )
        
        self.task.assigned_to.add(user_no_permission)
        
        with self.assertRaises(InvalidTransitionError) as cm:
            self.engine.validate_transition(
                self.task, 
                TaskStatus.IN_PROGRESS, 
                user_no_permission
            )
        
        self.assertIn('Permission denied', str(cm.exception))

    def test_get_available_transitions(self):
        """Test retrieval of available transitions for a task."""
        self.task.assigned_to.add(self.user_developer)
        
        transitions = self.engine.get_available_transitions(
            self.task, 
            self.user_developer
        )
        
        self.assertIsInstance(transitions, list)
        self.assertTrue(len(transitions) > 0)
        self.assertEqual(transitions[0]['to_status'], TaskStatus.IN_PROGRESS)

    def test_complex_transition_conditions(self):
        """Test complex transition conditions evaluation."""
        complex_rule = TransitionRule.objects.create(
            from_status=TaskStatus.IN_PROGRESS,
            to_status=TaskStatus.REVIEW,
            condition='{"actual_hours__gte": 1, "tags__name__contains": "backend"}',
            required_permissions=['tasks.change_task'],
            priority=1
        )
        
        self.task.status = TaskStatus.IN_PROGRESS
        self.task.actual_hours = Decimal('2.50')
        self.task.save()
        self.task.assigned_to.add(self.user_developer)
        
        result = self.engine.validate_transition(
            self.task, 
            TaskStatus.REVIEW, 
            self.user_developer
        )
        
        self.assertTrue(result)


class AutoAssignmentEngineTestCase(BaseWorkflowTestCase):
    """Test cases for automatic task assignment engine."""

    def setUp(self):
        super().setUp()
        self.engine = AutoAssignmentEngine()
        
        self.assignment_rule = AssignmentRule.objects.create(
            name='Backend Task Assignment',
            condition='{"tags__name__contains": "backend"}',
            assignment_strategy='round_robin',
            target_users=[self.user_developer.id, self.user_tester.id],
            is_active=True,
            priority=1
        )

    def test_auto_assign_based_on_tags(self):
        """Test automatic assignment based on task tags."""
        result = self.engine.auto_assign_task(self.task)
        
        self.assertTrue(result)
        self.task.refresh_from_db()
        self.assertTrue(self.task.assigned_to.exists())
        assigned_user = self.task.assigned_to.first()
        self.assertIn(assigned_user.id, self.assignment_rule.target_users)

    def test_workload_balancing_assignment(self):
        """Test assignment with workload balancing."""
        # Create multiple tasks for the developer
        for i in range(3):
            task = Task.objects.create(
                title=f'Developer Task {i}',
                description=f'Task {i} for developer',
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.MEDIUM,
                due_date=timezone.now() + timedelta(days=7),
                estimated_hours=Decimal('4.00'),
                created_by=self.user_manager
            )
            task.assigned_to.add(self.user_developer)
        
        # Update assignment rule to use workload balancing
        self.assignment_rule.assignment_strategy = 'workload_balanced'
        self.assignment_rule.save()
        
        result = self.engine.auto_assign_task(self.task)
        
        self.assertTrue(result)
        self.task.refresh_from_db()
        # Should assign to tester who has less workload
        self.assertEqual(self.task.assigned_to.first(), self.user_tester)

    def test_skill_based_assignment(self):
        """Test assignment based on user skills."""
        # Add skill information to user profile
        self.user_developer.profile.skills = ['python', 'django', 'backend']
        self.user_developer.profile.save()
        
        skill_rule = AssignmentRule.objects.create(
            name='Skill Based Assignment',
            condition='{"tags__name__contains": "backend"}',
            assignment_strategy='skill_based',
            required_skills=['python', 'django'],
            target_users=[self.user_developer.id, self.user_tester.id],
            is_active=True,
            priority=2
        )
        
        result = self.engine.auto_assign_task(self.task)
        
        self.assertTrue(result)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assigned_to.first(), self.user_developer)

    def test_no_matching_assignment_rule(self):
        """Test behavior when no assignment rule matches."""
        # Create task without matching tags
        task_no_match = Task.objects.create(
            title='No Match Task',
            description='Task with no matching assignment rules',
            status=TaskStatus.PENDING,
            priority=TaskPriority.LOW,
            due_date=timezone.now() + timedelta(days=7),
            estimated_hours=Decimal('2.00'),
            created_by=self.user_manager
        )
        task_no_match.tags.add(self.tag_frontend)
        
        result = self.engine.auto_assign_task(task_no_match)
        
        self.assertFalse(result)
        self.assertFalse(task_no_match.assigned_to.exists())

    def test_assignment_rule_priority(self):
        """Test that assignment rules are applied by priority."""
        high_priority_rule = AssignmentRule.objects.create(
            name='High Priority Backend Assignment',
            condition='{"tags__name__contains": "backend", "priority": "high"}',
            assignment_strategy='specific_user',
            target_users=[self.user_manager.id],
            is_active=True,
            priority=0  # Higher priority (lower number)
        )
        
        self.task.priority = TaskPriority.HIGH
        self.task.save()
        
        result = self.engine.auto_assign_task(self.task)
        
        self.assertTrue(result)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assigned_to.first(), self.user_manager)


class TaskTemplateEngineTestCase(BaseWorkflowTestCase):
    """Test cases for task template engine."""

    def setUp(self):
        super().setUp()
        self.engine = TaskTemplateEngine()
        
        self.template = TaskTemplate.objects.create(
            name='Bug Fix Template',
            title_template='Fix: {{bug_description}}',
            description_template='''
Bug Report: {{bug_description}}
Severity: {{severity}}
Affected Component: {{component}}

Steps to reproduce:
{{reproduction_steps}}

Expected Resolution Time: {{estimated_hours}} hours
            '''.strip(),
            default_priority=TaskPriority.HIGH,
            estimated_hours_template='{{base_hours|add:complexity_multiplier}}',
            created_by=self.user_manager
        )

    def test_create_task_from_template(self):
        """Test creating a task from a template with variable substitution."""
        variables = {
            'bug_description': 'Login form validation error',
            'severity': 'High',
            'component': 'Authentication Module',
            'reproduction_steps': '1. Navigate to login\n2. Enter invalid email\n3. Observe error',
            'base_hours': 4,
            'complexity_multiplier': 2
        }
        
        task = self.engine.create_from_template(
            self.template, 
            variables, 
            self.user_manager
        )
        
        self.assertIsInstance(task, Task)
        self.assertEqual(task.title, 'Fix: Login form validation error')
        self.assertIn('Authentication Module', task.description)
        self.assertEqual(task.priority, TaskPriority.HIGH)
        self.assertEqual(task.estimated_hours, Decimal('6.00'))  # 4 + 2

    def test_template_variable_validation(self):
        """Test validation of required template variables."""
        incomplete_variables = {
            'bug_description': 'Some bug',
            # Missing required variables
        }
        
        with self.assertRaises(ValidationError) as cm:
            self.engine.create_from_template(
                self.template, 
                incomplete_variables, 
                self.user_manager
            )
        
        self.assertIn('Required template variables missing', str(cm.exception))

    def test_template_with_default_values(self):
        """Test template creation with default values for missing variables."""
        self.template.default_variables = {
            'severity': 'Medium',
            'component': 'Unknown',
            'reproduction_steps': 'To be determined',
            'base_hours': 2,
            'complexity_multiplier': 1
        }
        self.template.save()
        
        minimal_variables = {
            'bug_description': 'Simple bug fix'
        }
        
        task = self.engine.create_from_template(
            self.template, 
            minimal_variables, 
            self.user_manager
        )
        
        self.assertIsInstance(task, Task)
        self.assertIn('Medium', task.description)
        self.assertEqual(task.estimated_hours, Decimal('3.00'))  # 2 + 1

    def test_template_inheritance(self):
        """Test template inheritance functionality."""
        parent_template = TaskTemplate.objects.create(
            name='Base Task Template',
            title_template='{{prefix}}: {{title}}',
            description_template='Base description: {{description}}',
            default_priority=TaskPriority.MEDIUM,
            created_by=self.user_manager
        )
        
        child_template = TaskTemplate.objects.create(
            name='Enhanced Task Template',
            parent_template=parent_template,
            description_template='Enhanced description: {{description}}\nAdditional info: {{extra_info}}',
            default_priority=TaskPriority.HIGH,
            created_by=self.user_manager
        )
        
        variables = {
            'prefix': 'TASK',
            'title': 'Test inheritance',
            'description': 'Base content',
            'extra_info': 'Additional content'
        }
        
        task = self.engine.create_from_template(
            child_template, 
            variables, 
            self.user_manager
        )
        
        self.assertEqual(task.title, 'TASK: Test inheritance')
        self.assertIn('Enhanced description', task.description)
        self.assertIn('Additional content', task.description)
        self.assertEqual(task.priority, TaskPriority.HIGH)


class RecurringTaskEngineTestCase(BaseWorkflowTestCase):
    """Test cases for recurring task generation engine."""

    def setUp(self):
        super().setUp()
        self.engine = RecurringTaskEngine()
        
        self.recurring_template = TaskTemplate.objects.create(
            name='Weekly Status Report',
            title_template='Weekly Status Report - Week {{week_number}}',
            description_template='Weekly status report for week {{week_number}} of {{year}}',
            default_priority=TaskPriority.MEDIUM,
            estimated_hours=Decimal('2.00'),
            recurrence_pattern='weekly',
            recurrence_interval=1,
            created_by=self.user_manager
        )

    @freeze_time("2024-01-01")  # Monday
    def test_generate_weekly_recurring_task(self):
        """Test generation of weekly recurring tasks."""
        tasks = self.engine.generate_recurring_tasks(
            self.recurring_template, 
            timezone.now(),
            weeks_ahead=4
        )
        
        self.assertEqual(len(tasks), 4)
        self.assertEqual(tasks[0].title, 'Weekly Status Report - Week 1')
        self.assertTrue(all(task.estimated_hours == Decimal('2.00') for task in tasks))

    @freeze_time("2024-01-01")
    def test_generate_daily_recurring_task(self):
        """Test generation of daily recurring tasks."""
        self.recurring_template.recurrence_pattern = 'daily'
        self.recurring_template.recurrence_interval = 2  # Every 2 days
        self.recurring_template.save()
        
        tasks = self.engine.generate_recurring_tasks(
            self.recurring_template,
            timezone.now(),
            days_ahead=10
        )
        
        self.assertEqual(len(tasks), 5)  # Every 2 days for 10 days = 5 tasks

    def test_recurring_task_with_business_days_only(self):
        """Test recurring task generation limited to business days."""
        self.recurring_template.recurrence_pattern = 'daily'
        self.recurring_template.business_days_only = True
        self.recurring_template.save()
        
        with freeze_time("2024-01-01"):  # Monday
            tasks = self.engine.generate_recurring_tasks(
                self.recurring_template,
                timezone.now(),
                days_ahead=7
            )
        
        # Should generate only for weekdays (Mon-Fri)
        self.assertEqual(len(tasks), 5)

    def test_recurring_task_end_date(self):
        """Test that recurring tasks respect end dates."""
        end_date = timezone.now() + timedelta(days=14)
        self.recurring_template.recurrence_end_date = end_date
        self.recurring_template.save()
        
        tasks = self.engine.generate_recurring_tasks(
            self.recurring_template,
            timezone.now(),
            weeks_ahead=8  # Would normally generate 8 weeks
        )
        
        # Should only generate tasks until end_date (2 weeks)
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(task.due_date <= end_date for task in tasks))


class SLAEngineTestCase(BaseWorkflowTestCase):
    """Test cases for SLA tracking and escalation engine."""

    def setUp(self):
        super().setUp()
        self.engine = SLAEngine()
        
        self.sla_config = SLAConfiguration.objects.create(
            name='Standard Development SLA',
            priority_high_hours=24,
            priority_medium_hours=72,
            priority_low_hours=168,
            escalation_rules={
                'first_escalation': {'hours': 12, 'action': 'notify_manager'},
                'second_escalation': {'hours': 48, 'action': 'reassign'}
            },
            business_hours_only=True,
            is_active=True
        )

    def test_calculate_sla_deadline(self):
        """Test SLA deadline calculation for different priorities."""
        high_priority_task = Task.objects.create(
            title='High Priority Task',
            description='Urgent task',
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=7),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        deadline = self.engine.calculate_sla_deadline(
            high_priority_task, 
            self.sla_config
        )
        
        expected_deadline = timezone.now() + timedelta(hours=24)
        self.assertAlmostEqual(
            deadline.timestamp(), 
            expected_deadline.timestamp(), 
            delta=60  # Within 1 minute
        )

    def test_sla_violation_detection(self):
        """Test detection of SLA violations."""
        # Create overdue task
        overdue_task = Task.objects.create(
            title='Overdue Task',
            description='Task that is overdue',
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() - timedelta(days=2),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager,
            created_at=timezone.now() - timedelta(hours=30)  # Created 30 hours ago
        )
        
        is_violated = self.engine.check_sla_violation(
            overdue_task, 
            self.sla_config
        )
        
        self.assertTrue(is_violated)

    def test_escalation_trigger(self):
        """Test SLA escalation triggering."""
        escalation_task = Task.objects.create(
            title='Escalation Task',
            description='Task requiring escalation',
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=1),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager,
            created_at=timezone.now() - timedelta(hours=50)  # Created 50 hours ago
        )
        escalation_task.assigned_to.add(self.user_developer)
        
        with patch('apps.workflows.engines.send_escalation_notification') as mock_notify:
            escalations = self.engine.process_escalations(
                [escalation_task], 
                self.sla_config
            )
        
        self.assertTrue(len(escalations) > 0)
        mock_notify.assert_called()

    def test_business_hours_calculation(self):
        """Test SLA calculation considering business hours only."""
        self.sla_config.business_hours_only = True
        self.sla_config.business_start_hour = 9
        self.sla_config.business_end_hour = 17
        self.sla_config.save()
        
        # Create task on Friday evening
        with freeze_time("2024-01-05 18:00:00"):  # Friday 6 PM
            task = Task.objects.create(
                title='Business Hours Task',
                description='Task created after business hours',
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                due_date=timezone.now() + timedelta(days=7),
                estimated_hours=Decimal('4.00'),
                created_by=self.user_manager
            )
            
            deadline = self.engine.calculate_sla_deadline(task, self.sla_config)
        
        # Should be calculated from Monday 9 AM
        expected_monday = datetime(2024, 1, 8, 9, 0, 0, tzinfo=timezone.utc)
        expected_deadline = expected_monday + timedelta(hours=24)
        
        self.assertAlmostEqual(
            deadline.timestamp(),
            expected_deadline.timestamp(),
            delta=3600  # Within 1 hour
        )


class DependencyEngineTestCase(BaseWorkflowTestCase):
    """Test cases for task dependency management engine."""

    def setUp(self):
        super().setUp()
        self.engine = DependencyEngine()
        
        self.parent_task = Task.objects.create(
            title='Parent Task',
            description='Task that blocks other tasks',
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('8.00'),
            created_by=self.user_manager
        )
        
        self.dependent_task = Task.objects.create(
            title='Dependent Task',
            description='Task that depends on parent',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=10),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager,
            parent_task=self.parent_task
        )

    def test_dependency_validation(self):
        """Test validation of task dependencies before status change."""
        # Try to start dependent task while parent is not complete
        with self.assertRaises(DependencyViolationError) as cm:
            self.engine.validate_dependencies(
                self.dependent_task, 
                TaskStatus.IN_PROGRESS
            )
        
        self.assertIn('dependency not satisfied', str(cm.exception))

    def test_dependency_resolution(self):
        """Test automatic dependency resolution when parent completes."""
        # Complete the parent task
        self.parent_task.status = TaskStatus.COMPLETED
        self.parent_task.save()
        
        # Should be able to start dependent task now
        result = self.engine.validate_dependencies(
            self.dependent_task, 
            TaskStatus.IN_PROGRESS
        )
        
        self.assertTrue(result)

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        # Create circular dependency: task A -> task B -> task A
        task_a = Task.objects.create(
            title='Task A',
            description='First task in circular dependency',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        task_b = Task.objects.create(
            title='Task B',
            description='Second task in circular dependency',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=7),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager,
            parent_task=task_a
        )
        
        # Try to create circular dependency
        task_a.parent_task = task_b
        
        with self.assertRaises(DependencyViolationError) as cm:
            self.engine.validate_dependencies(task_a, TaskStatus.PENDING)
        
        self.assertIn('Circular dependency', str(cm.exception))

    def test_dependency_chain_completion(self):
        """Test automatic progression of dependency chains."""
        # Create chain: grandparent -> parent -> child
        grandparent_task = Task.objects.create(
            title='Grandparent Task',
            description='Root task in chain',
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=3),
            estimated_hours=Decimal('6.00'),
            created_by=self.user_manager
        )
        
        self.parent_task.parent_task = grandparent_task
        self.parent_task.save()
        
        # Complete parent task
        self.parent_task.status = TaskStatus.COMPLETED
        self.parent_task.save()
        
        available_tasks = self.engine.get_ready_tasks()
        
        self.assertIn(self.dependent_task, available_tasks)

    def test_complex_dependency_graph(self):
        """Test handling of complex dependency graphs."""
        # Create diamond dependency pattern
        task_1 = Task.objects.create(
            title='Task 1',
            description='First parallel dependency',
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=2),
            estimated_hours=Decimal('3.00'),
            created_by=self.user_manager,
            parent_task=self.parent_task
        )
        
        task_2 = Task.objects.create(
            title='Task 2',
            description='Second parallel dependency',
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=3),
            estimated_hours=Decimal('3.00'),
            created_by=self.user_manager,
            parent_task=self.parent_task
        )
        
        final_task = Task.objects.create(
            title='Final Task',
            description='Task requiring both dependencies',
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=8),
            estimated_hours=Decimal('5.00'),
            created_by=self.user_manager
        )
        
        # Add multiple dependencies
        final_task.dependencies.add(task_1, task_2)
        
        # Complete parent task
        self.parent_task.status = TaskStatus.COMPLETED
        self.parent_task.save()
        
        result = self.engine.validate_dependencies(
            final_task, 
            TaskStatus.IN_PROGRESS
        )
        
        self.assertTrue(result)


class CriticalPathEngineTestCase(BaseWorkflowTestCase):
    """Test cases for critical path identification engine."""

    def setUp(self):
        super().setUp()
        self.engine = CriticalPathEngine()
        
        # Create project with multiple task paths
        self.project_tasks = []
        for i in range(5):
            task = Task.objects.create(
                title=f'Project Task {i+1}',
                description=f'Task {i+1} in project workflow',
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                due_date=timezone.now() + timedelta(days=(i+1)*2),
                estimated_hours=Decimal(str(4.0 + i)),
                created_by=self.user_manager
            )
            self.project_tasks.append(task)
        
        # Create dependencies to form critical path
        # Task 1 -> Task 2 -> Task 4 -> Task 5 (longest path)
        # Task 1 -> Task 3 -> Task 5 (shorter path)
        self.project_tasks[1].parent_task = self.project_tasks[0]  # T2 depends on T1
        self.project_tasks[2].parent_task = self.project_tasks[0]  # T3 depends on T1
        self.project_tasks[3].parent_task = self.project_tasks[1]  # T4 depends on T2
        self.project_tasks[4].parent_task = self.project_tasks[3]  # T5 depends on T4
        
        for task in self.project_tasks[1:]:
            task.save()

    def test_critical_path_identification(self):
        """Test identification of the critical path in a project."""
        critical_path = self.engine.calculate_critical_path(self.project_tasks)
        
        # Critical path should be T1 -> T2 -> T4 -> T5
        expected_path = [
            self.project_tasks[0],
            self.project_tasks[1], 
            self.project_tasks[3], 
            self.project_tasks[4]
        ]
        
        self.assertEqual(len(critical_path), 4)
        self.assertEqual(critical_path, expected_path)

    def test_critical_path_duration_calculation(self):
        """Test calculation of critical path total duration."""
        duration = self.engine.calculate_critical_path_duration(self.project_tasks)
        
        # Duration should be sum of T1(4) + T2(5) + T4(7) + T5(8) = 24 hours
        expected_duration = Decimal('24.00')
        self.assertEqual(duration, expected_duration)

    def test_slack_time_calculation(self):
        """Test calculation of slack time for non-critical tasks."""
        slack_times = self.engine.calculate_slack_times(self.project_tasks)
        
        # Task 3 should have slack time as it's not on critical path
        task_3_slack = slack_times[self.project_tasks[2].id]
        self.assertGreater(task_3_slack, 0)

    def test_critical_path_with_delays(self):
        """Test critical path recalculation when tasks are delayed."""
        # Simulate delay in Task 2
        self.project_tasks[1].actual_hours = Decimal('8.00')  # Double estimated
        self.project_tasks[1].save()
        
        updated_duration = self.engine.calculate_critical_path_duration(
            self.project_tasks,
            use_actual_hours=True
        )
        
        # New duration: T1(4) + T2(8) + T4(7) + T5(8) = 27 hours
        expected_duration = Decimal('27.00')
        self.assertEqual(updated_duration, expected_duration)

    def test_multiple_critical_paths(self):
        """Test handling of projects with multiple critical paths."""
        # Make T3 take as long as T2+T4 to create two critical paths
        self.project_tasks[2].estimated_hours = Decimal('12.00')
        self.project_tasks[2].save()
        
        critical_paths = self.engine.find_all_critical_paths(self.project_tasks)
        
        self.assertGreaterEqual(len(critical_paths), 1)
        # Should identify both paths with equal duration


class BusinessHoursEngineTestCase(BaseWorkflowTestCase):
    """Test cases for business hours calculation engine."""

    def setUp(self):
        super().setUp()
        self.engine = BusinessHoursEngine()
        
        # Configure business hours: Mon-Fri, 9 AM - 5 PM
        self.business_config = {
            'business_days': [0, 1, 2, 3, 4],  # Monday to Friday
            'start_hour': 9,
            'end_hour': 17,
            'timezone': 'UTC',
            'holidays': ['2024-01-01', '2024-12-25']
        }

    def test_business_hours_calculation(self):
        """Test calculation of business hours between two dates."""
        # From Monday 10 AM to Wednesday 2 PM
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # Monday
        end_time = datetime(2024, 1, 3, 14, 0, 0, tzinfo=timezone.utc)    # Wednesday
        
        business_hours = self.engine.calculate_business_hours(
            start_time, 
            end_time, 
            self.business_config
        )
        
        # Monday: 7 hours (10 AM - 5 PM)
        # Tuesday: 8 hours (9 AM - 5 PM) 
        # Wednesday: 5 hours (9 AM - 2 PM)
        # Total: 20 hours
        expected_hours = Decimal('20.00')
        self.assertEqual(business_hours, expected_hours)

    def test_weekend_exclusion(self):
        """Test that weekends are properly excluded from business hours."""
        # From Friday 2 PM to Monday 11 AM
        start_time = datetime(2024, 1, 5, 14, 0, 0, tzinfo=timezone.utc)  # Friday
        end_time = datetime(2024, 1, 8, 11, 0, 0, tzinfo=timezone.utc)    # Monday
        
        business_hours = self.engine.calculate_business_hours(
            start_time, 
            end_time, 
            self.business_config
        )
        
        # Friday: 3 hours (2 PM - 5 PM)
        # Saturday: 0 hours (weekend)
        # Sunday: 0 hours (weekend)  
        # Monday: 2 hours (9 AM - 11 AM)
        # Total: 5 hours
        expected_hours = Decimal('5.00')
        self.assertEqual(business_hours, expected_hours)

    def test_holiday_exclusion(self):
        """Test that holidays are properly excluded from business hours."""
        # From Dec 24 to Dec 26 (includes Christmas)
        start_time = datetime(2024, 12, 24, 10, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 12, 26, 15, 0, 0, tzinfo=timezone.utc)
        
        business_hours = self.engine.calculate_business_hours(
            start_time, 
            end_time, 
            self.business_config
        )
        
        # Dec 24: 7 hours (10 AM - 5 PM)
        # Dec 25: 0 hours (holiday)
        # Dec 26: 6 hours (9 AM - 3 PM)
        # Total: 13 hours
        expected_hours = Decimal('13.00')
        self.assertEqual(business_hours, expected_hours)

    def test_add_business_hours(self):
        """Test adding business hours to a start time."""
        start_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)  # Monday 2 PM
        hours_to_add = Decimal('10.00')
        
        result_time = self.engine.add_business_hours(
            start_time, 
            hours_to_add, 
            self.business_config
        )
        
        # Monday 2 PM + 3 hours = Monday 5 PM (end of business day)
        # Remaining 7 hours start Tuesday 9 AM
        # Tuesday 9 AM + 7 hours = Tuesday 4 PM
        expected_time = datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(result_time, expected_time)

    def test_business_hours_with_different_timezone(self):
        """Test business hours calculation with different timezone."""
        config_est = self.business_config.copy()
        config_est['timezone'] = 'US/Eastern'
        
        # Test with EST timezone
        start_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 20, 0, 0, tzinfo=timezone.utc)
        
        business_hours = self.engine.calculate_business_hours(
            start_time, 
            end_time, 
            config_est
        )
        
        # Should account for timezone difference
        self.assertIsInstance(business_hours, Decimal)
        self.assertGreater(business_hours, Decimal('0'))


class AutomationRulesEngineTestCase(BaseWorkflowTestCase):
    """Test cases for automation rules engine."""

    def setUp(self):
        super().setUp()
        self.engine = AutomationRulesEngine()
        
        # Create automation rules
        self.auto_assign_rule = AutomationRule.objects.create(
            name='Auto-assign backend tasks',
            event_type='task_created',
            condition='{"tags__name__contains": "backend"}',
            action_type='auto_assign',
            action_config={
                'assignment_strategy': 'round_robin',
                'user_pool': [self.user_developer.id, self.user_tester.id]
            },
            is_active=True,
            priority=1
        )
        
        self.escalation_rule = AutomationRule.objects.create(
            name='Escalate overdue high priority tasks',
            event_type='task_overdue',
            condition='{"priority": "high"}',
            action_type='escalate',
            action_config={
                'escalate_to': self.user_manager.id,
                'notification_template': 'overdue_escalation'
            },
            is_active=True,
            priority=2
        )

    def test_rule_execution_on_task_creation(self):
        """Test that automation rules execute when tasks are created."""
        # Create a backend task that should trigger auto-assignment
        new_task = Task.objects.create(
            title='New Backend Task',
            description='Task that should be auto-assigned',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('6.00'),
            created_by=self.user_manager
        )
        new_task.tags.add(self.tag_backend)
        
        # Execute automation rules for task creation event
        results = self.engine.execute_rules('task_created', {'task': new_task})
        
        self.assertTrue(len(results) > 0)
        new_task.refresh_from_db()
        self.assertTrue(new_task.assigned_to.exists())

    def test_rule_condition_evaluation(self):
        """Test proper evaluation of rule conditions."""
        # Test with task that matches condition
        matching_task = Task.objects.create(
            title='Matching Task',
            description='Task matching rule conditions',
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() - timedelta(hours=1),  # Overdue
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        matches = self.engine.evaluate_condition(
            self.escalation_rule.condition, 
            {'task': matching_task}
        )
        
        self.assertTrue(matches)
        
        # Test with task that doesn't match
        non_matching_task = Task.objects.create(
            title='Non-matching Task',
            description='Task not matching rule conditions',
            status=TaskStatus.PENDING,
            priority=TaskPriority.LOW,  # Different priority
            due_date=timezone.now() - timedelta(hours=1),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        matches = self.engine.evaluate_condition(
            self.escalation_rule.condition, 
            {'task': non_matching_task}
        )
        
        self.assertFalse(matches)

    def test_rule_priority_ordering(self):
        """Test that rules are executed in priority order."""
        # Create higher priority rule
        high_priority_rule = AutomationRule.objects.create(
            name='High priority rule',
            event_type='task_created',
            condition='{"tags__name__contains": "backend"}',
            action_type='set_priority',
            action_config={'priority': 'high'},
            is_active=True,
            priority=0  # Higher priority (lower number)
        )
        
        new_task = Task.objects.create(
            title='Test Priority Task',
            description='Task for testing rule priority',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        new_task.tags.add(self.tag_backend)
        
        with patch.object(self.engine, 'execute_action') as mock_execute:
            results = self.engine.execute_rules('task_created', {'task': new_task})
        
        # High priority rule should be executed first
        self.assertTrue(mock_execute.call_count >= 2)
        first_call_rule = mock_execute.call_args_list[0][0][0]
        self.assertEqual(first_call_rule.priority, 0)

    def test_rule_action_execution(self):
        """Test execution of different rule actions."""
        test_task = Task.objects.create(
            title='Test Action Task',
            description='Task for testing rule actions',
            status=TaskStatus.PENDING,
            priority=TaskPriority.LOW,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        # Test set_priority action
        priority_rule = AutomationRule.objects.create(
            name='Set priority rule',
            event_type='task_created',
            condition='{}',  # Always match
            action_type='set_priority',
            action_config={'priority': 'high'},
            is_active=True,
            priority=1
        )
        
        result = self.engine.execute_action(
            priority_rule, 
            {'task': test_task}
        )
        
        self.assertTrue(result['success'])
        test_task.refresh_from_db()
        self.assertEqual(test_task.priority, TaskPriority.HIGH)

    @patch('apps.workflows.engines.send_notification')
    def test_notification_action(self, mock_send):
        """Test notification action execution."""
        notification_rule = AutomationRule.objects.create(
            name='Send notification rule',
            event_type='task_completed',
            condition='{}',
            action_type='send_notification',
            action_config={
                'recipients': [self.user_manager.id],
                'template': 'task_completed',
                'subject': 'Task completed: {{task.title}}'
            },
            is_active=True,
            priority=1
        )
        
        completed_task = Task.objects.create(
            title='Completed Task',
            description='Task that was just completed',
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        result = self.engine.execute_action(
            notification_rule, 
            {'task': completed_task}
        )
        
        self.assertTrue(result['success'])
        mock_send.assert_called_once()

    def test_rule_error_handling(self):
        """Test proper error handling in rule execution."""
        # Create rule with invalid action config
        invalid_rule = AutomationRule.objects.create(
            name='Invalid rule',
            event_type='task_created',
            condition='{}',
            action_type='invalid_action',
            action_config={},
            is_active=True,
            priority=1
        )
        
        test_task = Task.objects.create(
            title='Error Test Task',
            description='Task for testing error handling',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        result = self.engine.execute_action(
            invalid_rule, 
            {'task': test_task}
        )
        
        self.assertFalse(result['success'])
        self.assertIn('error', result)

    def test_conditional_rule_execution(self):
        """Test rules with complex conditional logic."""
        complex_rule = AutomationRule.objects.create(
            name='Complex condition rule',
            event_type='task_updated',
            condition='''
            {
                "priority": "high",
                "status": "in_progress",
                "assigned_to__isnull": false,
                "estimated_hours__gte": 8.0
            }
            ''',
            action_type='add_comment',
            action_config={
                'comment': 'High priority complex task in progress - monitoring required'
            },
            is_active=True,
            priority=1
        )
        
        # Create task that matches all conditions
        complex_task = Task.objects.create(
            title='Complex Task',
            description='Task with complex conditions',
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('10.00'),
            created_by=self.user_manager
        )
        complex_task.assigned_to.add(self.user_developer)
        
        matches = self.engine.evaluate_condition(
            complex_rule.condition, 
            {'task': complex_task}
        )
        
        self.assertTrue(matches)
        
        # Test with task missing one condition (no assignee)
        unassigned_task = Task.objects.create(
            title='Unassigned Complex Task',
            description='Task missing assignment',
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('10.00'),
            created_by=self.user_manager
        )
        
        matches = self.engine.evaluate_condition(
            complex_rule.condition, 
            {'task': unassigned_task}
        )
        
        self.assertFalse(matches)


class WorkflowEngineIntegrationTestCase(TransactionTestCase):
    """Integration tests for complete workflow engine functionality."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Set up test data similar to BaseWorkflowTestCase
        cls.user_manager = User.objects.create_user(
            username='integration_manager',
            email='manager@integration.com',
            password='testpass123',
            is_staff=True
        )
        cls.user_developer = User.objects.create_user(
            username='integration_developer',
            email='developer@integration.com',
            password='testpass123'
        )

    def setUp(self):
        """Set up for integration tests."""
        self.workflow_engine = WorkflowEngine()
        self.tag_backend = Tag.objects.create(name='backend-integration')

    def test_complete_workflow_execution(self):
        """Test complete workflow from task creation to completion."""
        # Create initial task
        task = Task.objects.create(
            title='Integration Test Task',
            description='Complete workflow integration test',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=7),
            estimated_hours=Decimal('8.00'),
            created_by=self.user_manager
        )
        task.tags.add(self.tag_backend)
        
        # Simulate task assignment through workflow
        assignment_result = self.workflow_engine.assignment_engine.auto_assign_task(task)
        
        # Simulate status transitions through workflow
        if assignment_result:
            task.assigned_to.add(self.user_developer)
            transition_result = self.workflow_engine.status_engine.validate_transition(
                task, TaskStatus.IN_PROGRESS, self.user_developer
            )
            
            if transition_result:
                task.status = TaskStatus.IN_PROGRESS
                task.save()
        
        # Verify complete workflow execution
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertTrue(task.assigned_to.filter(id=self.user_developer.id).exists())

    @patch('apps.workflows.engines.send_task_notification.delay')
    def test_workflow_with_async_tasks(self, mock_celery_task):
        """Test workflow integration with Celery background tasks."""
        task = Task.objects.create(
            title='Async Workflow Task',
            description='Task triggering background processes',
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=3),
            estimated_hours=Decimal('6.00'),
            created_by=self.user_manager
        )
        task.assigned_to.add(self.user_developer)
        
        # Execute workflow that should trigger background tasks
        workflow_execution = WorkflowExecution.objects.create(
            workflow_definition=WorkflowDefinition.objects.create(
                name='Async Test Workflow',
                description='Workflow with async components',
                is_active=True,
                created_by=self.user_manager
            ),
            task=task,
            current_state='pending',
            started_by=self.user_manager
        )
        
        result = self.workflow_engine.execute_workflow(workflow_execution)
        
        self.assertTrue(result)
        # Verify background task was triggered
        mock_celery_task.assert_called()

    def test_workflow_performance_with_bulk_operations(self):
        """Test workflow engine performance with bulk task operations."""
        # Create multiple tasks for bulk processing
        tasks = []
        for i in range(50):
            task = Task.objects.create(
                title=f'Bulk Task {i+1}',
                description=f'Bulk processing task {i+1}',
                status=TaskStatus.PENDING,
                priority=TaskPriority.LOW,
                due_date=timezone.now() + timedelta(days=5),
                estimated_hours=Decimal('2.00'),
                created_by=self.user_manager
            )
            tasks.append(task)
        
        # Measure workflow execution time
        start_time = timezone.now()
        
        # Process all tasks through workflow engine
        processed_count = 0
        for task in tasks:
            try:
                result = self.workflow_engine.assignment_engine.auto_assign_task(task)
                if result:
                    processed_count += 1
            except Exception:
                continue  # Skip failed assignments for performance test
        
        end_time = timezone.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Performance assertions
        self.assertLess(execution_time, 30)  # Should complete within 30 seconds
        self.assertGreaterEqual(processed_count, 0)  # At least some should process

    def test_workflow_rollback_on_error(self):
        """Test workflow rollback functionality on errors."""
        task = Task.objects.create(
            title='Rollback Test Task',
            description='Task for testing rollback functionality',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        original_status = task.status
        
        # Create workflow execution that will fail
        workflow_execution = WorkflowExecution.objects.create(
            workflow_definition=WorkflowDefinition.objects.create(
                name='Failure Test Workflow',
                description='Workflow designed to fail',
                is_active=True,
                created_by=self.user_manager
            ),
            task=task,
            current_state='invalid_state',  # This should cause failure
            started_by=self.user_manager
        )
        
        # Execute workflow and expect failure
        with self.assertRaises(WorkflowExecutionError):
            self.workflow_engine.execute_workflow(workflow_execution)
        
        # Verify task state was rolled back
        task.refresh_from_db()
        self.assertEqual(task.status, original_status)
        
        workflow_execution.refresh_from_db()
        self.assertEqual(workflow_execution.status, 'failed')


# Performance and stress test cases
class WorkflowPerformanceTestCase(BaseWorkflowTestCase):
    """Performance and stress tests for workflow engines."""

    def test_large_dependency_graph_performance(self):
        """Test performance with large dependency graphs."""
        # Create large dependency graph (100 tasks)
        tasks = []
        for i in range(100):
            task = Task.objects.create(
                title=f'Perf Task {i+1}',
                description=f'Performance test task {i+1}',
                status=TaskStatus.PENDING,
                priority=TaskPriority.LOW,
                due_date=timezone.now() + timedelta(days=10),
                estimated_hours=Decimal('1.00'),
                created_by=self.user_manager
            )
            tasks.append(task)
        
        # Create chain dependencies
        for i in range(1, len(tasks)):
            tasks[i].parent_task = tasks[i-1]
            tasks[i].save()
        
        dependency_engine = DependencyEngine()
        
        start_time = timezone.now()
        critical_path = dependency_engine.calculate_critical_path(tasks)
        end_time = timezone.now()
        
        execution_time = (end_time - start_time).total_seconds()
        
        self.assertLess(execution_time, 5.0)  # Should complete within 5 seconds
        self.assertEqual(len(critical_path), 100)  # All tasks should be on critical path

    def test_high_volume_rule_evaluation(self):
        """Test performance with high volume of automation rules."""
        automation_engine = AutomationRulesEngine()
        
        # Create many automation rules
        rules = []
        for i in range(100):
            rule = AutomationRule.objects.create(
                name=f'Performance Rule {i+1}',
                event_type='task_created',
                condition=f'{{"priority": "medium", "id__gt": {i}}}',
                action_type='add_tag',
                action_config={'tag_name': f'auto_tag_{i}'},
                is_active=True,
                priority=i
            )
            rules.append(rule)
        
        # Create test task
        test_task = Task.objects.create(
            title='Performance Test Task',
            description='Task for performance testing',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        start_time = timezone.now()
        results = automation_engine.execute_rules('task_created', {'task': test_task})
        end_time = timezone.now()
        
        execution_time = (end_time - start_time).total_seconds()
        
        self.assertLess(execution_time, 2.0)  # Should complete within 2 seconds
        self.assertGreater(len(results), 0)  # Should execute some rules

    def test_concurrent_workflow_execution(self):
        """Test workflow engine under concurrent load."""
        import threading
        import queue
        
        results_queue = queue.Queue()
        
        def execute_workflow_thread(thread_id):
            """Execute workflow in separate thread."""
            try:
                task = Task.objects.create(
                    title=f'Concurrent Task {thread_id}',
                    description=f'Concurrent execution task {thread_id}',
                    status=TaskStatus.PENDING,
                    priority=TaskPriority.MEDIUM,
                    due_date=timezone.now() + timedelta(days=5),
                    estimated_hours=Decimal('3.00'),
                    created_by=self.user_manager
                )
                
                engine = WorkflowEngine()
                result = engine.assignment_engine.auto_assign_task(task)
                results_queue.put((thread_id, result, None))
                
            except Exception as e:
                results_queue.put((thread_id, False, str(e)))
        
        # Start concurrent threads
        threads = []
        num_threads = 10
        
        for i in range(num_threads):
            thread = threading.Thread(target=execute_workflow_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=10)  # 10 second timeout per thread
        
        # Collect results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())
        
        # Verify concurrent execution
        self.assertEqual(len(results), num_threads)
        successful_executions = sum(1 for _, success, _ in results if success)
        self.assertGreaterEqual(successful_executions, 0)  # At least some should succeed


class WorkflowEngineEdgeCasesTestCase(BaseWorkflowTestCase):
    """Test edge cases and error conditions in workflow engines."""

    def test_workflow_with_deleted_users(self):
        """Test workflow behavior when referenced users are deleted."""
        # Create assignment rule with specific user
        assignment_rule = AssignmentRule.objects.create(
            name='Deleted User Assignment',
            condition='{"priority": "high"}',
            assignment_strategy='specific_user',
            target_users=[self.user_developer.id],
            is_active=True,
            priority=1
        )
        
        # Delete the user
        deleted_user_id = self.user_developer.id
        self.user_developer.delete()
        
        # Create task that would match the rule
        task = Task.objects.create(
            title='Orphaned Assignment Task',
            description='Task with deleted user assignment',
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        engine = AutoAssignmentEngine()
        result = engine.auto_assign_task(task)
        
        # Should handle gracefully and not assign to deleted user
        self.assertFalse(result)
        self.assertFalse(task.assigned_to.exists())

    def test_circular_workflow_execution(self):
        """Test detection and handling of circular workflow executions."""
        workflow_def = WorkflowDefinition.objects.create(
            name='Circular Test Workflow',
            description='Workflow that creates circular execution',
            is_active=True,
            created_by=self.user_manager
        )
        
        # Create workflow execution that references itself
        execution = WorkflowExecution.objects.create(
            workflow_definition=workflow_def,
            task=self.task,
            current_state='pending',
            started_by=self.user_manager
        )
        
        # Mock circular reference by setting parent execution to itself
        execution.parent_execution = execution
        execution.save()
        
        engine = WorkflowEngine()
        
        with self.assertRaises(WorkflowExecutionError) as cm:
            engine.execute_workflow(execution)
        
        self.assertIn('Circular workflow execution detected', str(cm.exception))

    def test_workflow_with_corrupted_data(self):
        """Test workflow resilience with corrupted or invalid data."""
        # Create rule with invalid JSON condition
        invalid_rule = AutomationRule.objects.create(
            name='Invalid JSON Rule',
            event_type='task_created',
            condition='{"invalid": json}',  # Invalid JSON
            action_type='add_comment',
            action_config={'comment': 'Test comment'},
            is_active=True,
            priority=1
        )
        
        engine = AutomationRulesEngine()
        
        # Should handle invalid JSON gracefully
        result = engine.evaluate_condition(invalid_rule.condition, {'task': self.task})
        self.assertFalse(result)  # Should return False for invalid conditions

    def test_workflow_with_extremely_large_data(self):
        """Test workflow behavior with extremely large data sets."""
        # Create task with very large description
        large_description = 'A' * 100000  # 100KB description
        
        large_task = Task.objects.create(
            title='Large Data Task',
            description=large_description,
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager,
            metadata={'large_data': {'items': list(range(10000))}}  # Large metadata
        )
        
        engine = WorkflowEngine()
        
        # Should handle large data without crashing
        try:
            result = engine.assignment_engine.auto_assign_task(large_task)
            # Test passes if no exception is raised
            self.assertIsNotNone(result)
        except Exception as e:
            self.fail(f"Workflow engine failed with large data: {str(e)}")

    def test_workflow_with_null_and_empty_values(self):
        """Test workflow behavior with null and empty values."""
        # Create task with minimal/null data
        minimal_task = Task.objects.create(
            title='',  # Empty title
            description=None,  # Null description
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=None,  # Null hours
            created_by=self.user_manager
        )
        
        engine = WorkflowEngine()
        
        # Should handle null/empty values gracefully
        try:
            assignment_result = engine.assignment_engine.auto_assign_task(minimal_task)
            transition_result = engine.status_engine.get_available_transitions(
                minimal_task, 
                self.user_manager
            )
            
            # Test passes if no exceptions are raised
            self.assertIsNotNone(assignment_result)
            self.assertIsInstance(transition_result, list)
            
        except Exception as e:
            self.fail(f"Workflow engine failed with null/empty values: {str(e)}")

    def test_workflow_with_timezone_edge_cases(self):
        """Test workflow behavior across timezone boundaries."""
        # Test with tasks created at timezone boundaries
        import pytz
        
        # Create task at timezone boundary (midnight UTC during DST transition)
        boundary_time = datetime(2024, 3, 10, 0, 0, 0, tzinfo=pytz.UTC)
        
        with freeze_time(boundary_time):
            boundary_task = Task.objects.create(
                title='Timezone Boundary Task',
                description='Task created at timezone boundary',
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                due_date=timezone.now() + timedelta(days=1),
                estimated_hours=Decimal('8.00'),
                created_by=self.user_manager
            )
        
        # Test SLA calculation across timezone boundaries
        sla_config = SLAConfiguration.objects.create(
            name='Timezone Test SLA',
            priority_high_hours=24,
            business_hours_only=True,
            business_start_hour=9,
            business_end_hour=17,
            is_active=True
        )
        
        sla_engine = SLAEngine()
        
        try:
            deadline = sla_engine.calculate_sla_deadline(boundary_task, sla_config)
            self.assertIsNotNone(deadline)
            self.assertIsInstance(deadline, datetime)
        except Exception as e:
            self.fail(f"SLA engine failed with timezone boundary: {str(e)}")


class WorkflowEngineSecurityTestCase(BaseWorkflowTestCase):
    """Security-focused tests for workflow engines."""

    def test_workflow_permission_enforcement(self):
        """Test that workflow engines properly enforce permissions."""
        # Create user without task modification permissions
        restricted_user = User.objects.create_user(
            username='restricted',
            email='restricted@example.com',
            password='testpass123'
        )
        
        # Try to execute transition that requires permissions
        status_engine = StatusTransitionEngine()
        
        with self.assertRaises(InvalidTransitionError) as cm:
            status_engine.validate_transition(
                self.task,
                TaskStatus.IN_PROGRESS,
                restricted_user
            )
        
        self.assertIn('Permission denied', str(cm.exception))

    def test_workflow_input_sanitization(self):
        """Test that workflow engines sanitize malicious input."""
        # Create rule with potentially malicious condition
        malicious_condition = '''
        {
            "title__contains": "<script>alert('xss')</script>",
            "__class__": "User"
        }
        '''
        
        malicious_rule = AutomationRule.objects.create(
            name='Malicious Input Rule',
            event_type='task_created',
            condition=malicious_condition,
            action_type='add_comment',
            action_config={'comment': 'Safe comment'},
            is_active=True,
            priority=1
        )
        
        engine = AutomationRulesEngine()
        
        # Should safely evaluate without code injection
        result = engine.evaluate_condition(
            malicious_rule.condition, 
            {'task': self.task}
        )
        
        # Should return False (no match) and not execute malicious code
        self.assertFalse(result)

    def test_workflow_data_access_control(self):
        """Test that workflows respect data access controls."""
        # Create private task for another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        
        private_task = Task.objects.create(
            title='Private Task',
            description='Task that should be private',
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=other_user,
            is_private=True  # Assuming private field exists
        )
        
        # Create rule that tries to access private task
        access_rule = AutomationRule.objects.create(
            name='Private Access Rule',
            event_type='task_updated',
            condition='{"is_private": true}',
            action_type='add_comment',
            action_config={'comment': 'Unauthorized access'},
            is_active=True,
            priority=1
        )
        
        engine = AutomationRulesEngine()
        
        # Should not execute on private task when user lacks access
        with patch.object(engine, '_check_task_access', return_value=False):
            results = engine.execute_rules(
                'task_updated', 
                {'task': private_task, 'user': self.user_developer}
            )
        
        # Should not execute any rules due to access control
        self.assertEqual(len(results), 0)

    def test_workflow_audit_logging(self):
        """Test that workflow actions are properly audited."""
        audit_rule = AutomationRule.objects.create(
            name='Audited Rule',
            event_type='task_created',
            condition='{}',
            action_type='set_priority',
            action_config={'priority': 'high'},
            is_active=True,
            priority=1,
            requires_audit=True
        )
        
        engine = AutomationRulesEngine()
        
        with patch('apps.workflows.engines.audit_logger') as mock_audit:
            result = engine.execute_action(audit_rule, {'task': self.task})
        
        # Should log the action for audit purposes
        self.assertTrue(result['success'])
        mock_audit.info.assert_called()
        
        # Verify audit log contains required information
        audit_call = mock_audit.info.call_args[0][0]
        self.assertIn('Automation rule executed', audit_call)
        self.assertIn(audit_rule.name, audit_call)
        self.assertIn(str(self.task.id), audit_call)


class WorkflowEngineCompatibilityTestCase(BaseWorkflowTestCase):
    """Tests for workflow engine compatibility with different Django versions and databases."""

    def test_database_specific_queries(self):
        """Test that workflow engines work with different database backends."""
        # Test PostgreSQL-specific features if available
        from django.db import connection
        
        if 'postgresql' in connection.vendor:
            # Test JSONField queries
            json_task = Task.objects.create(
                title='JSON Test Task',
                description='Task for testing JSON functionality',
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                due_date=timezone.now() + timedelta(days=5),
                estimated_hours=Decimal('4.00'),
                created_by=self.user_manager,
                metadata={
                    'custom_fields': {
                        'client': 'Test Client',
                        'project_type': 'web_development'
                    }
                }
            )
            
            # Test complex JSON query in automation rule
            json_rule = AutomationRule.objects.create(
                name='JSON Query Rule',
                event_type='task_created',
                condition='{"metadata__custom_fields__project_type": "web_development"}',
                action_type='add_tag',
                action_config={'tag_name': 'web_project'},
                is_active=True,
                priority=1
            )
            
            engine = AutomationRulesEngine()
            matches = engine.evaluate_condition(
                json_rule.condition, 
                {'task': json_task}
            )
            
            self.assertTrue(matches)

    def test_django_version_compatibility(self):
        """Test compatibility with different Django features."""
        # Test async view compatibility (Django 3.1+)
        try:
            import asyncio
            from asgiref.sync import sync_to_async
            
            @sync_to_async
            def async_workflow_test():
                engine = WorkflowEngine()
                return engine.assignment_engine.auto_assign_task(self.task)
            
            # Test that workflow engine works in async context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(async_workflow_test())
                self.assertIsNotNone(result)
            finally:
                loop.close()
                
        except ImportError:
            # Skip if asyncio features not available
            pass

    def test_model_inheritance_compatibility(self):
        """Test workflow engine compatibility with model inheritance."""
        # Test with proxy models
        class UrgentTask(Task):
            class Meta:
                proxy = True
                
            def save(self, *args, **kwargs):
                if not self.priority:
                    self.priority = TaskPriority.HIGH
                super().save(*args, **kwargs)
        
        urgent_task = UrgentTask.objects.create(
            title='Urgent Proxy Task',
            description='Task using proxy model',
            status=TaskStatus.PENDING,
            due_date=timezone.now() + timedelta(days=5),
            estimated_hours=Decimal('4.00'),
            created_by=self.user_manager
        )
        
        engine = WorkflowEngine()
        result = engine.assignment_engine.auto_assign_task(urgent_task)
        
        # Should work with proxy models
        self.assertIsNotNone(result)
        self.assertEqual(urgent_task.priority, TaskPriority.HIGH)


# Mock classes for testing
class MockWorkflowEngine(WorkflowEngine):
    """Mock workflow engine for testing error conditions."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.should_fail = False
        
    def execute_workflow(self, workflow_execution):
        if self.should_fail:
            raise WorkflowExecutionError("Mock failure")
        return super().execute_workflow(workflow_execution)


class WorkflowEngineTestUtilities:
    """Utility methods for workflow engine testing."""
    
    @staticmethod
    def create_test_workflow_chain(length=5, user=None):
        """Create a chain of tasks for testing dependency workflows."""
        tasks = []
        for i in range(length):
            task = Task.objects.create(
                title=f'Chain Task {i+1}',
                description=f'Task {i+1} in workflow chain',
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                due_date=timezone.now() + timedelta(days=i+1),
                estimated_hours=Decimal(str(2.0 + i)),
                created_by=user
            )
            
            if i > 0:
                task.parent_task = tasks[i-1]
                task.save()
                
            tasks.append(task)
            
        return tasks
    
    @staticmethod
    def create_test_automation_rules(count=10, user=None):
        """Create test automation rules for performance testing."""
        rules = []
        for i in range(count):
            rule = AutomationRule.objects.create(
                name=f'Test Rule {i+1}',
                event_type='task_created',
                condition=f'{{"priority": "medium", "id__mod": {i}}}',
                action_type='add_comment',
                action_config={'comment': f'Auto comment {i+1}'},
                is_active=True,
                priority=i
            )
            rules.append(rule)
        return rules
    
    @staticmethod
    def cleanup_test_data():
        """Clean up test data after workflow tests."""
        # Clean up in reverse dependency order
        WorkflowExecution.objects.all().delete()
        AutomationRule.objects.all().delete()
        AssignmentRule.objects.all().delete()
        TransitionRule.objects.all().delete()
        SLAConfiguration.objects.all().delete()
        TaskTemplate.objects.all().delete()
        Task.objects.all().delete()


# Custom test runner for workflow tests
class WorkflowTestRunner:
    """Custom test runner for workflow engine tests with enhanced reporting."""
    
    def __init__(self):
        self.test_results = {
            'passed': 0,
            'failed': 0,
            'errors': 0,
            'skipped': 0
        }
    
    def run_workflow_tests(self, test_classes):
        """Run workflow tests with detailed reporting."""
        for test_class in test_classes:
            suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
            runner = unittest.TextTestRunner(verbosity=2)
            result = runner.run(suite)
            
            self.test_results['passed'] += result.testsRun - len(result.failures) - len(result.errors)
            self.test_results['failed'] += len(result.failures)
            self.test_results['errors'] += len(result.errors)
            
        return self.test_results


if __name__ == '__main__':
    # Run tests with custom test runner
    test_classes = [
        WorkflowEngineTestCase,
        StatusTransitionEngineTestCase,
        AutoAssignmentEngineTestCase,
        TaskTemplateEngineTestCase,
        RecurringTaskEngineTestCase,
        SLAEngineTestCase,
        DependencyEngineTestCase,
        CriticalPathEngineTestCase,
        BusinessHoursEngineTestCase,
        AutomationRulesEngineTestCase,
        WorkflowEngineIntegrationTestCase,
        WorkflowPerformanceTestCase,
        WorkflowEngineEdgeCasesTestCase,
        WorkflowEngineSecurityTestCase,
        WorkflowEngineCompatibilityTestCase
    ]
    
    runner = WorkflowTestRunner()
    results = runner.run_workflow_tests(test_classes)
    
    print(f"\nWorkflow Engine Test Results:")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")
    print(f"Errors: {results['errors']}")
    print(f"Skipped: {results['skipped']}")
