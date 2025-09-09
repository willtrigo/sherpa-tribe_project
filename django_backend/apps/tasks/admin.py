"""
Django Admin configuration for Task Management System.

This module provides comprehensive admin interfaces for task-related models,
implementing advanced features like custom actions, filters, and optimized queries.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, QuerySet
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import Task, Comment, Tag, TaskAssignment, TaskHistory, TaskTemplate
from .choices import TaskStatus, TaskPriority
from .forms import TaskAdminForm, CommentInlineForm


User = get_user_model()


class TaskHistoryInline(admin.TabularInline):
    """Inline admin for TaskHistory model with read-only historical data."""
    
    model = TaskHistory
    extra = 0
    readonly_fields = (
        'action_type', 'field_name', 'old_value', 'new_value', 
        'changed_by', 'timestamp', 'ip_address'
    )
    can_delete = False
    
    def has_add_permission(self, request: HttpRequest, obj: Optional[Any] = None) -> bool:
        """Prevent manual addition of history records."""
        return False


class CommentInline(admin.StackedInline):
    """Inline admin for Task comments with enhanced functionality."""
    
    model = Comment
    form = CommentInlineForm
    extra = 0
    readonly_fields = ('created_at', 'updated_at')
    fields = (
        'content', 'author', 'is_internal', 
        ('created_at', 'updated_at')
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize comment queries with select_related."""
        return super().get_queryset(request).select_related('author')


class TaskAssignmentInline(admin.TabularInline):
    """Inline admin for TaskAssignment through model."""
    
    model = TaskAssignment
    extra = 0
    readonly_fields = ('assigned_at', 'assigned_by')
    autocomplete_fields = ('assigned_to',)
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize assignment queries."""
        return super().get_queryset(request).select_related(
            'assigned_to', 'assigned_by'
        )


@admin.register(Task)
class TaskAdmin(ModelAdmin):
    """
    Advanced Task admin with comprehensive functionality.
    
    Features:
    - Optimized queries with select_related and prefetch_related
    - Custom actions for bulk operations
    - Advanced filtering and search
    - Inline editing for related models
    - Custom display methods with enhanced formatting
    """
    
    form = TaskAdminForm
    list_display = (
        'title', 'status_badge', 'priority_badge', 'assigned_users_display',
        'progress_bar', 'due_date_display', 'created_by', 'created_at'
    )
    list_filter = (
        'status', 'priority', 'is_archived', 'created_at', 'due_date',
        ('assigned_to', admin.RelatedOnlyFieldListFilter),
        ('created_by', admin.RelatedOnlyFieldListFilter),
        ('tags', admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        'title', 'description', 'tags__name', 
        'assigned_to__username', 'created_by__username'
    )
    readonly_fields = (
        'created_at', 'updated_at', 'completion_percentage',
        'time_spent_display', 'days_until_due'
    )
    autocomplete_fields = ('parent_task', 'created_by')
    filter_horizontal = ('assigned_to', 'tags')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'title', 'description', 'parent_task'
            )
        }),
        (_('Status & Priority'), {
            'fields': (
                ('status', 'priority'), 
                'is_archived'
            )
        }),
        (_('Assignment & Ownership'), {
            'fields': (
                'created_by', 'assigned_to', 'tags'
            )
        }),
        (_('Time Tracking'), {
            'fields': (
                ('due_date', 'estimated_hours'), 
                ('actual_hours', 'completion_percentage')
            )
        }),
        (_('Metadata'), {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        (_('System Information'), {
            'fields': (
                ('created_at', 'updated_at'),
                ('time_spent_display', 'days_until_due')
            ),
            'classes': ('collapse',)
        })
    )
    
    inlines = [TaskAssignmentInline, CommentInline, TaskHistoryInline]
    actions = [
        'mark_as_in_progress', 'mark_as_completed', 'mark_as_blocked',
        'archive_tasks', 'unarchive_tasks', 'assign_to_me', 'bulk_update_priority'
    ]
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize queryset with proper select_related and prefetch_related."""
        return super().get_queryset(request).select_related(
            'created_by', 'parent_task'
        ).prefetch_related(
            'assigned_to', 'tags', 'comments', 'task_history'
        ).annotate(
            assigned_count=Count('assigned_to'),
            comment_count=Count('comments')
        )
    
    def status_badge(self, obj: Task) -> str:
        """Display status as a colored badge."""
        color_mapping = {
            TaskStatus.TODO: '#6c757d',
            TaskStatus.IN_PROGRESS: '#007bff', 
            TaskStatus.IN_REVIEW: '#ffc107',
            TaskStatus.COMPLETED: '#28a745',
            TaskStatus.BLOCKED: '#dc3545',
            TaskStatus.CANCELLED: '#6f42c1'
        }
        color = color_mapping.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 12px; font-size: 11px; '
            'font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'
    
    def priority_badge(self, obj: Task) -> str:
        """Display priority as a colored badge."""
        color_mapping = {
            TaskPriority.LOW: '#17a2b8',
            TaskPriority.MEDIUM: '#ffc107',
            TaskPriority.HIGH: '#fd7e14',
            TaskPriority.CRITICAL: '#dc3545'
        }
        color = color_mapping.get(obj.priority, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 12px; font-size: 11px; '
            'font-weight: bold;">{}</span>',
            color, obj.get_priority_display()
        )
    priority_badge.short_description = _('Priority')
    priority_badge.admin_order_field = 'priority'
    
    def assigned_users_display(self, obj: Task) -> str:
        """Display assigned users with count."""
        assigned_count = getattr(obj, 'assigned_count', obj.assigned_to.count())
        if assigned_count == 0:
            return format_html('<em style="color: #6c757d;">{}</em>', _('Unassigned'))
        
        users = obj.assigned_to.all()[:3]  # Show first 3 users
        user_links = [
            format_html(
                '<a href="{}" style="text-decoration: none;">{}</a>',
                reverse('admin:auth_user_change', args=[user.pk]),
                user.get_full_name() or user.username
            ) for user in users
        ]
        
        display = ', '.join(user_links)
        if assigned_count > 3:
            display += format_html(' <em>(+{} more)</em>', assigned_count - 3)
        
        return mark_safe(display)
    assigned_users_display.short_description = _('Assigned To')
    
    def progress_bar(self, obj: Task) -> str:
        """Display progress as a visual progress bar."""
        if not obj.estimated_hours:
            return format_html('<em style="color: #6c757d;">{}</em>', _('No estimate'))
        
        actual = float(obj.actual_hours or 0)
        estimated = float(obj.estimated_hours)
        percentage = min((actual / estimated) * 100, 100)
        
        color = '#28a745' if percentage <= 100 else '#dc3545'
        
        return format_html(
            '<div style="width: 100px; background-color: #e9ecef; '
            'border-radius: 4px; overflow: hidden;">'
            '<div style="width: {}%; height: 20px; background-color: {}; '
            'display: flex; align-items: center; justify-content: center; '
            'color: white; font-size: 11px; font-weight: bold;">{:.1f}%</div>'
            '</div>',
            percentage, color, percentage
        )
    progress_bar.short_description = _('Progress')
    
    def due_date_display(self, obj: Task) -> str:
        """Display due date with color coding for urgency."""
        if not obj.due_date:
            return format_html('<em style="color: #6c757d;">{}</em>', _('No due date'))
        
        days_until_due = obj.days_until_due
        if days_until_due is None:
            color = '#6c757d'
        elif days_until_due < 0:
            color = '#dc3545'  # Overdue - red
        elif days_until_due <= 3:
            color = '#fd7e14'  # Due soon - orange
        else:
            color = '#28a745'  # On track - green
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.due_date.strftime('%Y-%m-%d')
        )
    due_date_display.short_description = _('Due Date')
    due_date_display.admin_order_field = 'due_date'
    
    def time_spent_display(self, obj: Task) -> str:
        """Display time spent vs estimated in a readable format."""
        if not obj.estimated_hours:
            return _('No estimate set')
        
        actual = obj.actual_hours or 0
        estimated = obj.estimated_hours
        
        return f'{actual}h / {estimated}h ({(actual/estimated*100):.1f}%)'
    time_spent_display.short_description = _('Time Spent')
    
    def completion_percentage(self, obj: Task) -> str:
        """Calculate and display completion percentage."""
        if not obj.estimated_hours:
            return '0%'
        
        actual = float(obj.actual_hours or 0)
        estimated = float(obj.estimated_hours)
        percentage = min((actual / estimated) * 100, 100)
        
        return f'{percentage:.1f}%'
    completion_percentage.short_description = _('Completion %')
    
    def days_until_due(self, obj: Task) -> Optional[str]:
        """Calculate days until due date."""
        days = obj.days_until_due
        if days is None:
            return None
        
        if days < 0:
            return f'{abs(days)} days overdue'
        elif days == 0:
            return 'Due today'
        else:
            return f'{days} days remaining'
    days_until_due.short_description = _('Days Until Due')
    
    # Custom Actions
    @admin.action(description=_('Mark selected tasks as In Progress'))
    def mark_as_in_progress(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to mark tasks as in progress."""
        updated = queryset.update(status=TaskStatus.IN_PROGRESS)
        self.message_user(
            request, 
            f'{updated} tasks marked as In Progress.',
            level='SUCCESS'
        )
    
    @admin.action(description=_('Mark selected tasks as Completed'))
    def mark_as_completed(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to mark tasks as completed."""
        updated = queryset.update(status=TaskStatus.COMPLETED)
        self.message_user(
            request,
            f'{updated} tasks marked as Completed.',
            level='SUCCESS'
        )
    
    @admin.action(description=_('Mark selected tasks as Blocked'))
    def mark_as_blocked(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to mark tasks as blocked."""
        updated = queryset.update(status=TaskStatus.BLOCKED)
        self.message_user(
            request,
            f'{updated} tasks marked as Blocked.',
            level='WARNING'
        )
    
    @admin.action(description=_('Archive selected tasks'))
    def archive_tasks(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to archive tasks."""
        updated = queryset.update(is_archived=True)
        self.message_user(
            request,
            f'{updated} tasks archived.',
            level='SUCCESS'
        )
    
    @admin.action(description=_('Unarchive selected tasks'))
    def unarchive_tasks(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to unarchive tasks."""
        updated = queryset.update(is_archived=False)
        self.message_user(
            request,
            f'{updated} tasks unarchived.',
            level='SUCCESS'
        )
    
    @admin.action(description=_('Assign selected tasks to me'))
    def assign_to_me(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to assign tasks to current user."""
        for task in queryset:
            task.assigned_to.add(request.user)
        
        self.message_user(
            request,
            f'{queryset.count()} tasks assigned to you.',
            level='SUCCESS'
        )
    
    @admin.action(description=_('Set priority to High for selected tasks'))
    def bulk_update_priority(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Bulk action to update task priority."""
        updated = queryset.update(priority=TaskPriority.HIGH)
        self.message_user(
            request,
            f'{updated} tasks priority updated to High.',
            level='SUCCESS'
        )


@admin.register(Comment)
class CommentAdmin(ModelAdmin):
    """Admin interface for Task comments."""
    
    list_display = (
        'content_preview', 'task_link', 'author', 'is_internal', 
        'created_at'
    )
    list_filter = ('is_internal', 'created_at', 'author')
    search_fields = ('content', 'task__title', 'author__username')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('task', 'author')
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize comment queries."""
        return super().get_queryset(request).select_related(
            'task', 'author'
        )
    
    def content_preview(self, obj: Comment) -> str:
        """Display truncated comment content."""
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = _('Content')
    
    def task_link(self, obj: Comment) -> str:
        """Display task as clickable link."""
        return format_html(
            '<a href="{}" style="text-decoration: none;">{}</a>',
            reverse('admin:tasks_task_change', args=[obj.task.pk]),
            obj.task.title
        )
    task_link.short_description = _('Task')


@admin.register(Tag)
class TagAdmin(ModelAdmin):
    """Admin interface for Task tags with usage statistics."""
    
    list_display = ('name', 'color_badge', 'task_count', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'description')
    readonly_fields = ('task_count', 'created_at', 'updated_at')
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate queryset with task count."""
        return super().get_queryset(request).annotate(
            task_count=Count('task')
        )
    
    def color_badge(self, obj: Tag) -> str:
        """Display tag color as a visual badge."""
        return format_html(
            '<span style="display: inline-block; width: 20px; height: 20px; '
            'background-color: {}; border-radius: 50%; border: 1px solid #ccc;"></span>',
            obj.color or '#6c757d'
        )
    color_badge.short_description = _('Color')
    
    def task_count(self, obj: Tag) -> int:
        """Display number of tasks using this tag."""
        return getattr(obj, 'task_count', 0)
    task_count.short_description = _('Tasks')
    task_count.admin_order_field = 'task_count'


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(ModelAdmin):
    """Admin interface for TaskAssignment through model."""
    
    list_display = (
        'task_link', 'assigned_to', 'assigned_by', 'assigned_at', 'is_active'
    )
    list_filter = ('assigned_at', 'is_active', 'assigned_by')
    search_fields = (
        'task__title', 'assigned_to__username', 'assigned_by__username'
    )
    readonly_fields = ('assigned_at',)
    autocomplete_fields = ('task', 'assigned_to', 'assigned_by')
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize assignment queries."""
        return super().get_queryset(request).select_related(
            'task', 'assigned_to', 'assigned_by'
        )
    
    def task_link(self, obj: TaskAssignment) -> str:
        """Display task as clickable link."""
        return format_html(
            '<a href="{}" style="text-decoration: none;">{}</a>',
            reverse('admin:tasks_task_change', args=[obj.task.pk]),
            obj.task.title
        )
    task_link.short_description = _('Task')


@admin.register(TaskHistory)
class TaskHistoryAdmin(ModelAdmin):
    """Admin interface for TaskHistory audit log."""
    
    list_display = (
        'task_link', 'action_type', 'field_name', 'changed_by', 
        'timestamp', 'ip_address'
    )
    list_filter = ('action_type', 'field_name', 'timestamp', 'changed_by')
    search_fields = (
        'task__title', 'field_name', 'old_value', 'new_value',
        'changed_by__username'
    )
    readonly_fields = (
        'task', 'action_type', 'field_name', 'old_value', 'new_value',
        'changed_by', 'timestamp', 'ip_address', 'user_agent'
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize history queries."""
        return super().get_queryset(request).select_related(
            'task', 'changed_by'
        )
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent manual addition of history records."""
        return False
    
    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Prevent modification of history records."""
        return False
    
    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Prevent deletion of history records."""
        return False
    
    def task_link(self, obj: TaskHistory) -> str:
        """Display task as clickable link."""
        return format_html(
            '<a href="{}" style="text-decoration: none;">{}</a>',
            reverse('admin:tasks_task_change', args=[obj.task.pk]),
            obj.task.title
        )
    task_link.short_description = _('Task')


@admin.register(TaskTemplate)
class TaskTemplateAdmin(ModelAdmin):
    """Admin interface for TaskTemplate with template management."""
    
    list_display = (
        'name', 'category', 'is_active', 'usage_count', 
        'created_by', 'created_at'
    )
    list_filter = ('category', 'is_active', 'created_at', 'created_by')
    search_fields = ('name', 'description', 'category')
    readonly_fields = ('usage_count', 'created_at', 'updated_at')
    autocomplete_fields = ('created_by',)
    filter_horizontal = ('default_tags',)
    
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Optimize template queries."""
        return super().get_queryset(request).select_related(
            'created_by'
        ).prefetch_related('default_tags')


# Register admin site customizations
admin.site.site_header = _('Task Management System Admin')
admin.site.site_title = _('Task Management Admin')
admin.site.index_title = _('Welcome to Task Management Administration')
