from django.contrib.auth.models import UserManager
from django.db import models


class CustomUserManager(UserManager):
    """
    Custom manager for the User model with additional methods.
    """

    def get_queryset(self):
        """Return queryset excluding soft-deleted users."""
        return super().get_queryset().filter(is_deleted=False)

    def active(self):
        """Return only active users."""
        return self.get_queryset().filter(status='active', is_active=True)

    def by_role(self, role):
        """Filter users by role."""
        return self.get_queryset().filter(role=role)

    def managers(self):
        """Return users with manager role or above."""
        return self.get_queryset().filter(
            role__in=['admin', 'manager']
        )

    def available_for_assignment(self):
        """Return users available for task assignment."""
        return self.active().annotate(
            active_tasks_count=models.Count(
                'assigned_tasks',
                filter=models.Q(
                    assigned_tasks__status__in=['todo', 'in_progress'],
                    assigned_tasks__is_archived=False
                )
            )
        ).filter(
            active_tasks_count__lt=models.F('max_concurrent_tasks')
        )

    def with_workload(self):
        """Return users with their current workload."""
        return self.get_queryset().annotate(
            active_tasks_count=models.Count(
                'assigned_tasks',
                filter=models.Q(
                    assigned_tasks__status__in=['todo', 'in_progress'],
                    assigned_tasks__is_archived=False
                )
            ),
            workload_percentage=models.Case(
                models.When(
                    max_concurrent_tasks=0,
                    then=models.Value(100.0)
                ),
                default=models.F('active_tasks_count') * 100.0 / models.F('max_concurrent_tasks'),
                output_field=models.FloatField()
            )
        )


class TeamManager(models.Manager):
    """
    Custom manager for the Team model.
    """

    def get_queryset(self):
        """Return queryset excluding soft-deleted teams."""
        return super().get_queryset().filter(is_deleted=False)

    def active(self):
        """Return only active teams."""
        return self.get_queryset().filter(is_active=True)

    def with_member_count(self):
        """Return teams with member count."""
        return self.get_queryset().annotate(
            member_count=models.Count(
                'members',
                filter=models.Q(members__is_active=True)
            )
        )

    def by_type(self, team_type):
        """Filter teams by type."""
        return self.get_queryset().filter(team_type=team_type)
