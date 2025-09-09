"""
Common serializers and mixins for the task management system.

Provides base serializers with common fields and functionality.
"""

from typing import Any, Dict

from rest_framework import serializers
from rest_framework.fields import empty


class TimestampSerializerMixin(serializers.Serializer):
    """Mixin to add timestamp fields to serializers."""

    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class UUIDSerializerMixin(serializers.Serializer):
    """Mixin to add UUID field to serializers."""

    id = serializers.UUIDField(read_only=True)


class MetadataSerializerMixin(serializers.Serializer):
    """Mixin to handle metadata field in serializers."""

    metadata = serializers.JSONField(required=False, default=dict)

    def validate_metadata(self, value: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metadata field."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be a JSON object.")
        return value


class AuditSerializerMixin(serializers.Serializer):
    """Mixin to add audit fields to serializers."""

    created_by = serializers.StringRelatedField(read_only=True)
    updated_by = serializers.StringRelatedField(read_only=True)


class SoftDeleteSerializerMixin(serializers.Serializer):
    """Mixin to add soft delete fields to serializers."""

    is_deleted = serializers.BooleanField(read_only=True)
    deleted_at = serializers.DateTimeField(read_only=True)
    deleted_by = serializers.StringRelatedField(read_only=True)


class ArchivableSerializerMixin(serializers.Serializer):
    """Mixin to add archiving fields to serializers."""

    is_archived = serializers.BooleanField(read_only=True)
    archived_at = serializers.DateTimeField(read_only=True)
    archived_by = serializers.StringRelatedField(read_only=True)


class BaseModelSerializer(
    UUIDSerializerMixin,
    TimestampSerializerMixin,
    MetadataSerializerMixin,
    AuditSerializerMixin,
    SoftDeleteSerializerMixin,
    serializers.ModelSerializer
):
    """
    Base serializer that includes all common fields.

    Provides UUID, timestamps, metadata, audit, and soft delete fields.
    """

    class Meta:
        abstract = True
        fields = [
            'id',
            'created_at',
            'updated_at',
            'metadata',
            'created_by',
            'updated_by',
            'is_deleted',
            'deleted_at',
            'deleted_by'
        ]
        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by',
            'is_deleted',
            'deleted_at',
            'deleted_by'
        ]


class DynamicFieldsSerializer(serializers.ModelSerializer):
    """
    Serializer that allows dynamic field selection.

    Usage:
        # Include only specific fields
        serializer = MySerializer(data, fields=('field1', 'field2'))

        # Exclude specific fields
        serializer = MySerializer(data, exclude=('field1', 'field2'))
    """

    def __init__(self, *args, **kwargs):
        # Extract fields and exclude arguments
        fields = kwargs.pop('fields', None)
        exclude = kwargs.pop('exclude', None)

        super().__init__(*args, **kwargs)

        if fields is not None:
            # Only include specified fields
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        if exclude is not None:
            # Remove excluded fields
            for field_name in exclude:
                self.fields.pop(field_name, None)


class WritableNestedSerializer(serializers.ModelSerializer):
    """
    Base serializer that handles writable nested relationships.

    Provides common patterns for handling nested object creation/updates.
    """

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Create instance with nested relationships."""
        nested_fields = self._extract_nested_fields(validated_data)
        instance = super().create(validated_data)
        self._create_nested_relations(instance, nested_fields)
        return instance

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Update instance with nested relationships."""
        nested_fields = self._extract_nested_fields(validated_data)
        instance = super().update(instance, validated_data)
        self._update_nested_relations(instance, nested_fields)
        return instance

    def _extract_nested_fields(self, validated_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract nested field data from validated_data."""
        nested_fields = {}

        # Override in subclasses to define which fields are nested
        for field_name in self._get_nested_field_names():
            if field_name in validated_data:
                nested_fields[field_name] = validated_data.pop(field_name)

        return nested_fields

    def _get_nested_field_names(self) -> list[str]:
        """Return list of nested field names. Override in subclasses."""
        return []

    def _create_nested_relations(self, instance: Any, nested_fields: Dict[str, Any]) -> None:
        """Create nested relations. Override in subclasses."""
        pass

    def _update_nested_relations(self, instance: Any, nested_fields: Dict[str, Any]) -> None:
        """Update nested relations. Override in subclasses."""
        pass


class BulkActionSerializer(serializers.Serializer):
    """Serializer for bulk actions on multiple objects."""

    ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="List of object IDs to perform action on"
    )
    action = serializers.ChoiceField(
        choices=[],  # Override in subclasses
        help_text="Action to perform on selected objects"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set choices dynamically if provided
        if hasattr(self, 'action_choices'):
            self.fields['action'].choices = self.action_choices


class ErrorDetailSerializer(serializers.Serializer):
    """Serializer for API error responses."""

    detail = serializers.CharField(help_text="Human-readable error message")
    code = serializers.CharField(help_text="Machine-readable error code")
    field = serializers.CharField(required=False, help_text="Field that caused the error")


class PaginationInfoSerializer(serializers.Serializer):
    """Serializer for pagination metadata."""

    count = serializers.IntegerField(help_text="Total number of items")
    next = serializers.URLField(required=False, help_text="URL for next page")
    previous = serializers.URLField(required=False, help_text="URL for previous page")
    page_size = serializers.IntegerField(help_text="Number of items per page")
    current_page = serializers.IntegerField(help_text="Current page number")
    total_pages = serializers.IntegerField(help_text="Total number of pages")
