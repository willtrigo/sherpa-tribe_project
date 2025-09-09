from django.db import models
from django.db.models import Q, Count, Avg, Sum, Case, When, Value, IntegerField
from django.utils import timezone
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank

from apps.common.managers import SoftDeleteManager


class TaskQuerySet(models.QuerySet):
    """Custom QuerySet for Task model with advanced filtering and optimization."""
    
    def active(self):
        """Filter active (non-deleted) tasks."""
        return self.filter(is_deleted=False)
    
    def by_status(self, status):
        """Filter tasks by status."""
        return self.filter(status=status)
    
    def by_priority(self, priority):
        """Filter tasks by priority."""
        return self.filter(priority=priority)
    
    def by_assignee(self, user):
        """Filter tasks assigned to a specific user."""
        return self.filter(assigned_to=user)
    
    def created_by_user(self, user):
        """Filter tasks created by a specific user."""
        return self.filter(created_by=user)
    
    def overdue(self):
        """Filter overdue tasks."""
        return self.filter(
            due_date__lt=timezone.now(),
            status__in=['todo', 'in_progress', 'in_review']
        )
    
    def due_soon(self, hours=24):
        """Filter tasks due within specified hours."""
        cutoff = timezone.now() + timezone.timedelta(hours=hours)
        return self.filter(
            due_date__lte=cutoff,
            due_date__gte=timezone.now(),
            status__in=['todo', 'in_progress', 'in_review']
        )
    
    def high_priority(self):
        """Filter high priority tasks."""
        return self.filter(priority__in=['high', 'critical'])
    
    def with_tags(self, tag_names):
        """Filter tasks that have any of the specified tags."""
        return self.filter(tags__name__in=tag_names).distinct()
    
    def without_assignee(self):
        """Filter tasks without assignees."""
        return self.filter(assigned_to__isnull=True)
    
    def with_subtasks(self):
        """Filter tasks that have subtasks."""
        return self.filter(subtasks__isnull=False).distinct()
    
    def root_tasks(self):
        """Filter root tasks (tasks without parent)."""
        return self.filter(parent_task__isnull=True)
    
    def subtasks_of(self, parent_task):
        """Filter subtasks of a specific parent task."""
        return self.filter(parent_task=parent_task)
    
    def in_progress_range(self, start_date, end_date):
        """Filter tasks in progress within date range."""
        return self.filter(
            status='in_progress',
            created_at__range=[start_date, end_date]
        )
    
    def completed_in_range(self, start_date, end_date):
        """Filter tasks completed within date range."""
        return self.filter(
            status='done',
            updated_at__range=[start_date, end_date]
        )
    
    def search(self, query):
        """Full-text search on tasks."""
        if not query:
            return self
        
        search_query = SearchQuery(query)
        search_vector = SearchVector('title', weight='A') + SearchVector('description', weight='B')
        
        return self.annotate(
            search=search_vector,
            rank=SearchRank(search_vector, search_query)
        ).filter(search=search_query).order_by('-rank')
    
    def with_related(self):
        """Optimize queries by selecting related objects."""
        return self.select_related(
            'created_by',
            'parent_task',
            'parent_task__created_by'
        ).prefetch_related(
            'assigned_to',
            'tags',
            'comments',
            'subtasks',
            'assignments__user'
        )
    
    def with_assignments(self):
        """Include active assignments."""
        return self.prefetch_related(
            models.Prefetch(
                'assignments',
                queryset=self.model.assignments.related.related_model.objects.filter(is_active=True)
            )
        )
    
    def with_statistics(self):
        """Annotate tasks with useful statistics."""
        return self.annotate(
            subtask_count=Count('subtasks', filter=Q(subtasks__is_deleted=False)),
            completed_subtask_count=Count(
                'subtasks',
                filter=Q(subtasks__is_deleted=False, subtasks__status='done')
            ),
            comment_count=Count('comments', filter=Q(comments__is_deleted=False)),
            assignee_count=Count('assigned_to', distinct=True),
            days_until_due=Case(
                When(due_date__gte=timezone.now(), then=(models.F('due_date') - timezone.now())),
                default=Value(0),
                output_field=models.DurationField()
            )
        )
    
    def performance_metrics(self):
        """Calculate performance metrics."""
        return self.aggregate(
            total_tasks=Count('id'),
            avg_estimated_hours=Avg('estimated_hours'),
            avg_actual_hours=Avg('actual_hours'),
            total_estimated_hours=Sum('estimated_hours'),
            total_actual_hours=Sum('actual_hours'),
            completed_tasks=Count('id', filter=Q(status='done')),
            overdue_tasks=Count('id', filter=Q(
                due_date__lt=timezone.now(),
                status__in=['todo', 'in_progress', 'in_review']
            ))
        )
    
    def by_team_members(self, team):
        """Filter tasks assigned to team members."""
        team_member_ids = team.members.values_list('id', flat=True)
        return self.filter(assigned_to__in=team_member_ids).distinct()
    
    def recent(self, days=7):
        """Filter recently created tasks."""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff_date)
    
    def updated_recently(self, days=7):
        """Filter recently updated tasks."""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(updated_at__gte=cutoff_date)


class TaskManager(SoftDeleteManager):
    """Custom manager for Task model."""
    
    def get_queryset(self):
        """Return custom QuerySet."""
        return TaskQuerySet(self.model, using=self._db)
    
    def active(self):
        """Get active tasks."""
        return self.get_queryset().active()
    
    def by_status(self, status):
        """Get tasks by status."""
        return self.get_queryset().by_status(status)
    
    def overdue(self):
        """Get overdue tasks."""
        return self.get_queryset().overdue()
    
    def due_soon(self, hours=24):
        """Get tasks due soon."""
        return self.get_queryset().due_soon(hours)
    
    def high_priority(self):
        """Get high priority tasks."""
        return self.get_queryset().high_priority()
    
    def search(self, query):
        """Search tasks."""
        return self.get_queryset().search(query)
    
    def with_related(self):
        """Get tasks with related objects."""
        return self.get_queryset().with_related()
    
    def performance_metrics(self):
        """Get performance metrics."""
        return self.get_queryset().performance_metrics()
    
    def create_from_template(self, template, variables=None, **kwargs):
        """Create task from template with variable substitution."""
        variables = variables or {}
        
        # Substitute variables in template
        title = self._substitute_variables(template.title_template, variables)
        description = self._substitute_variables(template.description_template, variables)
        
        # Create task with template defaults
        task_data = {
            'title': title,
            'description': description,
            'priority': template.default_priority,
            'estimated_hours': template.default_estimated_hours,
            **kwargs
        }
        
        task = self.create(**task_data)
        
        # Add default tags
        if template.default_tags.exists():
            task.tags.set(template.default_tags.all())
        
        return task
    
    def _substitute_variables(self, template_string, variables):
        """Substitute variables in template string."""
        for key, value in variables.items():
            placeholder = f"{{{key}}}"
            template_string = template_string.replace(placeholder, str(value))
        return template_string
    
    def bulk_update_status(self, task_ids, status, user):
        """Bulk update task status."""
        tasks = self.filter(id__in=task_ids)
        tasks.update(status=status, updated_at=timezone.now())
        
        # Create history entries
        from apps.tasks.models import TaskHistory
        history_entries = []
        for task in tasks:
            history_entries.append(
                TaskHistory(
                    task=task,
                    user=user,
                    action='status_changed',
                    field_name='status',
                    new_value=status
                )
            )
        TaskHistory.objects.bulk_create(history_entries)
        
        return tasks.count()
    
    def get_workload_distribution(self, users):
        """Get workload distribution for users."""
        return self.get_queryset().filter(
            assigned_to__in=users,
            status__in=['todo', 'in_progress']
        ).values('assigned_to__username').annotate(
            task_count=Count('id'),
            total_estimated_hours=Sum('estimated_hours'),
            high_priority_count=Count('id', filter=Q(priority__in=['high', 'critical']))
        ).order_by('-task_count')


class ActiveTaskManager(TaskManager):
    """Manager for active (non-deleted) tasks only."""
    
    def get_queryset(self):
        """Return only active tasks."""
        return super().get_queryset().active()


class CommentQuerySet(models.QuerySet):
    """Custom QuerySet for Comment model."""
    
    def active(self):
        """Filter active (non-deleted) comments."""
        return self.filter(is_deleted=False)
    
    def for_task(self, task):
        """Filter comments for a specific task."""
        return self.filter(task=task)
    
    def by_author(self, user):
        """Filter comments by author."""
        return self.filter(author=user)
    
    def top_level(self):
        """Filter top-level comments (not replies)."""
        return self.filter(parent_comment__isnull=True)
    
    def replies(self):
        """Filter reply comments."""
        return self.filter(parent_comment__isnull=False)
    
    def public(self):
        """Filter public comments."""
        return self.filter(is_internal=False)
    
    def internal(self):
        """Filter internal comments."""
        return self.filter(is_internal=True)
    
    def recent(self, days=7):
        """Filter recent comments."""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff_date)
    
    def with_replies(self):
        """Include replies in prefetch."""
        return self.prefetch_related('replies')
    
    def thread_order(self):
        """Order comments for thread display."""
        return self.order_by('created_at')


class CommentManager(SoftDeleteManager):
    """Custom manager for Comment model."""
    
    def get_queryset(self):
        """Return custom QuerySet."""
        return CommentQuerySet(self.model, using=self._db)
    
    def active(self):
        """Get active comments."""
        return self.get_queryset().active()
    
    def for_task(self, task):
        """Get comments for task."""
        return self.get_queryset().for_task(task)
    
    def public(self):
        """Get public comments."""
        return self.get_queryset().public()


class TaskHistoryQuerySet(models.QuerySet):
    """Custom QuerySet for TaskHistory model."""
    
    def for_task(self, task):
        """Filter history for a specific task."""
        return self.filter(task=task)
    
    def by_user(self, user):
        """Filter history by user."""
        return self.filter(user=user)
    
    def by_action(self, action):
        """Filter history by action type."""
        return self.filter(action=action)
    
    def recent(self, days=30):
        """Filter recent history entries."""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff_date)
    
    def field_changes(self, field_name):
        """Filter history entries for specific field changes."""
        return self.filter(field_name=field_name)
    
    def status_changes(self):
        """Filter status change history entries."""
        return self.filter(action='status_changed')
    
    def assignment_changes(self):
        """Filter assignment change history entries."""
        return self.filter(action__in=['assigned', 'unassigned'])


class TaskHistoryManager(models.Manager):
    """Custom manager for TaskHistory model."""
    
    def get_queryset(self):
        """Return custom QuerySet."""
        return TaskHistoryQuerySet(self.model, using=self._db)
    
    def for_task(self, task):
        """Get history for task."""
        return self.get_queryset().for_task(task)
    
    def recent(self, days=30):
        """Get recent history."""
        return self.get_queryset().recent(days)
    
    def create_entry(self, task, user, action, field_name=None, old_value=None, new_value=None, **kwargs):
        """Create a history entry."""
        return self.create(
            task=task,
            user=user,
            action=action,
            field_name=field_name or '',
            old_value=old_value or '',
            new_value=new_value or '',
            **kwargs
        )


class TeamQuerySet(models.QuerySet):
    """Custom QuerySet for Team model."""
    
    def active(self):
        """Filter active teams."""
        return self.filter(is_active=True, is_deleted=False)
    
    def with_member(self, user):
        """Filter teams that include a specific member."""
        return self.filter(members=user)
    
    def led_by(self, user):
        """Filter teams led by a specific user."""
        return self.filter(lead=user)
    
    def with_members(self):
        """Prefetch team members."""
        return self.prefetch_related('members', 'teammembership_set')
    
    def with_stats(self):
        """Annotate teams with statistics."""
        return self.annotate(
            member_count=Count('members', distinct=True),
            active_member_count=Count(
                'teammembership',
                filter=Q(teammembership__is_active=True),
                distinct=True
            )
        )


class TeamManager(SoftDeleteManager):
    """Custom manager for Team model."""
    
    def get_queryset(self):
        """Return custom QuerySet."""
        return TeamQuerySet(self.model, using=self._db)
    
    def active(self):
        """Get active teams."""
        return self.get_queryset().active()
    
    def with_member(self, user):
        """Get teams with specific member."""
        return self.get_queryset().with_member(user)
    
    def with_stats(self):
        """Get teams with statistics."""
        return self.get_queryset().with_stats()
