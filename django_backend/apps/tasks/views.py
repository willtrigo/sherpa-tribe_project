from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db import transaction

from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend

from apps.tasks.models import Task, Comment, TaskHistory, Tag, TaskAssignment, Team, TaskTemplate
from apps.tasks.serializers import (
    TaskListSerializer, TaskDetailSerializer, TaskCreateSerializer,
    CommentSerializer, TaskHistorySerializer, TagSerializer,
    TaskAssignmentSerializer, TaskAssignmentCreateSerializer,
    TeamSerializer, TaskTemplateSerializer
)
from apps.tasks.filters import TaskFilter
from apps.tasks.forms import TaskForm, TaskCreateForm, CommentForm
from apps.tasks.permissions import TaskPermission, CanEditTask
from apps.common.permissions import IsOwnerOrReadOnly
from apps.common.mixins import MultiplePermissionsRequiredMixin


# ===============================
# DJANGO TEMPLATE VIEWS (Frontend)
# ===============================

@login_required
def dashboard_view(request):
    """Dashboard view showing task overview."""
    context = {
        'total_tasks': Task.objects.filter(created_by=request.user).count(),
        'pending_tasks': Task.objects.filter(
            assigned_to=request.user, 
            status__in=['todo', 'in_progress']
        ).count(),
        'overdue_tasks': Task.objects.filter(
            assigned_to=request.user
        ).overdue().count(),
        'completed_today': Task.objects.filter(
            assigned_to=request.user,
            status='done',
            updated_at__date=timezone.now().date()
        ).count()
    }
    return render(request, 'common/dashboard.html', context)


class TaskListView(LoginRequiredMixin, ListView):
    """Class-based view for task list with Django templates."""
    
    model = Task
    template_name = 'tasks/task_list.html'
    context_object_name = 'tasks'
    paginate_by = 20
    
    def get_queryset(self):
        """Get filtered and optimized queryset."""
        queryset = Task.objects.active().with_related().with_statistics()
        
        # Filter by user's tasks (created or assigned)
        user = self.request.user
        queryset = queryset.filter(
            Q(created_by=user) | Q(assigned_to=user)
        ).distinct()
        
        # Apply filters
        status_filter = self.request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        priority_filter = self.request.GET.get('priority')
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)
        
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.search(search_query)
        
        # Default ordering
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        """Add additional context."""
        context = super().get_context_data(**kwargs)
        from apps.tasks.choices import TaskStatus, TaskPriority
        
        context.update({
            'status_choices': TaskStatus.choices,
            'priority_choices': TaskPriority.choices,
            'current_status': self.request.GET.get('status', ''),
            'current_priority': self.request.GET.get('priority', ''),
            'current_search': self.request.GET.get('search', ''),
            'tags': Tag.objects.all()[:20]  # Popular tags
        })
        return context


class TaskDetailView(LoginRequiredMixin, DetailView):
    """Class-based view for task detail with Django templates."""
    
    model = Task
    template_name = 'tasks/task_detail.html'
    context_object_name = 'task'
    
    def get_queryset(self):
        """Get optimized queryset with related objects."""
        return Task.objects.active().with_related().select_related(
            'parent_task'
        ).prefetch_related(
            'comments__author',
            'history__user',
            Prefetch(
                'subtasks',
                queryset=Task.objects.filter(is_deleted=False).select_related('created_by')
            )
        )
    
    def get_context_data(self, **kwargs):
        """Add additional context."""
        context = super().get_context_data(**kwargs)
        task = context['task']
        
        # Check permissions
        can_edit = (
            task.created_by == self.request.user or
            task.assigned_to.filter(id=self.request.user.id).exists()
        )
        
        context.update({
            'can_edit': can_edit,
            'comment_form': CommentForm(),
            'comments': task.comments.filter(is_deleted=False, parent_comment=None)
                           .select_related('author').order_by('-created_at'),
            'recent_history': task.history.select_related('user')[:10],
            'subtasks': task.subtasks.filter(is_deleted=False)
                           .select_related('created_by')
        })
        return context


class TaskCreateView(LoginRequiredMixin, CreateView):
    """Class-based view for task creation with Django templates."""
    
    model = Task
    form_class = TaskCreateForm
    template_name = 'tasks/task_create.html'
    success_url = reverse_lazy('tasks:task_list')
    
    def form_valid(self, form):
        """Set the task creator."""
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
        # Handle many-to-many relationships
        if form.cleaned_data.get('tags'):
            self.object.tags.set(form.cleaned_data['tags'])
        
        if form.cleaned_data.get('assignees'):
            # Create assignments
            assignments = []
            for user in form.cleaned_data['assignees']:
                assignments.append(
                    TaskAssignment(
                        task=self.object,
                        user=user,
                        assigned_by=self.request.user
                    )
                )
            TaskAssignment.objects.bulk_create(assignments)
        
        # Create history entry
        TaskHistory.objects.create(
            task=self.object,
            user=self.request.user,
            action='created'
        )
        
        messages.success(self.request, f'Task "{self.object.title}" created successfully.')
        return response
    
    def get_context_data(self, **kwargs):
        """Add additional context."""
        context = super().get_context_data(**kwargs)
        context.update({
            'page_title': 'Create New Task',
            'available_tags': Tag.objects.all(),
        })
        return context


class TaskUpdateView(LoginRequiredMixin, MultiplePermissionsRequiredMixin, UpdateView):
    """Class-based view for task editing with Django templates."""
    
    model = Task
    form_class = TaskForm
    template_name = 'tasks/task_edit.html'
    
    def get_success_url(self):
        """Return to task detail after successful update."""
        return reverse_lazy('tasks:task_detail', kwargs={'pk': self.object.pk})
    
    def check_permissions(self, request):
        """Check if user can edit this task."""
        task = self.get_object()
        return (
            task.created_by == request.user or
            task.assigned_to.filter(id=request.user.id).exists()
        )
    
    def form_valid(self, form):
        """Handle form submission with change tracking."""
        old_instance = Task.objects.get(pk=self.object.pk)
        response = super().form_valid(form)
        
        # Track changes and create history entries
        changes = self._get_changes(old_instance, self.object)
        self._create_history_entries(changes)
        
        messages.success(self.request, f'Task "{self.object.title}" updated successfully.')
        return response
    
    def _get_changes(self, old_obj, new_obj):
        """Get list of changed fields."""
        changes = {}
        tracked_fields = ['title', 'description', 'status', 'priority', 'due_date', 'estimated_hours']
        
        for field in tracked_fields:
            old_value = getattr(old_obj, field)
            new_value = getattr(new_obj, field)
            if old_value != new_value:
                changes[field] = {'old': old_value, 'new': new_value}
        
        return changes
    
    def _create_history_entries(self, changes):
        """Create history entries for changes."""
        for field, change in changes.items():
            TaskHistory.objects.create(
                task=self.object,
                user=self.request.user,
                action=f'{field}_changed',
                field_name=field,
                old_value=str(change['old']),
                new_value=str(change['new'])
            )


@login_required
@require_http_methods(["POST"])
def add_comment_view(request, task_id):
    """AJAX view for adding comments to tasks."""
    task = get_object_or_404(Task, id=task_id, is_deleted=False)
    
    # Check permissions
    if not (task.created_by == request.user or 
            task.assigned_to.filter(id=request.user.id).exists()):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.task = task
        comment.author = request.user
        comment.save()
        
        # Create history entry
        TaskHistory.objects.create(
            task=task,
            user=request.user,
            action='commented'
        )
        
        # Return comment data for AJAX
        return JsonResponse({
            'success': True,
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'author': comment.author.get_full_name() or comment.author.username,
                'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M')
            }
        })
    
    return JsonResponse({'error': 'Invalid form data'}, status=400)


@login_required
@require_http_methods(["POST"])
def assign_task_view(request, task_id):
    """AJAX view for assigning users to tasks."""
    task = get_object_or_404(Task, id=task_id, is_deleted=False)
    
    # Check permissions
    if not (task.created_by == request.user or 
            task.assigned_to.filter(id=request.user.id).exists()):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    user_id = request.POST.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'User ID is required'}, status=400)
    
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)
        
        # Check if already assigned
        if TaskAssignment.objects.filter(task=task, user=user, is_active=True).exists():
            return JsonResponse({'error': 'User is already assigned to this task'}, status=400)
        
        # Create assignment
        assignment = TaskAssignment.objects.create(
            task=task,
            user=user,
            assigned_by=request.user
        )
        
        # Create history entry
        TaskHistory.objects.create(
            task=task,
            user=request.user,
            action='assigned',
            metadata={'assigned_user': user.username}
        )
        
        return JsonResponse({
            'success': True,
            'assignment': {
                'id': assignment.id,
                'user': user.get_full_name() or user.username,
                'assigned_at': assignment.assigned_at.strftime('%Y-%m-%d %H:%M')
            }
        })
    
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)


@login_required
def task_history_view(request, task_id):
    """View for task history (AJAX)."""
    task = get_object_or_404(Task, id=task_id, is_deleted=False)
    
    # Check permissions
    if not (task.created_by == request.user or 
            task.assigned_to.filter(id=request.user.id).exists()):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    history = task.history.select_related('user').order_by('-created_at')[:50]
    
    history_data = []
    for entry in history:
        history_data.append({
            'id': entry.id,
            'action': entry.action,
            'user': entry.user.get_full_name() or entry.user.username,
            'field_name': entry.field_name,
            'old_value': entry.old_value,
            'new_value': entry.new_value,
            'created_at': entry.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return JsonResponse({'history': history_data})


# ===============================
# REST API VIEWS (Backend)
# ===============================

class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for API views."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class TaskViewSet(viewsets.ModelViewSet):
    """ViewSet for Task CRUD operations via REST API."""
    
    permission_classes = [IsAuthenticated, TaskPermission]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TaskFilter
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'updated_at', 'due_date', 'priority', 'status']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get filtered queryset based on user permissions."""
        user = self.request.user
        queryset = Task.objects.active().with_related().with_statistics()
        
        # Filter based on user permissions
        return queryset.filter(
            Q(created_by=user) | Q(assigned_to=user)
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return TaskListSerializer
        elif self.action == 'create':
            return TaskCreateSerializer
        else:
            return TaskDetailSerializer
    
    def perform_create(self, serializer):
        """Set the creator when creating a task."""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, CanEditTask])
    def assign(self, request, pk=None):
        """Assign users to a task."""
        task = self.get_object()
        serializer = TaskAssignmentCreateSerializer(
            data=request.data,
            context={'task': task, 'request': request}
        )
        
        if serializer.is_valid():
            assignment = serializer.save()
            
            # Create history entry
            TaskHistory.objects.create(
                task=task,
                user=request.user,
                action='assigned',
                metadata={'assigned_user': assignment.user.username}
            )
            
            return Response(
                TaskAssignmentSerializer(assignment).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def comments(self, request, pk=None):
        """Get comments for a task."""
        task = self.get_object()
        comments = task.comments.filter(is_deleted=False, parent_comment=None).with_replies()
        serializer = CommentSerializer(comments, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_comment(self, request, pk=None):
        """Add a comment to a task."""
        task = self.get_object()
        serializer = CommentSerializer(data=request.data)
        
        if serializer.is_valid():
            comment = serializer.save(task=task, author=request.user)
            
            # Create history entry
            TaskHistory.objects.create(
                task=task,
                user=request.user,
                action='commented'
            )
            
            return Response(
                CommentSerializer(comment).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get history for a task."""
        task = self.get_object()
        history = task.history.select_related('user').order_by('-created_at')
        
        page = self.paginate_queryset(history)
        if page is not None:
            serializer = TaskHistorySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = TaskHistorySerializer(history, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def my_tasks(self, request):
        """Get current user's tasks."""
        user = request.user
        queryset = self.get_queryset().filter(
            Q(created_by=user) | Q(assigned_to=user)
        )
        
        # Apply additional filters
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def overdue(self, request):
        """Get overdue tasks."""
        queryset = self.get_queryset().overdue()
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = TaskListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = TaskListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get task statistics for the current user."""
        user = request.user
        queryset = self.get_queryset()
        
        stats = {
            'total_tasks': queryset.count(),
            'by_status': {},
            'by_priority': {},
            'overdue_count': queryset.overdue().count(),
            'due_soon_count': queryset.due_soon().count(),
            'completed_this_week': queryset.filter(
                status='done',
                updated_at__week=timezone.now().isocalendar()[1]
            ).count()
        }
        
        # Tasks by status
        from apps.tasks.choices import TaskStatus, TaskPriority
        for status_choice, _ in TaskStatus.choices:
            stats['by_status'][status_choice] = queryset.filter(status=status_choice).count()
        
        # Tasks by priority
        for priority_choice, _ in TaskPriority.choices:
            stats['by_priority'][priority_choice] = queryset.filter(priority=priority_choice).count()
        
        return Response(stats)


class CommentViewSet(viewsets.ModelViewSet):
    """ViewSet for Comment CRUD operations."""
    
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get comments for tasks user has access to."""
        user = self.request.user
        return Comment.objects.filter(
            task__in=Task.objects.filter(
                Q(created_by=user) | Q(assigned_to=user)
            ),
            is_deleted=False
        ).select_related('author', 'task').with_replies()
    
    def perform_create(self, serializer):
        """Set the comment author."""
        serializer.save(author=self.request.user)


class TagViewSet(viewsets.ModelViewSet):
    """ViewSet for Tag CRUD operations."""
    
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]
    queryset = Tag.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering = ['name']
    
    @action(detail=False, methods=['get'])
    def popular(self, request):
        """Get popular tags based on usage."""
        from django.db.models import Count
        
        popular_tags = Tag.objects.annotate(
            task_count=Count('task', filter=Q(task__is_deleted=False))
        ).filter(task_count__gt=0).order_by('-task_count')[:20]
        
        serializer = self.get_serializer(popular_tags, many=True)
        return Response(serializer.data)


class TaskTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for TaskTemplate CRUD operations."""
    
    serializer_class = TaskTemplateSerializer
    permission_classes = [IsAuthenticated]
    queryset = TaskTemplate.objects.filter(is_active=True)
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'title_template', 'description_template']
    ordering = ['name']
    
    @action(detail=True, methods=['post'])
    def create_task(self, request, pk=None):
        """Create a task from this template."""
        template = self.get_object()
        variables = request.data.get('variables', {})
        
        # Create task from template
        task = Task.objects.create_from_template(
            template=template,
            variables=variables,
            created_by=request.user
        )
        
        serializer = TaskDetailSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TeamViewSet(viewsets.ModelViewSet):
    """ViewSet for Team CRUD operations."""
    
    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering = ['name']
    
    def get_queryset(self):
        """Get teams user is member of or leads."""
        user = self.request.user
        return Team.objects.filter(
            Q(members=user) | Q(lead=user),
            is_active=True,
            is_deleted=False
        ).distinct().with_stats()
    
    @action(detail=True, methods=['get'])
    def tasks(self, request, pk=None):
        """Get tasks assigned to team members."""
        team = self.get_object()
        tasks = Task.objects.active().by_team_members(team).with_related()
        
        page = self.paginate_queryset(tasks)
        if page is not None:
            serializer = TaskListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = TaskListSerializer(tasks, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_member(self, request, pk=None):
        """Add a member to the team."""
        team = self.get_object()
        
        # Check if user can manage this team
        if team.lead != request.user:
            return Response(
                {'error': 'Only team leads can add members'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = TeamMembershipSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(team=team)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['delete'])
    def remove_member(self, request, pk=None):
        """Remove a member from the team."""
        team = self.get_object()
        user_id = request.data.get('user_id')
        
        # Check if user can manage this team
        if team.lead != request.user:
            return Response(
                {'error': 'Only team leads can remove members'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            membership = team.teammembership_set.get(user_id=user_id, is_active=True)
            membership.is_active = False
            membership.save()
            return Response({'success': 'Member removed'}, status=status.HTTP_200_OK)
        except team.teammembership_set.model.DoesNotExist:
            return Response(
                {'error': 'Member not found'},
                status=status.HTTP_404_NOT_FOUND
            )
