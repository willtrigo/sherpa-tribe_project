"""
Common abstract models and mixins for the task management system.

Provides base models with common functionality like timestamps,
soft deletion, and metadata handling.
"""

import uuid
from typing import Any, Dict

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.conf import settings

from .managers import SoftDeleteManager, TimestampedManager


class UUIDMixin(models.Model):
    """Mixin to provide UUID primary key."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this record"
    )

    class Meta:
        abstract = True


class TimestampMixin(models.Model):
    """Mixin to provide creation and modification timestamps."""

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When this record was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_index=True,
        help_text="When this record was last modified"
    )

    objects = TimestampedManager()

    class Meta:
        abstract = True
        ordering = ['-created_at']


class SoftDeleteMixin(models.Model):
    """Mixin to provide soft deletion functionality."""

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this record has been soft deleted"
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When this record was soft deleted"
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_%(class)s_set",
        help_text="User who soft deleted this record"
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()  # Manager that includes deleted objects

    class Meta:
        abstract = True

    def soft_delete(self, user=None) -> None:
        """Soft delete this instance."""
        if user and not isinstance(user, get_user_model()):
            raise ValueError("user must be an instance of User model")
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user:
            self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self) -> None:
        """Restore a soft deleted instance."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])


class MetadataMixin(models.Model):
    """Mixin to provide JSON metadata field with helper methods."""

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata for this record"
    )

    class Meta:
        abstract = True

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get a metadata value by key."""
        return self.metadata.get(key, default)

    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata value by key."""
        self.metadata[key] = value

    def update_metadata(self, data: Dict[str, Any]) -> None:
        """Update metadata with a dictionary of values."""
        self.metadata.update(data)

    def delete_metadata(self, key: str) -> bool:
        """Delete a metadata key. Returns True if key existed."""
        if key in self.metadata:
            del self.metadata[key]
            return True
        return False


class AuditMixin(models.Model):
    """Mixin to track who created and last modified a record."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_%(class)s_set",
        help_text="User who created this record"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_%(class)s_set",
        help_text="User who last updated this record"
    )

    class Meta:
        abstract = True


class BaseModel(
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    MetadataMixin,
    AuditMixin
):
    """
    Base model that combines all common mixins.

    Provides:
    - UUID primary key
    - Created/updated timestamps
    - Soft deletion
    - JSON metadata field
    - Audit trail (created_by, updated_by)
    """

    class Meta:
        abstract = True


class VersionedMixin(models.Model):
    """Mixin to provide simple versioning functionality."""

    version = models.PositiveIntegerField(
        default=1,
        help_text="Version number of this record"
    )

    class Meta:
        abstract = True

    def increment_version(self) -> None:
        """Increment the version number."""
        self.version += 1


class ArchivableMixin(models.Model):
    """Mixin to provide archiving functionality."""

    is_archived = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this record is archived"
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this record was archived"
    )
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_%(class)s_set",
        help_text="User who archived this record"
    )

    class Meta:
        abstract = True

    def archive(self, user=None) -> None:
        """Archive this instance."""
        if user and not isinstance(user, get_user_model()):
            raise ValueError("user must be an instance of User model")
        self.is_archived = True
        self.archived_at = timezone.now()
        if user:
            self.archived_by = user
        self.save(update_fields=['is_archived', 'archived_at', 'archived_by'])

    def unarchive(self) -> None:
        """Unarchive this instance."""
        self.is_archived = False
        self.archived_at = None
        self.archived_by = None
        self.save(update_fields=['is_archived', 'archived_at', 'archived_by'])
