"""
Common Django admin configurations and mixins.
"""
from typing import Any, Dict, List, Optional, Tuple, Type

from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.db import models
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.core.exceptions import ValidationError
from django.contrib import messages


class BaseModelAdmin(ModelAdmin):
    """
    Base admin class with common configurations for all models.
    """

    # Common fields that should be readonly
    readonly_fields = ('id', 'created_at', 'updated_at')

    # Default list per page
    list_per_page = 25

    # Enable search by default
    search_fields = ('id',)

    # Default ordering
    ordering = ('-created_at',)

    # Show full result count
    show_full_result_count = False

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Tuple[str, ...]:
        """
        Return readonly fields based on user permissions and object state.
        """
        readonly = list(self.readonly_fields)

        # Make all fields readonly for non-staff users
        if not request.user.is_staff:
            return tuple(readonly + [f.name for f in self.model._meta.fields])

        # Add timestamps for existing objects
        if obj and hasattr(obj, 'created_at'):
            if 'created_at' not in readonly:
                readonly.append('created_at')

        if obj and hasattr(obj, 'updated_at'):
            if 'updated_at' not in readonly:
                readonly.append('updated_at')

        return tuple(readonly)

    def get_list_display(self, request: HttpRequest) -> Tuple[str, ...]:
        """
        Return list display fields with common additions.
        """
        list_display = list(self.list_display) if self.list_display else []

        # Add common fields if they exist and aren't already included
        common_fields = ['id', 'created_at', 'updated_at']
        for field in common_fields:
            if (hasattr(self.model, field) and 
                field not in list_display and 
                len(list_display) < 8):  # Limit number of columns
                list_display.append(field)

        return tuple(list_display)

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        """
        Enhanced save with audit trail.
        """
        # Set created_by and updated_by if fields exist
        if hasattr(obj, 'updated_by'):
            obj.updated_by = request.user

        if not change and hasattr(obj, 'created_by'):
            obj.created_by = request.user

        try:
            super().save_model(request, obj, form, change)

            action = "updated" if change else "created"
            messages.success(
                request, 
                f"{obj._meta.verbose_name.title()} '{obj}' was successfully {action}."
            )
        except ValidationError as e:
            messages.error(request, f"Validation error: {e}")
        except Exception as e:
            messages.error(request, f"Error saving {obj._meta.verbose_name}: {e}")


class TimestampedModelAdmin(BaseModelAdmin):
    """
    Admin for models that inherit from TimestampedModel.
    """

    readonly_fields = ('created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')

    def get_fieldsets(self, request: HttpRequest, obj: Any = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Return fieldsets with timestamps section.
        """
        fieldsets = list(self.fieldsets) if self.fieldsets else []

        # Add timestamp fieldset if object exists
        if obj:
            fieldsets.append(
                ('Timestamps', {
                    'fields': ('created_at', 'updated_at'),
                    'classes': ('collapse',)
                })
            )

        return fieldsets


class SoftDeleteModelAdmin(BaseModelAdmin):
    """
    Admin for models with soft delete functionality.
    """

    list_filter = ('is_active', 'created_at', 'updated_at')
    actions = ['make_active', 'make_inactive', 'permanent_delete']

    def get_queryset(self, request: HttpRequest) -> models.QuerySet:
        """
        Include soft-deleted objects in admin.
        """
        qs = self.model._default_manager.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def make_active(self, request: HttpRequest, queryset: models.QuerySet) -> None:
        """Action to activate selected objects."""
        updated = queryset.update(is_active=True)
        messages.success(
            request,
            f"Successfully activated {updated} {self.model._meta.verbose_name_plural}."
        )
    make_active.short_description = "Activate selected items"

    def make_inactive(self, request: HttpRequest, queryset: models.QuerySet) -> None:
        """Action to deactivate selected objects."""
        updated = queryset.update(is_active=False)
        messages.success(
            request,
            f"Successfully deactivated {updated} {self.model._meta.verbose_name_plural}."
        )
    make_inactive.short_description = "Deactivate selected items"

    def permanent_delete(self, request: HttpRequest, queryset: models.QuerySet) -> None:
        """Action to permanently delete selected objects."""
        count = queryset.count()
        queryset.delete()
        messages.warning(
            request,
            f"Permanently deleted {count} {self.model._meta.verbose_name_plural}."
        )
    permanent_delete.short_description = "Permanently delete selected items"

    def delete_model(self, request: HttpRequest, obj: Any) -> None:
        """
        Soft delete by default, unless force delete is specified.
        """
        if hasattr(obj, 'soft_delete'):
            obj.soft_delete()
            messages.info(request, f"{obj._meta.verbose_name.title()} '{obj}' was soft deleted.")
        else:
            super().delete_model(request, obj)


class ReadOnlyModelAdmin(BaseModelAdmin):
    """
    Admin for read-only models (like logs, audit trails, etc.).
    """

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable add permission."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Disable change permission."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Disable delete permission."""
        return False

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Tuple[str, ...]:
        """Make all fields readonly."""
        return tuple(f.name for f in self.model._meta.fields)


class JSONFieldAdmin:
    """
    Mixin for better handling of JSON fields in admin.
    """

    def get_form(self, request: HttpRequest, obj: Any = None, **kwargs: Any) -> Type:
        """
        Customize form for JSON fields.
        """
        form = super().get_form(request, obj, **kwargs)

        # Find JSON fields and customize their widgets
        for field_name, field in form.base_fields.items():
            if isinstance(self.model._meta.get_field(field_name), models.JSONField):
                field.widget.attrs.update({
                    'rows': 10,
                    'cols': 80,
                    'style': 'font-family: monospace;'
                })

        return form


class BulkActionsMixin:
    """
    Mixin to add common bulk actions.
    """

    actions = ['export_as_json', 'duplicate_objects']

    def export_as_json(self, request: HttpRequest, queryset: models.QuerySet) -> None:
        """Export selected objects as JSON."""
        import json
        from django.http import JsonResponse

        data = []
        for obj in queryset:
            # Create a simple dict representation
            obj_data = {}
            for field in obj._meta.fields:
                value = getattr(obj, field.name)
                if hasattr(value, 'isoformat'):  # DateTime fields
                    value = value.isoformat()
                elif hasattr(value, '__str__'):
                    value = str(value)
                obj_data[field.name] = value
            data.append(obj_data)

        response = JsonResponse(data, safe=False)
        response['Content-Disposition'] = f'attachment; filename="{self.model._meta.verbose_name_plural}.json"'
        return response

    export_as_json.short_description = "Export selected as JSON"

    def duplicate_objects(self, request: HttpRequest, queryset: models.QuerySet) -> None:
        """Duplicate selected objects."""
        duplicated_count = 0
        for obj in queryset:
            # Create a copy by setting pk to None
            obj.pk = None
            obj.id = None

            # Update name/title if exists to avoid conflicts
            if hasattr(obj, 'name'):
                obj.name = f"{obj.name} (Copy)"
            elif hasattr(obj, 'title'):
                obj.title = f"{obj.title} (Copy)"

            try:
                obj.save()
                duplicated_count += 1
            except Exception as e:
                messages.error(request, f"Failed to duplicate {obj}: {e}")

        if duplicated_count:
            messages.success(
                request,
                f"Successfully duplicated {duplicated_count} {self.model._meta.verbose_name_plural}."
            )

    duplicate_objects.short_description = "Duplicate selected objects"


class RelatedObjectsMixin:
    """
    Mixin to display related objects with links.
    """

    def get_related_objects_display(self, obj: Any, related_field: str) -> str:
        """
        Generate HTML display for related objects.
        """
        related_manager = getattr(obj, related_field, None)
        if not related_manager:
            return "-"

        if hasattr(related_manager, 'all'):
            related_objects = related_manager.all()[:5]  # Limit to 5 objects
            if not related_objects:
                return "-"

            links = []
            for related_obj in related_objects:
                url = reverse(
                    f'admin:{related_obj._meta.app_label}_{related_obj._meta.model_name}_change',
                    args=[related_obj.pk]
                )
                links.append(f'<a href="{url}">{related_obj}</a>')

            result = ", ".join(links)

            # Add "and X more" if there are more objects
            total_count = related_manager.count()
            if total_count > 5:
                result += f" <em>(and {total_count - 5} more)</em>"

            return mark_safe(result)

        return str(related_manager)


# Register common admin site customizations
admin.site.site_header = "Task Management System Administration"
admin.site.site_title = "TMS Admin"
admin.site.index_title = "Welcome to Task Management System Administration"
