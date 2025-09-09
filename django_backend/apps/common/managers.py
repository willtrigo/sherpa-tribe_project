"""
Custom model managers for common functionality.

Provides managers for soft deletion, timestamps, and other common patterns.
"""

from typing import Any, Dict, Optional

from django.db import models
from django.db.models import QuerySet
from django.utils import timezone


class SoftDeleteQuerySet(QuerySet):
    """QuerySet that excludes soft deleted objects by default."""

    def delete(self) -> tuple[int, Dict[str, int]]:
        """Soft delete all objects in this queryset."""
        return self.update(
            is_deleted=True,
            deleted_at=timezone.now()
        )

    def hard_delete(self) -> tuple[int, Dict[str, int]]:
        """Permanently delete all objects in this queryset."""
        return super().delete()

    def alive(self) -> QuerySet:
        """Return only non-deleted objects."""
        return self.filter(is_deleted=False)

    def deleted(self) -> QuerySet:
        """Return only soft-deleted objects."""
        return self.filter(is_deleted=True)

    def with_deleted(self) -> QuerySet:
        """Return all objects including soft-deleted ones."""
        return self.all()


class SoftDeleteManager(models.Manager):
    """Manager that excludes soft deleted objects by default."""

    def get_queryset(self) -> QuerySet:
        """Return queryset excluding soft deleted objects."""
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def with_deleted(self) -> QuerySet:
        """Return queryset including soft deleted objects."""
        return SoftDeleteQuerySet(self.model, using=self._db).with_deleted()

    def deleted_only(self) -> QuerySet:
        """Return queryset with only soft deleted objects."""
        return SoftDeleteQuerySet(self.model, using=self._db).deleted()


class TimestampedQuerySet(QuerySet):
    """QuerySet with timestamp-related utilities."""

    def created_before(self, date: timezone.datetime) -> QuerySet:
        """Filter objects created before the given date."""
        return self.filter(created_at__lt=date)

    def created_after(self, date: timezone.datetime) -> QuerySet:
        """Filter objects created after the given date."""
        return self.filter(created_at__gt=date)

    def created_between(
        self, 
        start_date: timezone.datetime, 
        end_date: timezone.datetime
    ) -> QuerySet:
        """Filter objects created between two dates."""
        return self.filter(created_at__range=(start_date, end_date))

    def updated_since(self, date: timezone.datetime) -> QuerySet:
        """Filter objects updated since the given date."""
        return self.filter(updated_at__gt=date)

    def recent(self, days: int = 7) -> QuerySet:
        """Filter objects created in the last N days."""
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff)


class TimestampedManager(models.Manager):
    """Manager with timestamp-related query methods."""

    def get_queryset(self) -> QuerySet:
        """Return timestamped queryset."""
        return TimestampedQuerySet(self.model, using=self._db)

    def created_before(self, date: timezone.datetime) -> QuerySet:
        """Filter objects created before the given date."""
        return self.get_queryset().created_before(date)

    def created_after(self, date: timezone.datetime) -> QuerySet:
        """Filter objects created after the given date."""
        return self.get_queryset().created_after(date)

    def created_between(
        self, 
        start_date: timezone.datetime, 
        end_date: timezone.datetime
    ) -> QuerySet:
        """Filter objects created between two dates."""
        return self.get_queryset().created_between(start_date, end_date)

    def recent(self, days: int = 7) -> QuerySet:
        """Filter objects created in the last N days."""
        return self.get_queryset().recent(days)


class ArchivableQuerySet(QuerySet):
    """QuerySet for archivable objects."""

    def active(self) -> QuerySet:
        """Return only non-archived objects."""
        return self.filter(is_archived=False)

    def archived(self) -> QuerySet:
        """Return only archived objects."""
        return self.filter(is_archived=True)

    def archive_all(self, user=None) -> int:
        """Archive all objects in this queryset."""
        update_fields = {
            'is_archived': True,
            'archived_at': timezone.now()
        }
        if user:
            update_fields['archived_by'] = user

        return self.update(**update_fields)


class ArchivableManager(models.Manager):
    """Manager for archivable objects that excludes archived by default."""

    def get_queryset(self) -> QuerySet:
        """Return queryset excluding archived objects."""
        return ArchivableQuerySet(self.model, using=self._db).active()

    def archived(self) -> QuerySet:
        """Return queryset with only archived objects."""
        return ArchivableQuerySet(self.model, using=self._db).archived()

    def with_archived(self) -> QuerySet:
        """Return queryset including archived objects."""
        return ArchivableQuerySet(self.model, using=self._db).all()


class BaseModelManager(SoftDeleteManager, TimestampedManager):
    """
    Combined manager that provides both soft delete and timestamp functionality.

    This manager should be used with models that inherit from BaseModel.
    """

    def get_queryset(self) -> QuerySet:
        """Return queryset that combines soft delete and timestamp functionality."""
        # Create a combined QuerySet class dynamically
        class CombinedQuerySet(SoftDeleteQuerySet, TimestampedQuerySet):
            pass

        return CombinedQuerySet(self.model, using=self._db).alive()


class ActiveManager(models.Manager):
    """Manager that filters for active (non-deleted, non-archived) objects."""

    def get_queryset(self) -> QuerySet:
        """Return queryset with only active objects."""
        queryset = super().get_queryset()

        # Apply soft delete filter if the model supports it
        if hasattr(self.model, 'is_deleted'):
            queryset = queryset.filter(is_deleted=False)

        # Apply archive filter if the model supports it
        if hasattr(self.model, 'is_archived'):
            queryset = queryset.filter(is_archived=False)

        return queryset
