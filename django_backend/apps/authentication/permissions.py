"""
Enterprise Task Management System - Authentication Permissions Module

This module implements a comprehensive permission framework for the task management system,
providing role-based access control (RBAC), object-level permissions, and advanced security features.

Architecture:
- Base permission classes for common patterns
- Role-based permissions with hierarchical access levels
- Object-level permissions for fine-grained control
- Security mixins for rate limiting and audit logging
- Team-based access control
- Dynamic permission evaluation system

Author: Enterprise Development Team
Version: 1.0.0
"""

import logging
from typing import Any, Dict, List, Optional, Type, Union
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Model, Q
from django.http import HttpRequest
from django.utils import timezone
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView


User = get_user_model()
logger = logging.getLogger(__name__)


class SecurityAuditMixin:
    """
    Mixin for auditing permission checks and security events.
    Provides comprehensive logging and monitoring capabilities.
    """
    
    @staticmethod
    def log_permission_check(
        user: User,
        action: str,
        resource: str,
        granted: bool,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log permission check for security auditing."""
        audit_data = {
            'user_id': user.id if user and user.is_authenticated else None,
            'username': getattr(user, 'username', 'anonymous'),
            'action': action,
            'resource': resource,
            'granted': granted,
            'timestamp': timezone.now().isoformat(),
            'ip_address': getattr(context or {}, 'ip_address', 'unknown'),
            'user_agent': getattr(context or {}, 'user_agent', 'unknown'),
        }
        
        log_level = logging.INFO if granted else logging.WARNING
        logger.log(
            log_level,
            f"Permission {'GRANTED' if granted else 'DENIED'}: {action} on {resource}",
            extra={'audit_data': audit_data}
        )


class RateLimitMixin:
    """
    Mixin for implementing rate limiting on permission checks.
    Prevents abuse and ensures system stability.
    """
    
    DEFAULT_RATE_LIMIT_WINDOW = 3600  # 1 hour
    DEFAULT_MAX_ATTEMPTS = 100
    
    def check_rate_limit(
        self,
        user: User,
        action: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW
    ) -> bool:
        """
        Check if user has exceeded rate limit for specific action.
        
        Args:
            user: User performing the action
            action: Action being rate limited
            max_attempts: Maximum attempts allowed in window
            window_seconds: Time window in seconds
            
        Returns:
            True if within rate limit, False if exceeded
        """
        if not user or not user.is_authenticated:
            return False
            
        cache_key = f"rate_limit:{user.id}:{action}"
        current_count = cache.get(cache_key, 0)
        
        if current_count >= max_attempts:
            logger.warning(
                f"Rate limit exceeded for user {user.id} on action {action}",
                extra={'user_id': user.id, 'action': action, 'count': current_count}
            )
            return False
            
        # Increment counter with expiration
        cache.set(cache_key, current_count + 1, window_seconds)
        return True


class BaseEnterprisePermission(permissions.BasePermission, SecurityAuditMixin, RateLimitMixin):
    """
    Base permission class for the enterprise task management system.
    Provides common functionality and security patterns.
    """
    
    permission_name = 'base_permission'
    rate_limit_action = 'api_access'
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """
        Base permission check with rate limiting and audit logging.
        
        Args:
            request: DRF request object
            view: API view being accessed
            
        Returns:
            Boolean indicating if permission is granted
        """
        user = getattr(request, 'user', None)
        
        # Rate limiting check
        if not self.check_rate_limit(user, self.rate_limit_action):
            self.log_permission_check(
                user, self.rate_limit_action, self.permission_name, False,
                {'reason': 'rate_limit_exceeded'}
            )
            return False
            
        # Basic authentication check
        if not user or not user.is_authenticated:
            self.log_permission_check(
                user, 'authentication', self.permission_name, False,
                {'reason': 'not_authenticated'}
            )
            return False
            
        # Account status checks
        if not user.is_active:
            self.log_permission_check(
                user, 'account_status', self.permission_name, False,
                {'reason': 'account_inactive'}
            )
            return False
            
        return True
    
    def get_request_context(self, request: Request) -> Dict[str, Any]:
        """Extract context information from request for logging."""
        return {
            'ip_address': self.get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'method': request.method,
            'path': request.path,
        }
    
    @staticmethod
    def get_client_ip(request: Request) -> str:
        """Extract client IP address from request headers."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')


class IsAuthenticatedAndActive(BaseEnterprisePermission):
    """
    Permission that requires user to be authenticated and active.
    Extends base permission with additional security checks.
    """
    
    permission_name = 'authenticated_active'
    rate_limit_action = 'authentication_check'
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check if user is authenticated and active."""
        if not super().has_permission(request, view):
            return False
            
        user = request.user
        context = self.get_request_context(request)
        
        # Email verification check (if required)
        if hasattr(user, 'email_verified') and not user.email_verified:
            self.log_permission_check(
                user, 'email_verification', self.permission_name, False,
                {**context, 'reason': 'email_not_verified'}
            )
            return False
            
        # Multi-factor authentication check (if required)
        if hasattr(user, 'requires_mfa') and user.requires_mfa:
            if not self._check_mfa_status(user, request):
                self.log_permission_check(
                    user, 'mfa_verification', self.permission_name, False,
                    {**context, 'reason': 'mfa_not_verified'}
                )
                return False
        
        self.log_permission_check(
            user, 'authentication', self.permission_name, True, context
        )
        return True
    
    def _check_mfa_status(self, user: User, request: Request) -> bool:
        """Check multi-factor authentication status."""
        # Implementation would check MFA session or token
        # This is a placeholder for MFA integration
        return request.session.get('mfa_verified', False)


class RoleBasedPermission(BaseEnterprisePermission):
    """
    Permission class implementing role-based access control (RBAC).
    Supports hierarchical roles and dynamic role evaluation.
    """
    
    # Role hierarchy (higher number = more permissions)
    ROLE_HIERARCHY = {
        'guest': 0,
        'user': 10,
        'team_member': 20,
        'team_lead': 30,
        'project_manager': 40,
        'department_head': 50,
        'admin': 60,
        'super_admin': 70,
        'system_admin': 100,
    }
    
    required_role = 'user'
    permission_name = 'role_based'
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check if user has required role."""
        if not super().has_permission(request, view):
            return False
            
        user = request.user
        context = self.get_request_context(request)
        
        user_role_level = self._get_user_role_level(user)
        required_level = self.ROLE_HIERARCHY.get(self.required_role, 0)
        
        has_permission = user_role_level >= required_level
        
        self.log_permission_check(
            user, 'role_check', self.permission_name, has_permission,
            {
                **context,
                'user_role_level': user_role_level,
                'required_level': required_level,
                'required_role': self.required_role,
            }
        )
        
        return has_permission
    
    def _get_user_role_level(self, user: User) -> int:
        """Get user's effective role level."""
        if user.is_superuser:
            return self.ROLE_HIERARCHY['system_admin']
            
        # Get user's primary role
        user_role = getattr(user, 'role', 'user')
        base_level = self.ROLE_HIERARCHY.get(user_role, 0)
        
        # Check for temporary role elevations
        elevated_role = self._check_temporary_elevation(user)
        if elevated_role:
            elevated_level = self.ROLE_HIERARCHY.get(elevated_role, 0)
            return max(base_level, elevated_level)
            
        return base_level
    
    def _check_temporary_elevation(self, user: User) -> Optional[str]:
        """Check for temporary role elevations (e.g., acting manager)."""
        cache_key = f"temp_role:{user.id}"
        temp_role_data = cache.get(cache_key)
        
        if temp_role_data:
            expiry = temp_role_data.get('expires_at')
            if expiry and timezone.now() < expiry:
                return temp_role_data.get('role')
                
        return None


class ObjectLevelPermission(RoleBasedPermission):
    """
    Permission class for object-level access control.
    Checks permissions on specific model instances.
    """
    
    permission_name = 'object_level'
    
    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        """Check object-level permissions."""
        user = request.user
        context = self.get_request_context(request)
        
        # Owner check
        if self._is_owner(user, obj):
            self.log_permission_check(
                user, 'object_owner', f"{self.permission_name}:{obj._meta.label}", True,
                {**context, 'object_id': obj.pk, 'reason': 'owner'}
            )
            return True
            
        # Team member check
        if self._is_team_member(user, obj):
            self.log_permission_check(
                user, 'object_team_member', f"{self.permission_name}:{obj._meta.label}", True,
                {**context, 'object_id': obj.pk, 'reason': 'team_member'}
            )
            return True
            
        # Role-based access check
        if self._check_role_access(user, obj, request.method):
            self.log_permission_check(
                user, 'object_role_access', f"{self.permission_name}:{obj._meta.label}", True,
                {**context, 'object_id': obj.pk, 'reason': 'role_based'}
            )
            return True
            
        self.log_permission_check(
            user, 'object_denied', f"{self.permission_name}:{obj._meta.label}", False,
            {**context, 'object_id': obj.pk, 'reason': 'insufficient_permissions'}
        )
        return False
    
    def _is_owner(self, user: User, obj: Model) -> bool:
        """Check if user is the owner of the object."""
        owner_fields = ['owner', 'created_by', 'user']
        for field in owner_fields:
            if hasattr(obj, field):
                owner = getattr(obj, field)
                if owner == user:
                    return True
        return False
    
    def _is_team_member(self, user: User, obj: Model) -> bool:
        """Check if user is a team member with access to the object."""
        # Check if object has team relation
        if hasattr(obj, 'team'):
            team = getattr(obj, 'team')
            if team and hasattr(team, 'members'):
                return team.members.filter(id=user.id).exists()
                
        # Check if object has assigned_to relation (many-to-many)
        if hasattr(obj, 'assigned_to'):
            return obj.assigned_to.filter(id=user.id).exists()
            
        return False
    
    def _check_role_access(self, user: User, obj: Model, method: str) -> bool:
        """Check role-based access to object."""
        user_role_level = self._get_user_role_level(user)
        
        # Define method-specific role requirements
        method_role_requirements = {
            'GET': 'user',
            'POST': 'team_member',
            'PUT': 'team_lead',
            'PATCH': 'team_lead',
            'DELETE': 'project_manager',
        }
        
        required_role = method_role_requirements.get(method, 'admin')
        required_level = self.ROLE_HIERARCHY.get(required_role, 100)
        
        return user_role_level >= required_level


class TaskManagementPermission(ObjectLevelPermission):
    """
    Specialized permission class for task management operations.
    Implements business-specific rules for task access.
    """
    
    required_role = 'user'
    permission_name = 'task_management'
    
    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        """Check task-specific permissions."""
        user = request.user
        
        # Check if task is archived (read-only for most users)
        if getattr(obj, 'is_archived', False):
            user_role_level = self._get_user_role_level(user)
            if user_role_level < self.ROLE_HIERARCHY.get('project_manager', 40):
                if request.method != 'GET':
                    return False
                    
        # Check task confidentiality
        if hasattr(obj, 'is_confidential') and obj.is_confidential:
            if not self._has_confidential_access(user, obj):
                return False
                
        # Check parent task permissions for subtasks
        if hasattr(obj, 'parent_task') and obj.parent_task:
            parent_permission = self.has_object_permission(request, view, obj.parent_task)
            if not parent_permission:
                return False
                
        return super().has_object_permission(request, view, obj)
    
    def _has_confidential_access(self, user: User, obj: Model) -> bool:
        """Check if user has access to confidential tasks."""
        # Only owner, assigned users, and managers can access confidential tasks
        if self._is_owner(user, obj) or self._is_team_member(user, obj):
            return True
            
        user_role_level = self._get_user_role_level(user)
        return user_role_level >= self.ROLE_HIERARCHY.get('project_manager', 40)


class TeamBasedPermission(RoleBasedPermission):
    """
    Permission class for team-based access control.
    Manages permissions based on team membership and hierarchy.
    """
    
    required_role = 'team_member'
    permission_name = 'team_based'
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check team-based permissions."""
        if not super().has_permission(request, view):
            return False
            
        user = request.user
        
        # Check if user belongs to any active team
        if not self._has_team_membership(user):
            return False
            
        return True
    
    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        """Check object-level team permissions."""
        user = request.user
        
        # Check if user and object belong to the same team
        if hasattr(obj, 'team'):
            obj_team = getattr(obj, 'team')
            if obj_team and not self._is_team_member_of(user, obj_team):
                return False
                
        return super().has_object_permission(request, view, obj)
    
    def _has_team_membership(self, user: User) -> bool:
        """Check if user belongs to any active team."""
        if hasattr(user, 'teams'):
            return user.teams.filter(is_active=True).exists()
        return False
    
    def _is_team_member_of(self, user: User, team: Model) -> bool:
        """Check if user is member of specific team."""
        if hasattr(team, 'members'):
            return team.members.filter(id=user.id).exists()
        return False


class AdminOnlyPermission(RoleBasedPermission):
    """
    Permission class that only allows admin users.
    Used for sensitive administrative operations.
    """
    
    required_role = 'admin'
    permission_name = 'admin_only'
    rate_limit_action = 'admin_access'
    
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check admin-level permissions with additional security."""
        if not super().has_permission(request, view):
            return False
            
        user = request.user
        context = self.get_request_context(request)
        
        # Additional security checks for admin operations
        if not self._verify_admin_session(user, request):
            self.log_permission_check(
                user, 'admin_session_invalid', self.permission_name, False,
                {**context, 'reason': 'invalid_admin_session'}
            )
            return False
            
        # Check for suspicious activity
        if self._detect_suspicious_admin_activity(user, request):
            self.log_permission_check(
                user, 'suspicious_admin_activity', self.permission_name, False,
                {**context, 'reason': 'suspicious_activity_detected'}
            )
            return False
            
        return True
    
    def _verify_admin_session(self, user: User, request: Request) -> bool:
        """Verify admin session validity with additional checks."""
        # Check session age
        session_start = request.session.get('admin_session_start')
        if session_start:
            session_age = timezone.now() - datetime.fromisoformat(session_start)
            if session_age > timedelta(hours=8):  # 8-hour admin session limit
                return False
                
        # Check IP consistency
        session_ip = request.session.get('admin_session_ip')
        current_ip = self.get_client_ip(request)
        if session_ip and session_ip != current_ip:
            return False
            
        return True
    
    def _detect_suspicious_admin_activity(self, user: User, request: Request) -> bool:
        """Detect potentially suspicious admin activity."""
        # Check for rapid sequential requests
        cache_key = f"admin_activity:{user.id}"
        recent_requests = cache.get(cache_key, [])
        
        # Remove old requests (older than 1 minute)
        cutoff_time = timezone.now() - timedelta(minutes=1)
        recent_requests = [
            req_time for req_time in recent_requests 
            if datetime.fromisoformat(req_time) > cutoff_time
        ]
        
        # Add current request
        recent_requests.append(timezone.now().isoformat())
        cache.set(cache_key, recent_requests, 300)  # 5-minute cache
        
        # Flag if more than 30 requests in 1 minute
        return len(recent_requests) > 30


# Permission decorators for function-based views
def require_permission(permission_class: Type[BaseEnterprisePermission]):
    """
    Decorator to require specific permission for function-based views.
    
    Usage:
        @require_permission(AdminOnlyPermission)
        def admin_view(request):
            pass
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            permission = permission_class()
            
            # Create mock DRF request for permission check
            class MockRequest:
                def __init__(self, django_request):
                    self.user = getattr(django_request, 'user', None)
                    self.method = django_request.method
                    self.META = django_request.META
                    self.path = django_request.path
                    self.session = getattr(django_request, 'session', {})
            
            mock_request = MockRequest(request)
            
            if not permission.has_permission(mock_request, None):
                raise PermissionDenied("Insufficient permissions")
                
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# Utility functions for permission management
class PermissionManager:
    """
    Utility class for managing permissions programmatically.
    Provides methods for dynamic permission evaluation and management.
    """
    
    @staticmethod
    def grant_temporary_role(user: User, role: str, duration_hours: int = 24) -> bool:
        """Grant temporary role elevation to user."""
        if role not in RoleBasedPermission.ROLE_HIERARCHY:
            return False
            
        cache_key = f"temp_role:{user.id}"
        expiry = timezone.now() + timedelta(hours=duration_hours)
        
        cache.set(cache_key, {
            'role': role,
            'expires_at': expiry,
            'granted_by': 'system',  # This should be set to granting user
            'granted_at': timezone.now(),
        }, duration_hours * 3600)
        
        logger.info(
            f"Temporary role {role} granted to user {user.id} for {duration_hours} hours"
        )
        return True
    
    @staticmethod
    def revoke_temporary_role(user: User) -> bool:
        """Revoke temporary role elevation from user."""
        cache_key = f"temp_role:{user.id}"
        cache.delete(cache_key)
        
        logger.info(f"Temporary role revoked for user {user.id}")
        return True
    
    @staticmethod
    def check_user_permissions(user: User, resource: str, action: str) -> Dict[str, Any]:
        """
        Comprehensive permission check for user on resource/action combination.
        Returns detailed information about permission status.
        """
        result = {
            'granted': False,
            'user_role_level': 0,
            'reasons': [],
            'temporary_elevation': None,
            'rate_limited': False,
        }
        
        if not user or not user.is_authenticated:
            result['reasons'].append('not_authenticated')
            return result
            
        # Get role level
        permission = RoleBasedPermission()
        result['user_role_level'] = permission._get_user_role_level(user)
        
        # Check temporary elevation
        temp_role = permission._check_temporary_elevation(user)
        if temp_role:
            result['temporary_elevation'] = temp_role
            
        # Check rate limiting
        if not permission.check_rate_limit(user, action):
            result['rate_limited'] = True
            result['reasons'].append('rate_limit_exceeded')
            return result
            
        # Basic permission logic would go here
        # This is a simplified implementation
        if user.is_active and result['user_role_level'] > 0:
            result['granted'] = True
        else:
            result['reasons'].append('insufficient_permissions')
            
        return result


# Export all permission classes
__all__ = [
    'BaseEnterprisePermission',
    'IsAuthenticatedAndActive',
    'RoleBasedPermission',
    'ObjectLevelPermission',
    'TaskManagementPermission',
    'TeamBasedPermission',
    'AdminOnlyPermission',
    'SecurityAuditMixin',
    'RateLimitMixin',
    'PermissionManager',
    'require_permission',
]
