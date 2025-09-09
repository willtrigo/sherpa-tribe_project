"""
Common permissions for the task management system.

Provides reusable permission classes for API access control.
"""

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import View


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    Assumes the model has a 'created_by' field.
    """

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check if user has permission for specific object."""
        User = get_user_model()
        # Read permissions are allowed for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner
        if hasattr(obj, 'created_by'):
            return obj.created_by == request.user

        # Fallback to checking if user is the object itself (for user profiles)
        if hasattr(obj, 'user'):
            return obj.user == request.user

        # For User objects
        if isinstance(obj, User):
            return obj == request.user

        return False


class IsAssignedOrOwner(permissions.BasePermission):
    """
    Permission that allows access to owners and assigned users.
    Useful for task-based objects where multiple users might need access.
    """

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check if user is owner or assigned to the object."""
        user = request.user

        # Check if user is the owner
        if hasattr(obj, 'created_by') and obj.created_by == user:
            return True

        # Check if user is assigned to the object
        if hasattr(obj, 'assigned_to'):
            # Handle ManyToManyField
            if hasattr(obj.assigned_to, 'all'):
                return user in obj.assigned_to.all()
            # Handle ForeignKey
            elif obj.assigned_to == user:
                return True

        # Check if user is assigned through a different field name
        if hasattr(obj, 'assignees') and hasattr(obj.assignees, 'all'):
            return user in obj.assignees.all()

        return False


class IsTeamMemberOrOwner(permissions.BasePermission):
    """
    Permission that allows access to team members and owners.
    """

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check if user is team member or owner."""
        user = request.user

        # Check if user is the owner
        if hasattr(obj, 'created_by') and obj.created_by == user:
            return True

        # Check if user is a team member
        if hasattr(obj, 'team'):
            team = obj.team
            if hasattr(team, 'members') and hasattr(team.members, 'all'):
                return user in team.members.all()

        # Check if object has direct team members
        if hasattr(obj, 'members') and hasattr(obj.members, 'all'):
            return user in obj.members.all()

        return False


class IsAdminOrOwner(permissions.BasePermission):
    """
    Permission that allows access to admins and owners.
    """

    def has_permission(self, request: Request, view: View) -> bool:
        """Check if user has general permission."""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check if user is admin or owner."""
        User = get_user_model()
        user = request.user

        # Admin users have full access
        if user.is_superuser or user.is_staff:
            return True

        # Check if user is the owner
        if hasattr(obj, 'created_by') and obj.created_by == user:
            return True

        # For User objects
        if isinstance(obj, User):
            return obj == user

        return False


class IsReadOnlyUser(permissions.BasePermission):
    """
    Permission that only allows read-only access.
    """

    def has_permission(self, request: Request, view: View) -> bool:
        """Only allow safe methods."""
        return request.method in permissions.SAFE_METHODS


class IsActiveUser(permissions.BasePermission):
    """
    Permission that only allows access to active users.
    """

    def has_permission(self, request: Request, view: View) -> bool:
        """Check if user is active."""
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_active
        )


class HasObjectPermission(permissions.BasePermission):
    """
    Permission that checks Django's object-level permissions.
    """

    def __init__(self, perm_format: str = None):
        """
        Initialize with permission format.

        Args:
            perm_format: Format string for permission, e.g., '{app_label}.change_{model_name}'
        """
        self.perm_format = perm_format

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check Django object permissions."""
        if not self.perm_format:
            return True

        # Get permission string
        opts = obj._meta
        perm = self.perm_format.format(
            app_label=opts.app_label,
            model_name=opts.model_name
        )

        return request.user.has_perm(perm, obj)


class IsOwnerOrTeamMember(permissions.BasePermission):
    """
    Combined permission for owner or team member access.
    """

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check if user is owner or team member."""
        # Check owner permission
        owner_permission = IsOwnerOrReadOnly()
        if owner_permission.has_object_permission(request, view, obj):
            return True

        # Check team member permission
        team_permission = IsTeamMemberOrOwner()
        return team_permission.has_object_permission(request, view, obj)


class DynamicPermission(permissions.BasePermission):
    """
    Dynamic permission that can be configured at runtime.
    """

    def __init__(self, permission_classes: list = None):
        """
        Initialize with list of permission classes.

        Args:
            permission_classes: List of permission classes to check
        """
        self.permission_classes = permission_classes or []

    def has_permission(self, request: Request, view: View) -> bool:
        """Check all configured permissions."""
        for permission_class in self.permission_classes:
            permission = permission_class()
            if not permission.has_permission(request, view):
                return False
        return True

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Check all configured object permissions."""
        for permission_class in self.permission_classes:
            permission = permission_class()
            if hasattr(permission, 'has_object_permission'):
                if not permission.has_object_permission(request, view, obj):
                    return False
        return True


# Convenience permission combinations
class OwnerOrReadOnlyPermission(IsOwnerOrReadOnly):
    """Alias for IsOwnerOrReadOnly for better readability."""
    pass


class AdminOrOwnerPermission(IsAdminOrOwner):
    """Alias for IsAdminOrOwner for better readability."""
    pass


class TeamMemberPermission(IsTeamMemberOrOwner):
    """Alias for IsTeamMemberOrOwner for better readability."""
    pass
