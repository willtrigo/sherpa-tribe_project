from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User, Team, TeamMembership


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Admin configuration for custom User model.
    """

    list_display = (
        'username', 'email', 'first_name', 'last_name',
        'role', 'status', 'department', 'is_staff', 'date_joined'
    )

    list_filter = (
        'role', 'status', 'department', 'is_staff',
        'is_superuser', 'is_active', 'date_joined'
    )

    search_fields = ('username', 'first_name', 'last_name', 'email', 'department')

    ordering = ('username',)

    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {
            'fields': ('first_name', 'last_name', 'email', 'phone_number', 'avatar', 'bio')
        }),
        (_('Work info'), {
            'fields': ('role', 'status', 'department', 'job_title', 'manager')
        }),
        (_('Preferences'), {
            'fields': ('timezone', 'language', 'email_notifications', 
                      'task_assignment_notifications', 'task_due_notifications')
        }),
        (_('Work capacity'), {
            'fields': ('max_concurrent_tasks', 'working_hours_per_day')
        }),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {
            'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')
        }),
        (_('Metadata'), {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role'),
        }),
    )

    readonly_fields = ('last_login', 'date_joined', 'created_at', 'updated_at')


class TeamMembershipInline(admin.TabularInline):
    """
    Inline for team memberships in Team admin.
    """
    model = TeamMembership
    extra = 0
    fields = ('user', 'role', 'joined_date', 'is_active', 'tasks_completed')
    readonly_fields = ('joined_date', 'tasks_completed')


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """
    Admin configuration for Team model.
    """

    list_display = (
        'name', 'team_type', 'lead', 'member_count',
        'is_active', 'created_at'
    )

    list_filter = ('team_type', 'is_active', 'created_at')

    search_fields = ('name', 'description', 'lead__username')

    ordering = ('name',)

    inlines = [TeamMembershipInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'team_type', 'lead')
        }),
        (_('Settings'), {
            'fields': ('is_active', 'max_members')
        }),
        (_('Metadata'), {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    def member_count(self, obj):
        """Display member count in list view."""
        return obj.member_count
    member_count.short_description = _('Members')


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    """
    Admin configuration for TeamMembership model.
    """

    list_display = (
        'user', 'team', 'role', 'joined_date',
        'is_active', 'tasks_completed'
    )

    list_filter = ('role', 'is_active', 'joined_date', 'team__team_type')

    search_fields = ('user__username', 'team__name')

    ordering = ('-joined_date',)

    fieldsets = (
        (None, {
            'fields': ('user', 'team', 'role')
        }),
        (_('Status'), {
            'fields': ('is_active', 'joined_date', 'tasks_completed')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('joined_date', 'created_at', 'updated_at')
