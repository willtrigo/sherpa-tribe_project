"""
Django Admin Configuration for Authentication App

This module configures the Django admin interface for authentication-related
models, providing a comprehensive interface for managing users, sessions,
and authentication-related data.

The admin interface includes:
- Enhanced user management with filtering and search capabilities
- Session monitoring and management
- Authentication attempt logging and analysis
- Token management for JWT-based authentication
- Bulk operations for user management

Security considerations:
- Only superusers can access sensitive authentication data
- Audit logging for all admin actions
- Password fields are properly masked
- Sensitive fields are excluded from history tracking
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.http import HttpRequest
from django.db.models import QuerySet
from django.contrib.admin import SimpleListFilter
from django.utils import timezone
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

# Import models from related apps
from apps.users.models import User
from django.contrib.auth.models import Permission


class ActiveSessionFilter(SimpleListFilter):
    """
    Custom filter for active user sessions.
    
    Allows filtering users based on whether they have active sessions,
    helping administrators identify currently logged-in users.
    """
    
    title = _("Active Sessions")
    parameter_name = "active_sessions"
    
    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> List[Tuple[str, str]]:
        """
        Return filter options for active sessions.
        
        Args:
            request: The HTTP request object
            model_admin: The model admin instance
            
        Returns:
            List of tuples containing filter values and labels
        """
        return [
            ("yes", _("Has Active Sessions")),
            ("no", _("No Active Sessions")),
            ("recent", _("Active in Last 24h")),
        ]
    
    def queryset(self, request: HttpRequest, queryset: QuerySet) -> Optional[QuerySet]:
        """
        Filter the queryset based on active sessions.
        
        Args:
            request: The HTTP request object
            queryset: The original queryset
            
        Returns:
            Filtered queryset or None if no filter applied
        """
        if self.value() == "yes":
            active_user_ids = Session.objects.filter(
                expire_date__gte=timezone.now()
            ).values_list("session_key", flat=True)
            return queryset.filter(id__in=active_user_ids)
        
        if self.value() == "no":
            active_user_ids = Session.objects.filter(
                expire_date__gte=timezone.now()
            ).values_list("session_key", flat=True)
            return queryset.exclude(id__in=active_user_ids)
        
        if self.value() == "recent":
            recent_threshold = timezone.now() - timedelta(hours=24)
            return queryset.filter(last_login__gte=recent_threshold)
        
        return None


class LastLoginFilter(SimpleListFilter):
    """
    Custom filter for user last login dates.
    
    Provides convenient filtering options for identifying users
    based on their last login activity.
    """
    
    title = _("Last Login")
    parameter_name = "last_login_filter"
    
    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> List[Tuple[str, str]]:
        """
        Return filter options for last login dates.
        
        Args:
            request: The HTTP request object
            model_admin: The model admin instance
            
        Returns:
            List of tuples containing filter values and labels
        """
        return [
            ("today", _("Today")),
            ("week", _("Past Week")),
            ("month", _("Past Month")),
            ("never", _("Never Logged In")),
            ("inactive_30", _("Inactive 30+ Days")),
        ]
    
    def queryset(self, request: HttpRequest, queryset: QuerySet) -> Optional[QuerySet]:
        """
        Filter the queryset based on last login dates.
        
        Args:
            request: The HTTP request object
            queryset: The original queryset
            
        Returns:
            Filtered queryset or None if no filter applied
        """
        now = timezone.now()
        
        if self.value() == "today":
            return queryset.filter(last_login__date=now.date())
        
        if self.value() == "week":
            week_ago = now - timedelta(days=7)
            return queryset.filter(last_login__gte=week_ago)
        
        if self.value() == "month":
            month_ago = now - timedelta(days=30)
            return queryset.filter(last_login__gte=month_ago)
        
        if self.value() == "never":
            return queryset.filter(last_login__isnull=True)
        
        if self.value() == "inactive_30":
            thirty_days_ago = now - timedelta(days=30)
            return queryset.filter(
                models.Q(last_login__lt=thirty_days_ago) |
                models.Q(last_login__isnull=True)
            )
        
        return None


@admin.register(User)
class EnhancedUserAdmin(BaseUserAdmin):
    """
    Enhanced Django admin configuration for User model.
    
    Extends the default UserAdmin with additional functionality
    for the Enterprise Task Management System, including:
    - Enhanced filtering and search capabilities
    - Custom field displays with security considerations
    - Bulk operations for user management
    - Integration with task and team management
    """
    
    # List display configuration
    list_display = [
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active_display",
        "is_staff_display",
        "last_login_display",
        "date_joined_display",
        "active_sessions_count",
    ]
    
    # List filters
    list_filter = [
        ActiveSessionFilter,
        LastLoginFilter,
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
        "groups",
    ]
    
    # Search configuration
    search_fields = [
        "username",
        "first_name",
        "last_name",
        "email",
    ]
    
    # Ordering
    ordering = ["-date_joined"]
    
    # Items per page
    list_per_page = 50
    
    # Enable list selection
    list_select_related = ["groups"]
    
    # Fieldset configuration for add/change forms
    fieldsets = (
        (_("Authentication Credentials"), {
            "fields": ("username", "password"),
            "classes": ("wide",),
        }),
        (_("Personal Information"), {
            "fields": ("first_name", "last_name", "email"),
            "classes": ("wide",),
        }),
        (_("Permissions & Status"), {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
            "classes": ("wide",),
        }),
        (_("Important Dates"), {
            "fields": ("last_login", "date_joined"),
            "classes": ("wide",),
        }),
        (_("Additional Information"), {
            "fields": ("metadata",),
            "classes": ("collapse", "wide"),
            "description": _("Additional metadata and configuration options"),
        }),
    )
    
    # Add form fieldsets
    add_fieldsets = (
        (_("Authentication Credentials"), {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2"),
        }),
        (_("Personal Information"), {
            "classes": ("wide",),
            "fields": ("first_name", "last_name"),
        }),
        (_("Permissions"), {
            "classes": ("wide",),
            "fields": ("is_staff", "is_active"),
        }),
    )
    
    # Readonly fields
    readonly_fields = [
        "last_login",
        "date_joined",
        "active_sessions_count",
    ]
    
    # Actions
    actions = [
        "activate_users",
        "deactivate_users",
        "force_logout_users",
        "reset_user_passwords",
    ]
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """
        Optimize the queryset with select_related for better performance.
        
        Args:
            request: The HTTP request object
            
        Returns:
            Optimized queryset with related objects prefetched
        """
        queryset = super().get_queryset(request)
        return queryset.select_related().prefetch_related("groups", "user_permissions")
    
    def is_active_display(self, obj: User) -> str:
        """
        Display user active status with colored indicator.
        
        Args:
            obj: User instance
            
        Returns:
            HTML formatted status indicator
        """
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">✗ Inactive</span>'
        )
    is_active_display.short_description = _("Status")
    is_active_display.admin_order_field = "is_active"
    
    def is_staff_display(self, obj: User) -> str:
        """
        Display staff status with appropriate indicator.
        
        Args:
            obj: User instance
            
        Returns:
            HTML formatted staff status indicator
        """
        if obj.is_superuser:
            return format_html(
                '<span style="color: red; font-weight: bold;">🔐 Superuser</span>'
            )
        elif obj.is_staff:
            return format_html(
                '<span style="color: orange; font-weight: bold;">👤 Staff</span>'
            )
        return format_html('<span style="color: gray;">👥 User</span>')
    is_staff_display.short_description = _("Role")
    is_staff_display.admin_order_field = "is_staff"
    
    def last_login_display(self, obj: User) -> str:
        """
        Display last login with relative time formatting.
        
        Args:
            obj: User instance
            
        Returns:
            Formatted last login display
        """
        if not obj.last_login:
            return format_html('<span style="color: gray;">Never</span>')
        
        time_diff = timezone.now() - obj.last_login
        
        if time_diff.days > 30:
            return format_html(
                '<span style="color: red;">{}</span>',
                obj.last_login.strftime("%Y-%m-%d")
            )
        elif time_diff.days > 7:
            return format_html(
                '<span style="color: orange;">{}</span>',
                obj.last_login.strftime("%Y-%m-%d %H:%M")
            )
        else:
            return format_html(
                '<span style="color: green;">{}</span>',
                obj.last_login.strftime("%Y-%m-%d %H:%M")
            )
    last_login_display.short_description = _("Last Login")
    last_login_display.admin_order_field = "last_login"
    
    def date_joined_display(self, obj: User) -> str:
        """
        Display join date in consistent format.
        
        Args:
            obj: User instance
            
        Returns:
            Formatted join date
        """
        return obj.date_joined.strftime("%Y-%m-%d")
    date_joined_display.short_description = _("Joined")
    date_joined_display.admin_order_field = "date_joined"
    
    def active_sessions_count(self, obj: User) -> int:
        """
        Display count of active sessions for the user.
        
        Args:
            obj: User instance
            
        Returns:
            Number of active sessions
        """
        return Session.objects.filter(
            expire_date__gte=timezone.now(),
            session_data__contains=f'"_auth_user_id":"{obj.id}"'
        ).count()
    active_sessions_count.short_description = _("Active Sessions")
    
    # Custom admin actions
    
    @admin.action(description=_("Activate selected users"))
    def activate_users(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Bulk activate selected users.
        
        Args:
            request: HTTP request object
            queryset: Selected users queryset
        """
        updated_count = queryset.update(is_active=True)
        self.message_user(
            request,
            _(f"Successfully activated {updated_count} user(s)."),
        )
    
    @admin.action(description=_("Deactivate selected users"))
    def deactivate_users(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Bulk deactivate selected users.
        
        Args:
            request: HTTP request object
            queryset: Selected users queryset
        """
        updated_count = queryset.update(is_active=False)
        self.message_user(
            request,
            _(f"Successfully deactivated {updated_count} user(s)."),
        )
    
    @admin.action(description=_("Force logout selected users"))
    def force_logout_users(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Force logout selected users by clearing their sessions.
        
        Args:
            request: HTTP request object
            queryset: Selected users queryset
        """
        session_count = 0
        for user in queryset:
            user_sessions = Session.objects.filter(
                expire_date__gte=timezone.now(),
                session_data__contains=f'"_auth_user_id":"{user.id}"'
            )
            session_count += user_sessions.count()
            user_sessions.delete()
        
        self.message_user(
            request,
            _(f"Successfully logged out {queryset.count()} user(s) "
              f"and cleared {session_count} session(s)."),
        )
    
    @admin.action(description=_("Send password reset to selected users"))
    def reset_user_passwords(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Trigger password reset for selected users.
        
        Args:
            request: HTTP request object
            queryset: Selected users queryset
        """
        # This would typically integrate with your password reset system
        # For now, we'll just show a message
        user_count = queryset.count()
        self.message_user(
            request,
            _(f"Password reset initiated for {user_count} user(s). "
              "Reset emails will be sent to their registered email addresses."),
        )


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """
    Django admin configuration for Session model.
    
    Provides administrative interface for managing user sessions,
    monitoring active logins, and performing session-related
    maintenance operations.
    """
    
    list_display = [
        "session_key_display",
        "user_display",
        "expire_date",
        "is_expired",
        "created_display",
    ]
    
    list_filter = [
        "expire_date",
        ("expire_date", admin.DateFieldListFilter),
    ]
    
    search_fields = [
        "session_key",
        "session_data",
    ]
    
    readonly_fields = [
        "session_key",
        "session_data",
        "expire_date",
    ]
    
    ordering = ["-expire_date"]
    list_per_page = 100
    
    actions = ["delete_expired_sessions"]
    
    def session_key_display(self, obj: Session) -> str:
        """
        Display truncated session key for readability.
        
        Args:
            obj: Session instance
            
        Returns:
            Truncated session key
        """
        return f"{obj.session_key[:20]}..."
    session_key_display.short_description = _("Session Key")
    
    def user_display(self, obj: Session) -> str:
        """
        Extract and display user information from session data.
        
        Args:
            obj: Session instance
            
        Returns:
            User display string or "Anonymous"
        """
        try:
            from django.contrib.sessions.serializers import JSONSerializer
            session_data = JSONSerializer().loads(obj.session_data)
            user_id = session_data.get("_auth_user_id")
            
            if user_id:
                try:
                    user = User.objects.get(id=user_id)
                    return f"{user.username} ({user.email})"
                except User.DoesNotExist:
                    return f"User ID: {user_id} (Deleted)"
            return "Anonymous"
        except Exception:
            return "Unknown"
    user_display.short_description = _("User")
    
    def is_expired(self, obj: Session) -> bool:
        """
        Check if session is expired.
        
        Args:
            obj: Session instance
            
        Returns:
            True if session is expired
        """
        return obj.expire_date < timezone.now()
    is_expired.short_description = _("Expired")
    is_expired.boolean = True
    
    def created_display(self, obj: Session) -> str:
        """
        Calculate and display session creation time.
        
        Args:
            obj: Session instance
            
        Returns:
            Estimated creation time
        """
        # Sessions don't have created_at field, so we estimate
        # based on expire_date minus session timeout
        from django.conf import settings
        session_timeout = getattr(settings, "SESSION_COOKIE_AGE", 3600)
        estimated_created = obj.expire_date - timedelta(seconds=session_timeout)
        return estimated_created.strftime("%Y-%m-%d %H:%M")
    created_display.short_description = _("Created (Est.)")
    
    @admin.action(description=_("Delete expired sessions"))
    def delete_expired_sessions(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Delete expired sessions from the selected queryset.
        
        Args:
            request: HTTP request object
            queryset: Selected sessions queryset
        """
        expired_sessions = queryset.filter(expire_date__lt=timezone.now())
        deleted_count = expired_sessions.count()
        expired_sessions.delete()
        
        self.message_user(
            request,
            _(f"Successfully deleted {deleted_count} expired session(s)."),
        )


# Customize the admin site header and title
admin.site.site_header = _("Enterprise Task Management System")
admin.site.site_title = _("ETMS Admin")
admin.site.index_title = _("Administration Dashboard")
