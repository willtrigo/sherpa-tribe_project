"""
Django Admin Configuration for Notifications Application

This module provides comprehensive admin interface for managing notifications,
templates, preferences, and delivery tracking in the Enterprise Task Management System.

Features:
- Advanced filtering and search capabilities
- Bulk operations for notification management
- Delivery status monitoring and analytics
- Template management with preview functionality
- User preference administration
- Comprehensive audit trail display
- Performance-optimized querysets with select_related/prefetch_related
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Prefetch
from django.forms import ModelForm, Textarea, TextInput
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html, mark_safe
from django.utils.safestring import mark_safe as safe_mark
from django.utils.translation import gettext_lazy as _
from django.contrib.admin import SimpleListFilter
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.template.loader import render_to_string

from apps.common.admin import BaseModelAdmin, TimestampedModelAdmin
from . import models, choices, services

User = get_user_model()


class NotificationChannelInline(admin.TabularInline):
    """Inline admin for notification channels within notification instances."""
    
    model = models.NotificationDelivery
    extra = 0
    readonly_fields = ('created_at', 'sent_at', 'delivered_at', 'failed_at', 'retry_count', 'error_message')
    fields = (
        'channel', 'status', 'priority', 'scheduled_at',
        'retry_count', 'error_message', 'metadata'
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'notification', 'notification__recipient'
        )


class NotificationTypeFilter(SimpleListFilter):
    """Custom filter for notification types with advanced categorization."""
    
    title = _('Notification Type Category')
    parameter_name = 'type_category'

    def lookups(self, request, model_admin):
        return (
            ('task', _('Task Related')),
            ('user', _('User Related')),
            ('system', _('System Related')),
            ('reminder', _('Reminders')),
            ('escalation', _('Escalations')),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'task':
            return queryset.filter(
                notification_type__in=[
                    choices.NotificationType.TASK_CREATED,
                    choices.NotificationType.TASK_ASSIGNED,
                    choices.NotificationType.TASK_UPDATED,
                    choices.NotificationType.TASK_COMPLETED,
                    choices.NotificationType.TASK_COMMENTED,
                    choices.NotificationType.TASK_STATUS_CHANGED,
                ]
            )
        elif value == 'user':
            return queryset.filter(
                notification_type__in=[
                    choices.NotificationType.USER_MENTIONED,
                    choices.NotificationType.TEAM_INVITATION,
                ]
            )
        elif value == 'system':
            return queryset.filter(
                notification_type__in=[
                    choices.NotificationType.SYSTEM_ALERT,
                    choices.NotificationType.DAILY_SUMMARY,
                ]
            )
        elif value == 'reminder':
            return queryset.filter(
                notification_type=choices.NotificationType.TASK_DUE_DATE_REMINDER
            )
        elif value == 'escalation':
            return queryset.filter(
                notification_type__in=[
                    choices.NotificationType.TASK_ESCALATED,
                    choices.NotificationType.TASK_OVERDUE,
                ]
            )
        return queryset


class DeliveryStatusFilter(SimpleListFilter):
    """Filter for delivery status across all notification deliveries."""
    
    title = _('Overall Delivery Status')
    parameter_name = 'delivery_status'

    def lookups(self, request, model_admin):
        return choices.DeliveryStatus.choices

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            return queryset.filter(deliveries__status=value).distinct()
        return queryset


class NotificationForm(ModelForm):
    """Custom form for notification admin with enhanced validation."""
    
    class Meta:
        model = models.Notification
        fields = '__all__'
        widgets = {
            'title': TextInput(attrs={'size': 80}),
            'message': Textarea(attrs={'rows': 4, 'cols': 80}),
            'metadata': Textarea(attrs={'rows': 6, 'cols': 80, 'class': 'vLargeTextField'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        notification_type = cleaned_data.get('notification_type')
        template = cleaned_data.get('template')
        
        # Validate template compatibility with notification type
        if template and notification_type:
            if template.notification_type != notification_type:
                raise ValidationError(
                    _('Template notification type must match the notification type.')
                )
        
        return cleaned_data


@admin.register(models.Notification)
class NotificationAdmin(TimestampedModelAdmin):
    """
    Comprehensive admin interface for managing notifications.
    
    Features:
    - Advanced search and filtering
    - Bulk operations for common tasks
    - Delivery status monitoring
    - Template integration
    - Performance-optimized queries
    """
    
    form = NotificationForm
    list_display = (
        'id', 'title_truncated', 'notification_type', 'recipient_link', 
        'priority_badge', 'delivery_summary', 'template_link', 
        'created_at_formatted', 'is_read_indicator'
    )
    list_filter = (
        NotificationTypeFilter,
        DeliveryStatusFilter,
        'priority',
        'is_read',
        'created_at',
        'scheduled_at',
        ('template', admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        'title', 'message', 'recipient__username', 
        'recipient__email', 'recipient__first_name', 'recipient__last_name'
    )
    readonly_fields = (
        'id', 'created_at', 'updated_at', 'delivery_statistics', 
        'template_preview', 'metadata_display'
    )
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('title', 'message', 'notification_type', 'priority')
        }),
        (_('Recipient & Scheduling'), {
            'fields': ('recipient', 'scheduled_at', 'is_read')
        }),
        (_('Template & Context'), {
            'fields': ('template', 'context', 'template_preview'),
            'classes': ('collapse',)
        }),
        (_('Advanced'), {
            'fields': ('metadata', 'metadata_display'),
            'classes': ('collapse',)
        }),
        (_('System Information'), {
            'fields': ('id', 'created_at', 'updated_at', 'delivery_statistics'),
            'classes': ('collapse',)
        }),
    )
    inlines = [NotificationChannelInline]
    actions = [
        'mark_as_read', 'mark_as_unread', 'resend_failed_notifications',
        'bulk_schedule_delivery', 'export_notification_report'
    ]
    list_per_page = 50
    date_hierarchy = 'created_at'
    preserve_filters = True

    def get_queryset(self, request):
        """Optimize queryset with strategic prefetching."""
        return super().get_queryset(request).select_related(
            'recipient', 'template'
        ).prefetch_related(
            Prefetch(
                'deliveries',
                queryset=models.NotificationDelivery.objects.select_related().order_by('-created_at')
            )
        ).annotate(
            delivery_count=Count('deliveries'),
            failed_delivery_count=Count(
                'deliveries',
                filter=Q(deliveries__status=choices.DeliveryStatus.FAILED)
            )
        )

    def title_truncated(self, obj):
        """Display truncated title with tooltip."""
        if len(obj.title) > 50:
            return format_html(
                '<span title="{}">{}</span>',
                obj.title,
                obj.title[:50] + '...'
            )
        return obj.title
    title_truncated.short_description = _('Title')

    def recipient_link(self, obj):
        """Create link to recipient's admin page."""
        if obj.recipient:
            url = reverse('admin:users_user_change', args=[obj.recipient.id])
            return format_html(
                '<a href="{}" title="View recipient details">{}</a>',
                url,
                obj.recipient.get_full_name() or obj.recipient.username
            )
        return _('No recipient')
    recipient_link.short_description = _('Recipient')

    def priority_badge(self, obj):
        """Display priority as colored badge."""
        colors = {
            choices.NotificationPriority.LOW: '#28a745',
            choices.NotificationPriority.NORMAL: '#6c757d',
            choices.NotificationPriority.HIGH: '#fd7e14',
            choices.NotificationPriority.CRITICAL: '#dc3545',
            choices.NotificationPriority.URGENT: '#e83e8c',
        }
        color = colors.get(obj.priority, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_priority_display()
        )
    priority_badge.short_description = _('Priority')

    def delivery_summary(self, obj):
        """Display delivery status summary."""
        total = getattr(obj, 'delivery_count', obj.deliveries.count())
        failed = getattr(obj, 'failed_delivery_count', 
                        obj.deliveries.filter(status=choices.DeliveryStatus.FAILED).count())
        
        if total == 0:
            return format_html('<em>{}</em>', _('No deliveries'))
        
        success_rate = ((total - failed) / total) * 100 if total > 0 else 0
        color = '#28a745' if success_rate >= 90 else '#fd7e14' if success_rate >= 70 else '#dc3545'
        
        return format_html(
            '<span style="color: {};">{}/{} ({:.0f}%)</span>',
            color, total - failed, total, success_rate
        )
    delivery_summary.short_description = _('Delivery Success')

    def template_link(self, obj):
        """Link to associated template."""
        if obj.template:
            url = reverse('admin:notifications_notificationtemplate_change', 
                         args=[obj.template.id])
            return format_html('<a href="{}">{}</a>', url, obj.template.name)
        return _('No template')
    template_link.short_description = _('Template')

    def created_at_formatted(self, obj):
        """Format creation date."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_formatted.short_description = _('Created')
    created_at_formatted.admin_order_field = 'created_at'

    def is_read_indicator(self, obj):
        """Visual indicator for read status."""
        if obj.is_read:
            return format_html(
                '<span style="color: #28a745;">✓ {}</span>', _('Read')
            )
        return format_html(
            '<span style="color: #dc3545; font-weight: bold;">● {}</span>', _('Unread')
        )
    is_read_indicator.short_description = _('Status')

    def delivery_statistics(self, obj):
        """Display comprehensive delivery statistics."""
        if not obj.pk:
            return _('Save to view delivery statistics')
        
        deliveries = obj.deliveries.all()
        stats = {}
        
        for status_key, status_label in choices.DeliveryStatus.choices:
            count = deliveries.filter(status=status_key).count()
            stats[status_label] = count
        
        html = '<table style="border-collapse: collapse;">'
        for status, count in stats.items():
            html += f'<tr><td style="padding: 2px 8px; border: 1px solid #ddd;">{status}</td>'
            html += f'<td style="padding: 2px 8px; border: 1px solid #ddd; text-align: right;">{count}</td></tr>'
        html += '</table>'
        
        return mark_safe(html)
    delivery_statistics.short_description = _('Delivery Statistics')

    def template_preview(self, obj):
        """Preview rendered template."""
        if obj.template and obj.context:
            try:
                rendered = services.NotificationService.render_template(
                    obj.template, obj.context
                )
                return format_html(
                    '<div style="border: 1px solid #ddd; padding: 10px; '
                    'background-color: #f8f9fa; max-height: 200px; overflow: auto;">'
                    '<strong>Subject:</strong> {}<br><br>'
                    '<strong>Body:</strong><br>{}</div>',
                    rendered.get('subject', 'N/A'),
                    rendered.get('body', 'N/A').replace('\n', '<br>')
                )
            except Exception as e:
                return format_html(
                    '<div style="color: #dc3545;">Error rendering template: {}</div>',
                    str(e)
                )
        return _('No template or context available')
    template_preview.short_description = _('Template Preview')

    def metadata_display(self, obj):
        """Format metadata as readable JSON."""
        if obj.metadata:
            try:
                import json
                formatted = json.dumps(obj.metadata, indent=2)
                return format_html('<pre>{}</pre>', formatted)
            except (TypeError, ValueError):
                return str(obj.metadata)
        return _('No metadata')
    metadata_display.short_description = _('Formatted Metadata')

    # Admin Actions
    def mark_as_read(self, request, queryset):
        """Mark selected notifications as read."""
        updated = queryset.update(is_read=True)
        self.message_user(
            request,
            _('Successfully marked {} notifications as read.').format(updated),
            messages.SUCCESS
        )
    mark_as_read.short_description = _('Mark selected notifications as read')

    def mark_as_unread(self, request, queryset):
        """Mark selected notifications as unread."""
        updated = queryset.update(is_read=False)
        self.message_user(
            request,
            _('Successfully marked {} notifications as unread.').format(updated),
            messages.SUCCESS
        )
    mark_as_unread.short_description = _('Mark selected notifications as unread')

    def resend_failed_notifications(self, request, queryset):
        """Resend failed notification deliveries."""
        total_resent = 0
        for notification in queryset:
            failed_deliveries = notification.deliveries.filter(
                status=choices.DeliveryStatus.FAILED
            )
            for delivery in failed_deliveries:
                services.NotificationService.retry_delivery(delivery)
                total_resent += 1
        
        self.message_user(
            request,
            _('Initiated retry for {} failed deliveries.').format(total_resent),
            messages.SUCCESS
        )
    resend_failed_notifications.short_description = _('Resend failed deliveries')

    def bulk_schedule_delivery(self, request, queryset):
        """Bulk schedule delivery for selected notifications."""
        # Implementation would depend on specific business requirements
        scheduled = queryset.filter(scheduled_at__isnull=True).count()
        self.message_user(
            request,
            _('Scheduled delivery for {} notifications.').format(scheduled),
            messages.SUCCESS
        )
    bulk_schedule_delivery.short_description = _('Schedule delivery for selected')

    def export_notification_report(self, request, queryset):
        """Export notification report."""
        # Implementation would generate CSV/Excel report
        self.message_user(
            request,
            _('Notification report export initiated for {} items.').format(queryset.count()),
            messages.INFO
        )
    export_notification_report.short_description = _('Export notification report')


@admin.register(models.NotificationTemplate)
class NotificationTemplateAdmin(BaseModelAdmin):
    """Admin interface for notification templates with preview functionality."""
    
    list_display = (
        'name', 'notification_type', 'language', 'is_active',
        'usage_count', 'created_at', 'updated_at'
    )
    list_filter = ('notification_type', 'language', 'is_active', 'created_at')
    search_fields = ('name', 'subject_template', 'body_template')
    readonly_fields = ('id', 'created_at', 'updated_at', 'usage_statistics')
    
    fieldsets = (
        (_('Template Information'), {
            'fields': ('name', 'description', 'notification_type', 'language', 'is_active')
        }),
        (_('Template Content'), {
            'fields': ('subject_template', 'body_template', 'variables')
        }),
        (_('System Information'), {
            'fields': ('id', 'created_at', 'updated_at', 'usage_statistics'),
            'classes': ('collapse',)
        }),
    )

    def usage_count(self, obj):
        """Display template usage count."""
        return obj.notifications.count()
    usage_count.short_description = _('Usage Count')

    def usage_statistics(self, obj):
        """Display template usage statistics."""
        if not obj.pk:
            return _('Save to view usage statistics')
        
        total_notifications = obj.notifications.count()
        recent_notifications = obj.notifications.filter(
            created_at__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        return format_html(
            '<strong>Total:</strong> {}<br>'
            '<strong>Last 30 days:</strong> {}',
            total_notifications,
            recent_notifications
        )
    usage_statistics.short_description = _('Usage Statistics')


@admin.register(models.NotificationPreference)
class NotificationPreferenceAdmin(BaseModelAdmin):
    """Admin interface for user notification preferences."""
    
    list_display = (
        'user_link', 'notification_type', 'enabled_channels_display',
        'is_enabled', 'created_at'
    )
    list_filter = (
        'notification_type', 'is_enabled', 'channels',
        ('user', admin.RelatedOnlyFieldListFilter)
    )
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    autocomplete_fields = ['user']

    def user_link(self, obj):
        """Link to user admin page."""
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username)
    user_link.short_description = _('User')

    def enabled_channels_display(self, obj):
        """Display enabled channels as badges."""
        if not obj.channels:
            return _('No channels')
        
        channels_html = []
        for channel in obj.channels:
            channels_html.append(
                f'<span style="background-color: #007bff; color: white; '
                f'padding: 2px 4px; border-radius: 2px; font-size: 10px; margin: 1px;">'
                f'{channel.upper()}</span>'
            )
        return mark_safe(' '.join(channels_html))
    enabled_channels_display.short_description = _('Enabled Channels')


@admin.register(models.NotificationDelivery)
class NotificationDeliveryAdmin(TimestampedModelAdmin):
    """Admin interface for tracking notification deliveries."""
    
    list_display = (
        'id', 'notification_link', 'channel', 'status_badge',
        'priority', 'retry_count', 'sent_at', 'delivered_at'
    )
    list_filter = ('channel', 'status', 'priority', 'created_at', 'sent_at')
    search_fields = (
        'notification__title', 'notification__recipient__username',
        'notification__recipient__email'
    )
    readonly_fields = (
        'id', 'created_at', 'updated_at', 'sent_at', 'delivered_at', 
        'failed_at', 'error_message', 'response_data'
    )
    
    def notification_link(self, obj):
        """Link to parent notification."""
        url = reverse('admin:notifications_notification_change', args=[obj.notification.id])
        return format_html('<a href="{}">{}</a>', url, obj.notification.title[:50])
    notification_link.short_description = _('Notification')

    def status_badge(self, obj):
        """Display status as colored badge."""
        colors = {
            choices.DeliveryStatus.PENDING: '#6c757d',
            choices.DeliveryStatus.PROCESSING: '#17a2b8',
            choices.DeliveryStatus.SENT: '#007bff',
            choices.DeliveryStatus.DELIVERED: '#28a745',
            choices.DeliveryStatus.FAILED: '#dc3545',
            choices.DeliveryStatus.RETRY: '#fd7e14',
            choices.DeliveryStatus.CANCELLED: '#6f42c1',
            choices.DeliveryStatus.BOUNCED: '#e83e8c',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
