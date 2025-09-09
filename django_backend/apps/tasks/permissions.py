"""
Task-specific permissions for the Task Management System.

This module contains custom permission classes that control access to task-related
operations based on user roles, ownership, and business rules.
"""

from typing import Any, Dict, Optional, Union

from django.contrib.auth import get_user_model
from django.db.models import Model, QuerySet
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.common.permissions import BaseEntityPermission
from apps.tasks.models import Task, Comment, Tag, TaskHistory


User = get_user_model()


class TaskBasePermission(BaseEntityPermission):
    """
    Base permission class for task-related operations.
    
    Provides common functionality for all task permissions including
    ownership checks, team membership validation, and role-based access.
    """
    
    def _is_task_owner(self, user: User, task: Task) -> bool:
        """Check if user is the creator of the task."""
        return task.created_by_id == user.id
    
    def _is_task_assignee(self, user: User, task: Task) -> bool:
        """Check if user is assigned to the task."""
        return task.assigned_to.filter(id=user.id).exists()
    
    def _is_task_participant(self, user: User, task: Task) -> bool:
        """Check if user is either owner or assignee of the task."""
        return self._is_task_owner(user, task) or self._is_task_assignee(user, task)
    
    def _can_view_task(self, user: User, task: Task) -> bool:
        """
        Determine if user can view the task.
        
        Business rules:
        - Task participants (owner/assignees) can always view
        - Team members can view team tasks
        - Managers can view subordinates' tasks
        - Archived tasks follow special rules
        """
        if task.is_archived and not self._has_role(user, 'manager', 'admin'):
            return False
            
        if self._is_task_participant(user, task):
            return True
            
        # Check team membership if task has team context
        if hasattr(task, 'team') and task.team:
            return self._is_team_member(user, task.team)
            
        # Managers can view tasks created by their team members
        if self._has_role(user, 'manager'):
            return self._is_subordinate_task(user, task)
            
        return self._has_role(user, 'admin')
    
    def _can_modify_task(self, user: User, task: Task) -> bool:
        """
        Determine if user can modify the task.
        
        Business rules:
        - Task owner can always modify (unless archived)
        - Assignees can modify status, comments, and time tracking
        - Managers can modify team tasks
        - Admins can modify any task
        """
        if task.is_archived and not self._has_role(user, 'admin'):
            return False
            
        if self._is_task_owner(user, task):
            return True
            
        if self._has_role(user, 'admin'):
            return True
            
        # Managers can modify team tasks
        if self._has_role(user, 'manager'):
            if hasattr(task, 'team') and task.team:
                return self._is_team_member(user, task.team)
            return self._is_subordinate_task(user, task)
            
        return False
    
    def _is_subordinate_task(self, manager: User, task: Task) -> bool:
        """Check if task belongs to manager's subordinate."""
        # This would integrate with your org structure
        # For now, simplified team-based check
        if not hasattr(manager, 'managed_teams'):
            return False
            
        return task.created_by.teams.filter(
            id__in=manager.managed_teams.values_list('id', flat=True)
        ).exists()


class TaskPermission(TaskBasePermission):
    """
    Main permission class for Task CRUD operations.
    
    Handles permissions for viewing, creating, updating, and deleting tasks
    based on user roles and business rules.
    """
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """
        Check if user has permission to access the task endpoint.
        
        All authenticated users can access task endpoints, but specific
        operations are controlled by has_object_permission.
        """
        if not request.user or not request.user.is_authenticated:
            return False
            
        # List/Create permissions
        if view.action in ['list', 'create']:
            return True
            
        # Detail permissions handled in has_object_permission
        return True
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Task
    ) -> bool:
        """
        Check if user has permission to perform action on specific task.
        
        Args:
            request: The HTTP request
            view: The view being accessed
            obj: The task object
            
        Returns:
            bool: True if user has permission, False otherwise
        """
        user = request.user
        
        # Read permissions
        if request.method in SAFE_METHODS:
            return self._can_view_task(user, obj)
        
        # Write permissions
        if request.method in ['PUT', 'PATCH']:
            return self._can_modify_task(user, obj)
        
        # Delete permissions - more restrictive
        if request.method == 'DELETE':
            return self._can_delete_task(user, obj)
        
        return False
    
    def _can_delete_task(self, user: User, task: Task) -> bool:
        """
        Determine if user can delete the task.
        
        Business rules:
        - Only task owner can delete (unless admin)
        - Cannot delete tasks with subtasks
        - Cannot delete tasks with logged time
        - Admins can delete any task
        """
        if self._has_role(user, 'admin'):
            return True
            
        if not self._is_task_owner(user, task):
            return False
            
        # Check business constraints
        if task.subtasks.exists():
            return False
            
        if task.actual_hours and task.actual_hours > 0:
            return False
            
        return True


class TaskAssignmentPermission(TaskBasePermission):
    """
    Permission class for task assignment operations.
    
    Controls who can assign/unassign users to/from tasks.
    """
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check general assignment permission."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Task
    ) -> bool:
        """
        Check assignment-specific permissions.
        
        Business rules:
        - Task owner can assign anyone from their team
        - Managers can assign team members
        - Users can assign themselves if task is open
        - Admins can assign anyone
        """
        user = request.user
        
        if self._has_role(user, 'admin'):
            return True
            
        if self._is_task_owner(user, obj):
            return True
            
        if self._has_role(user, 'manager'):
            # Check if it's a team task or subordinate task
            if hasattr(obj, 'team') and obj.team:
                return self._is_team_member(user, obj.team)
            return self._is_subordinate_task(user, obj)
        
        # Self-assignment for open tasks
        if view.action == 'assign' and self._is_task_open_for_assignment(obj):
            # User can assign themselves
            assignment_data = getattr(request, 'data', {})
            assigned_user_ids = assignment_data.get('user_ids', [])
            return len(assigned_user_ids) == 1 and assigned_user_ids[0] == user.id
        
        return False
    
    def _is_task_open_for_assignment(self, task: Task) -> bool:
        """Check if task allows self-assignment."""
        # Business rule: tasks in 'open' or 'in_progress' status allow self-assignment
        return task.status in ['open', 'in_progress'] and not task.is_archived


class TaskCommentPermission(TaskBasePermission):
    """
    Permission class for task comment operations.
    
    Controls who can view, create, update, and delete comments on tasks.
    """
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check general comment permission."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Union[Task, Comment]
    ) -> bool:
        """
        Check comment-specific permissions.
        
        For comments, obj might be either Task (for list/create) or Comment (for detail operations).
        """
        user = request.user
        
        # Determine the task based on object type
        if isinstance(obj, Task):
            task = obj
        elif isinstance(obj, Comment):
            task = obj.task
            comment = obj
        else:
            return False
        
        # Must be able to view the task to comment
        if not self._can_view_task(user, task):
            return False
        
        # Read permissions
        if request.method in SAFE_METHODS:
            return True
        
        # Create permissions
        if request.method == 'POST':
            return self._can_comment_on_task(user, task)
        
        # Update/Delete permissions for specific comment
        if isinstance(obj, Comment):
            if request.method in ['PUT', 'PATCH']:
                return self._can_edit_comment(user, comment)
            if request.method == 'DELETE':
                return self._can_delete_comment(user, comment)
        
        return False
    
    def _can_comment_on_task(self, user: User, task: Task) -> bool:
        """
        Determine if user can add comments to task.
        
        Business rules:
        - Task participants can always comment
        - Team members can comment on team tasks
        - Cannot comment on archived tasks (unless admin)
        """
        if task.is_archived and not self._has_role(user, 'admin'):
            return False
            
        if self._is_task_participant(user, task):
            return True
            
        if hasattr(task, 'team') and task.team:
            return self._is_team_member(user, task.team)
            
        return self._has_role(user, 'manager', 'admin')
    
    def _can_edit_comment(self, user: User, comment: Comment) -> bool:
        """
        Determine if user can edit the comment.
        
        Business rules:
        - Comment author can edit within time limit
        - Admins can edit any comment
        - Cannot edit comments on archived tasks
        """
        if comment.task.is_archived and not self._has_role(user, 'admin'):
            return False
            
        if self._has_role(user, 'admin'):
            return True
            
        if comment.created_by_id != user.id:
            return False
            
        # Time-based edit restriction (e.g., 30 minutes)
        from django.utils import timezone
        from datetime import timedelta
        
        edit_deadline = comment.created_at + timedelta(minutes=30)
        return timezone.now() <= edit_deadline
    
    def _can_delete_comment(self, user: User, comment: Comment) -> bool:
        """
        Determine if user can delete the comment.
        
        Business rules:
        - Comment author can delete
        - Task owner can delete comments on their tasks
        - Admins can delete any comment
        """
        if self._has_role(user, 'admin'):
            return True
            
        if comment.created_by_id == user.id:
            return True
            
        if self._is_task_owner(user, comment.task):
            return True
            
        return False


class TaskHistoryPermission(TaskBasePermission):
    """
    Permission class for task history/audit log access.
    
    Controls who can view the audit trail of task changes.
    """
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check general history access permission."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Union[Task, TaskHistory]
    ) -> bool:
        """
        Check history-specific permissions.
        
        History is read-only, so only check view permissions.
        """
        user = request.user
        
        # Determine the task
        if isinstance(obj, Task):
            task = obj
        elif isinstance(obj, TaskHistory):
            task = obj.task
        else:
            return False
        
        # Only allow read operations
        if request.method not in SAFE_METHODS:
            return False
        
        # Business rules:
        # - Task participants can view history
        # - Managers can view team task history
        # - Admins can view all history
        if self._has_role(user, 'admin'):
            return True
            
        if self._is_task_participant(user, task):
            return True
            
        if self._has_role(user, 'manager'):
            if hasattr(task, 'team') and task.team:
                return self._is_team_member(user, task.team)
            return self._is_subordinate_task(user, task)
        
        return False


class TaskTemplatePermission(BasePermission):
    """
    Permission class for task template operations.
    
    Controls access to task templates which are used for creating recurring tasks.
    """
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """
        Check template access permissions.
        
        Business rules:
        - Authenticated users can view templates
        - Managers and admins can create/modify templates
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Read permissions for all authenticated users
        if request.method in SAFE_METHODS:
            return True
        
        # Write permissions for managers and admins only
        return self._has_role(request.user, 'manager', 'admin')
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Any
    ) -> bool:
        """Check object-level template permissions."""
        user = request.user
        
        # Read permissions
        if request.method in SAFE_METHODS:
            return True
        
        # Write permissions
        if self._has_role(user, 'admin'):
            return True
            
        # Template creator can modify their templates
        if hasattr(obj, 'created_by') and obj.created_by_id == user.id:
            return True
            
        # Team managers can modify team templates
        if (self._has_role(user, 'manager') and 
            hasattr(obj, 'team') and obj.team):
            return self._is_team_member(user, obj.team)
        
        return False
    
    def _has_role(self, user: User, *roles: str) -> bool:
        """Check if user has any of the specified roles."""
        if not user or not user.is_authenticated:
            return False
        
        user_roles = getattr(user, 'roles', [])
        if hasattr(user, 'get_roles'):
            user_roles = user.get_roles()
        elif hasattr(user, 'role'):
            user_roles = [user.role]
        
        return any(role in user_roles for role in roles)
    
    def _is_team_member(self, user: User, team: Any) -> bool:
        """Check if user is member of the specified team."""
        if not hasattr(user, 'teams'):
            return False
        return user.teams.filter(id=team.id).exists()


# Convenience permission combinations
class TaskOwnerOrReadOnly(TaskPermission):
    """
    Permission that allows task owners to edit, others to read only.
    Useful for endpoints that need simple ownership-based permissions.
    """
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Task
    ) -> bool:
        """Allow read to all who can view, write only to owners."""
        user = request.user
        
        if request.method in SAFE_METHODS:
            return self._can_view_task(user, obj)
        
        return self._is_task_owner(user, obj) or self._has_role(user, 'admin')


class TaskParticipantOnly(TaskPermission):
    """
    Permission that restricts access to task participants only.
    Useful for sensitive task operations.
    """
    
    def has_object_permission(
        self, 
        request: Request, 
        view: APIView, 
        obj: Task
    ) -> bool:
        """Allow access only to task participants and admins."""
        user = request.user
        
        if self._has_role(user, 'admin'):
            return True
            
        return self._is_task_participant(user, obj)
