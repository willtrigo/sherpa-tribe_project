"""
Advanced filtering system for Task model with comprehensive query optimization.

This module provides a robust filtering framework using django-filter with
performance optimizations, complex query handling, and search capabilities.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import django_filters
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramSimilarity,
)
from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    Q,
    QuerySet,
    Value,
    When,
)
from django.db.models.functions import Greatest
from django.utils import timezone
from django_filters import rest_framework as filters

from apps.tasks.choices import (
    PRIORITY_CHOICES,
    STATUS_CHOICES,
)
from apps.tasks.models import Task, Tag


class TaskFilterSet(filters.FilterSet):
    """
    Advanced filterset for Task model with optimized database queries.
    
    Provides comprehensive filtering capabilities including:
    - Status and priority filtering
    - Date range filtering with timezone awareness
    - Full-text search with ranking
    - User and team-based filtering
    - Performance-optimized queries with prefetch_related
    """

    # Basic field filters with exact and multiple choice support
    status = filters.MultipleChoiceFilter(
        choices=STATUS_CHOICES,
        field_name="status",
        lookup_expr="in",
        help_text="Filter by task status. Supports multiple values.",
    )
    
    priority = filters.MultipleChoiceFilter(
        choices=PRIORITY_CHOICES,
        field_name="priority",
        lookup_expr="in",
        help_text="Filter by task priority. Supports multiple values.",
    )

    # Date range filters with timezone awareness
    due_date_after = filters.DateTimeFilter(
        field_name="due_date",
        lookup_expr="gte",
        help_text="Filter tasks due after this date (inclusive).",
    )
    
    due_date_before = filters.DateTimeFilter(
        field_name="due_date",
        lookup_expr="lte",
        help_text="Filter tasks due before this date (inclusive).",
    )
    
    created_after = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
        help_text="Filter tasks created after this date (inclusive).",
    )
    
    created_before = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
        help_text="Filter tasks created before this date (inclusive).",
    )
    
    updated_after = filters.DateTimeFilter(
        field_name="updated_at",
        lookup_expr="gte",
        help_text="Filter tasks updated after this date (inclusive).",
    )
    
    updated_before = filters.DateTimeFilter(
        field_name="updated_at",
        lookup_expr="lte",
        help_text="Filter tasks updated before this date (inclusive).",
    )

    # User-related filters with multiple selection support
    created_by = filters.ModelMultipleChoiceFilter(
        field_name="created_by",
        queryset=None,  # Will be set in __init__
        help_text="Filter by task creator. Supports multiple users.",
    )
    
    assigned_to = filters.ModelMultipleChoiceFilter(
        field_name="assigned_to",
        queryset=None,  # Will be set in __init__
        help_text="Filter by assigned users. Supports multiple users.",
    )

    # Tag filtering with multiple selection
    tags = filters.ModelMultipleChoiceFilter(
        field_name="tags",
        queryset=Tag.objects.all(),
        help_text="Filter by tags. Supports multiple tags.",
    )
    
    tags_all = filters.ModelMultipleChoiceFilter(
        field_name="tags",
        queryset=Tag.objects.all(),
        method="filter_tags_all",
        help_text="Filter tasks that have ALL specified tags.",
    )

    # Numeric range filters
    estimated_hours_min = filters.NumberFilter(
        field_name="estimated_hours",
        lookup_expr="gte",
        help_text="Minimum estimated hours.",
    )
    
    estimated_hours_max = filters.NumberFilter(
        field_name="estimated_hours",
        lookup_expr="lte",
        help_text="Maximum estimated hours.",
    )
    
    actual_hours_min = filters.NumberFilter(
        field_name="actual_hours",
        lookup_expr="gte",
        help_text="Minimum actual hours.",
    )
    
    actual_hours_max = filters.NumberFilter(
        field_name="actual_hours",
        lookup_expr="lte",
        help_text="Maximum actual hours.",
    )

    # Advanced filters
    is_overdue = filters.BooleanFilter(
        method="filter_overdue",
        help_text="Filter overdue tasks (due_date < now).",
    )
    
    has_subtasks = filters.BooleanFilter(
        method="filter_has_subtasks",
        help_text="Filter tasks that have subtasks.",
    )
    
    is_subtask = filters.BooleanFilter(
        field_name="parent_task__isnull",
        lookup_expr="exact",
        exclude=True,
        help_text="Filter tasks that are subtasks.",
    )
    
    is_archived = filters.BooleanFilter(
        field_name="is_archived",
        help_text="Filter archived/unarchived tasks.",
    )

    # Full-text search with PostgreSQL features
    search = filters.CharFilter(
        method="filter_search",
        help_text="Full-text search in title, description, and comments.",
    )

    # Ordering filter with comprehensive options
    ordering = filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("due_date", "due_date"),
            ("priority", "priority"),
            ("status", "status"),
            ("title", "title"),
            ("estimated_hours", "estimated_hours"),
            ("actual_hours", "actual_hours"),
        ),
        field_labels={
            "created_at": "Creation Date",
            "updated_at": "Last Updated",
            "due_date": "Due Date",
            "priority": "Priority",
            "status": "Status",
            "title": "Title",
            "estimated_hours": "Estimated Hours",
            "actual_hours": "Actual Hours",
        },
        help_text="Order results by specified field. Use '-' prefix for descending order.",
    )

    class Meta:
        model = Task
        fields = {
            "title": ["icontains", "exact"],
            "description": ["icontains"],
            "metadata": ["has_key", "has_keys"],
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize filterset with optimized user querysets."""
        super().__init__(*args, **kwargs)
        
        # Optimize user querysets to reduce database hits
        from apps.users.models import User
        
        user_queryset = User.objects.select_related().only(
            "id", "username", "first_name", "last_name", "email"
        )
        
        self.filters["created_by"].queryset = user_queryset
        self.filters["assigned_to"].queryset = user_queryset

    def filter_overdue(
        self, queryset: QuerySet[Task], name: str, value: bool
    ) -> QuerySet[Task]:
        """Filter tasks based on overdue status with timezone awareness."""
        if value is None:
            return queryset
            
        now = timezone.now()
        
        if value:
            return queryset.filter(
                due_date__lt=now,
                status__in=["TODO", "IN_PROGRESS", "REVIEW"],
            )
        else:
            return queryset.exclude(
                due_date__lt=now,
                status__in=["TODO", "IN_PROGRESS", "REVIEW"],
            )

    def filter_has_subtasks(
        self, queryset: QuerySet[Task], name: str, value: bool
    ) -> QuerySet[Task]:
        """Filter tasks based on whether they have subtasks."""
        if value is None:
            return queryset
            
        subtask_annotation = Count("subtasks")
        queryset = queryset.annotate(subtask_count=subtask_annotation)
        
        if value:
            return queryset.filter(subtask_count__gt=0)
        else:
            return queryset.filter(subtask_count=0)

    def filter_tags_all(
        self, queryset: QuerySet[Task], name: str, value: List[Tag]
    ) -> QuerySet[Task]:
        """Filter tasks that have ALL specified tags."""
        if not value:
            return queryset
            
        for tag in value:
            queryset = queryset.filter(tags=tag)
            
        return queryset

    def filter_search(
        self, queryset: QuerySet[Task], name: str, value: str
    ) -> QuerySet[Task]:
        """
        Advanced full-text search with ranking and trigram similarity.
        
        Uses PostgreSQL's full-text search capabilities with ranking
        and trigram similarity for fuzzy matching.
        """
        if not value:
            return queryset

        # Create search vector for full-text search
        search_vector = (
            SearchVector("title", weight="A") +
            SearchVector("description", weight="B") +
            SearchVector("comments__content", weight="C")
        )
        
        # Create search query
        search_query = SearchQuery(value)
        
        # Calculate trigram similarity for fuzzy matching
        title_similarity = TrigramSimilarity("title", value)
        description_similarity = TrigramSimilarity("description", value)
        
        # Combine search methods with ranking
        queryset = (
            queryset.annotate(
                search=search_vector,
                rank=SearchRank(search_vector, search_query),
                title_sim=title_similarity,
                desc_sim=description_similarity,
                combined_rank=Greatest(
                    "rank",
                    "title_sim",
                    "desc_sim",
                    output_field=DecimalField(max_digits=10, decimal_places=6),
                ),
            )
            .filter(
                Q(search=search_query) |
                Q(title_sim__gt=0.3) |
                Q(desc_sim__gt=0.2)
            )
            .order_by("-combined_rank", "-updated_at")
            .distinct()
        )
        
        return queryset

    @property
    def qs(self) -> QuerySet[Task]:
        """
        Optimized queryset with select_related and prefetch_related.
        
        Returns queryset with optimized database access patterns
        to minimize N+1 queries.
        """
        queryset = super().qs
        
        # Apply performance optimizations
        queryset = queryset.select_related(
            "created_by",
            "parent_task",
            "parent_task__created_by",
        ).prefetch_related(
            "assigned_to",
            "tags",
            "comments",
            "comments__author",
            "subtasks",
            "subtasks__assigned_to",
        )
        
        # Add computed fields for efficient filtering
        queryset = queryset.annotate(
            is_overdue_computed=Case(
                When(
                    due_date__lt=timezone.now(),
                    status__in=["TODO", "IN_PROGRESS", "REVIEW"],
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
            subtask_count=Count("subtasks"),
            comment_count=Count("comments"),
            assignee_count=Count("assigned_to"),
        )
        
        return queryset


class MyTasksFilterSet(TaskFilterSet):
    """
    Specialized filterset for user's personal tasks.
    
    Extends TaskFilterSet with user-specific filtering capabilities
    for dashboard and personal task management views.
    """

    involvement = filters.ChoiceFilter(
        choices=(
            ("created", "Tasks I Created"),
            ("assigned", "Tasks Assigned to Me"),
            ("all", "All My Tasks"),
        ),
        method="filter_involvement",
        help_text="Filter by user involvement type.",
    )

    def filter_involvement(
        self, queryset: QuerySet[Task], name: str, value: str
    ) -> QuerySet[Task]:
        """Filter tasks based on user involvement type."""
        if not hasattr(self.request, "user") or not value:
            return queryset
            
        user = self.request.user
        
        if value == "created":
            return queryset.filter(created_by=user)
        elif value == "assigned":
            return queryset.filter(assigned_to=user)
        elif value == "all":
            return queryset.filter(
                Q(created_by=user) | Q(assigned_to=user)
            ).distinct()
            
        return queryset


class TeamTasksFilterSet(TaskFilterSet):
    """
    Specialized filterset for team-based task filtering.
    
    Extends TaskFilterSet with team-specific capabilities for
    team dashboard and project management views.
    """

    team = filters.ModelChoiceFilter(
        queryset=None,  # Will be set in __init__
        method="filter_team",
        help_text="Filter tasks by team membership.",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with team-specific querysets."""
        super().__init__(*args, **kwargs)
        
        if hasattr(self.request, "user"):
            from apps.users.models import Team
            
            # Only show teams the user belongs to
            self.filters["team"].queryset = Team.objects.filter(
                members=self.request.user
            )

    def filter_team(
        self, queryset: QuerySet[Task], name: str, value: Any
    ) -> QuerySet[Task]:
        """Filter tasks by team membership."""
        if not value:
            return queryset
            
        return queryset.filter(
            Q(created_by__teams=value) |
            Q(assigned_to__teams=value)
        ).distinct()


# Export all filtersets for easy importing
__all__ = [
    "TaskFilterSet",
    "MyTasksFilterSet", 
    "TeamTasksFilterSet",
]
