from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from apps.tasks.models import (
    Task, TaskAssignment, Comment, TaskHistory, Tag, 
    TaskTemplate, Team, TeamMembership
)
from apps.tasks.choices import TaskStatus, TaskPriority
from apps.tasks.validators import TaskStatusTransitionValidator
from apps.common.serializers import BaseModelSerializer

User = get_user_model()


class TagSerializer(BaseModelSerializer):
    """Serializer for Tag model."""
    
    task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Tag
        fields = ['id', 'name', 'color', 'description', 'task_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'name': {
                'validators': [
                    UniqueValidator(
                        queryset=Tag.objects.all(),
                        message="A tag with this name already exists."
                    )
                ]
            }
        }
    
    def get_task_count(self, obj):
        """Get number of tasks using this tag."""
        return obj.task_set.filter(is_deleted=False).count()
    
    def validate_name(self, value):
        """Validate and normalize tag name."""
        return value.lower().strip()


class UserMinimalSerializer(serializers.ModelSerializer):
    """Minimal user serializer for nested relationships."""
    
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name']
        read_only_fields = ['id', 'username', 'email', 'full_name']


class TaskAssignmentSerializer(BaseModelSerializer):
    """Serializer for TaskAssignment model."""
    
    user = UserMinimalSerializer(read_only=True)
    assigned_by = UserMinimalSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = TaskAssignment
        fields = [
            'id', 'user', 'user_id', 'assigned_by', 'assigned_at', 
            'is_active', 'role', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'assigned_by', 'assigned_at', 'created_at', 'updated_at']
    
    def validate_user_id(self, value):
        """Validate user exists."""
        try:
            User.objects.get(id=value)
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("User does not exist.")


class CommentSerializer(BaseModelSerializer):
    """Serializer for Comment model."""
    
    author = UserMinimalSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    reply_count = serializers.SerializerMethodField()
    is_edited = serializers.SerializerMethodField()
    
    class Meta:
        model = Comment
        fields = [
            'id', 'content', 'author', 'parent_comment', 'is_internal',
            'replies', 'reply_count', 'is_edited', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'author', 'created_at', 'updated_at']
    
    def get_replies(self, obj):
        """Get replies to this comment."""
        if hasattr(obj, '_prefetched_replies'):
            replies = [reply for reply in obj._prefetched_replies if not reply.is_deleted]
        else:
            replies = obj.replies.filter(is_deleted=False).order_by('created_at')
        
        return CommentSerializer(replies, many=True, context=self.context).data
    
    def get_reply_count(self, obj):
        """Get count of replies."""
        return obj.replies.filter(is_deleted=False).count()
    
    def get_is_edited(self, obj):
        """Check if comment was edited."""
        return obj.updated_at > obj.created_at + timezone.timedelta(minutes=1)


class TaskHistorySerializer(BaseModelSerializer):
    """Serializer for TaskHistory model."""
    
    user = UserMinimalSerializer(read_only=True)
    
    class Meta:
        model = TaskHistory
        fields = [
            'id', 'user', 'action', 'field_name', 'old_value', 
            'new_value', 'metadata', 'created_at'
        ]
        read_only_fields = ['id', 'user', 'created_at']


class TaskListSerializer(BaseModelSerializer):
    """Lightweight serializer for task list views."""
    
    created_by = UserMinimalSerializer(read_only=True)
    assigned_to = UserMinimalSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    subtask_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    progress = serializers.SerializerMethodField()
    
    class Meta:
        model = Task
        fields = [
            'id', 'title', 'status', 'status_display', 'priority', 'priority_display',
            'due_date', 'estimated_hours', 'actual_hours', 'created_by', 'assigned_to',
            'tags', 'is_overdue', 'subtask_count', 'comment_count', 'progress',
            'completion_percentage', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_by', 'is_overdue', 'created_at', 'updated_at'
        ]
    
    def get_progress(self, obj):
        """Get calculated progress."""
        return obj.calculate_progress()


class TaskDetailSerializer(BaseModelSerializer):
    """Comprehensive serializer for task detail views."""
    
    created_by = UserMinimalSerializer(read_only=True)
    assigned_to = UserMinimalSerializer(many=True, read_only=True)
    assignments = TaskAssignmentSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    parent_task = serializers.SerializerMethodField()
    subtasks = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)
    history = TaskHistorySerializer(many=True, read_only=True)
    
    # Display fields
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    
    # Computed fields
    is_overdue = serializers.BooleanField(read_only=True)
    has_subtasks = serializers.BooleanField(read_only=True)
    subtask_count = serializers.IntegerField(read_only=True)
    completed_subtask_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    progress = serializers.SerializerMethodField()
    time_remaining = serializers.SerializerMethodField()
    
    # Write-only fields for updates
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of tag IDs to assign to the task"
    )
    assignee_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of user IDs to assign to the task"
    )
    
    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'status', 'status_display',
            'priority', 'priority_display', 'due_date', 'estimated_hours',
            'actual_hours', 'completion_percentage', 'metadata',
            'is_recurring', 'recurrence_pattern', 'created_by', 'assigned_to',
            'assignments', 'tags', 'parent_task', 'subtasks', 'comments',
            'history', 'is_overdue', 'has_subtasks', 'subtask_count',
            'completed_subtask_count', 'comment_count', 'progress',
            'time_remaining', 'created_at', 'updated_at',
            'tag_ids', 'assignee_ids'
        ]
        read_only_fields = [
            'id', 'created_by', 'is_overdue', 'has_subtasks',
            'created_at', 'updated_at'
        ]
    
    def get_parent_task(self, obj):
        """Get parent task minimal info."""
        if obj.parent_task:
            return {
                'id': obj.parent_task.id,
                'title': obj.parent_task.title,
                'status': obj.parent_task.status
            }
        return None
    
    def get_subtasks(self, obj):
        """Get subtasks with minimal info."""
        subtasks = obj.subtasks.filter(is_deleted=False).select_related('created_by')
        return TaskListSerializer(subtasks, many=True, context=self.context).data
    
    def get_progress(self, obj):
        """Get calculated progress."""
        return obj.calculate_progress()
    
    def get_time_remaining(self, obj):
        """Get time remaining until due date."""
        if obj.due_date:
            now = timezone.now()
            if obj.due_date > now:
                delta = obj.due_date - now
                return {
                    'days': delta.days,
                    'hours': delta.seconds // 3600,
                    'total_hours': int(delta.total_seconds() // 3600)
                }
            else:
                delta = now - obj.due_date
                return {
                    'days': -delta.days,
                    'hours': -(delta.seconds // 3600),
                    'total_hours': -int(delta.total_seconds() // 3600),
                    'overdue': True
                }
        return None
    
    def validate_status(self, value):
        """Validate status transition."""
        if self.instance and self.instance.status != value:
            validator = TaskStatusTransitionValidator(self.instance, value)
            validator.validate()
        return value
    
    def validate_assignee_ids(self, value):
        """Validate assignee IDs exist."""
        if value:
            existing_ids = set(User.objects.filter(id__in=value).values_list('id', flat=True))
            invalid_ids = set(value) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError(f"Invalid user IDs: {list(invalid_ids)}")
        return value
    
    def validate_tag_ids(self, value):
        """Validate tag IDs exist."""
        if value:
            existing_ids = set(Tag.objects.filter(id__in=value).values_list('id', flat=True))
            invalid_ids = set(value) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError(f"Invalid tag IDs: {list(invalid_ids)}")
        return value
    
    @transaction.atomic
    def update(self, instance, validated_data):
        """Update task with related objects."""
        tag_ids = validated_data.pop('tag_ids', None)
        assignee_ids = validated_data.pop('assignee_ids', None)
        
        # Track changes for history
        changes = {}
        for field, value in validated_data.items():
            old_value = getattr(instance, field)
            if old_value != value:
                changes[field] = {'old': old_value, 'new': value}
        
        # Update the task
        task = super().update(instance, validated_data)
        
        # Update tags if provided
        if tag_ids is not None:
            old_tag_names = list(task.tags.values_list('name', flat=True))
            task.tags.set(tag_ids)
            new_tag_names = list(task.tags.values_list('name', flat=True))
            if set(old_tag_names) != set(new_tag_names):
                changes['tags'] = {'old': old_tag_names, 'new': new_tag_names}
        
        # Update assignees if provided
        if assignee_ids is not None:
            old_assignee_names = list(task.assigned_to.values_list('username', flat=True))
            # Deactivate old assignments
            task.assignments.update(is_active=False)
            # Create new assignments
            for user_id in assignee_ids:
                TaskAssignment.objects.create(
                    task=task,
                    user_id=user_id,
                    assigned_by=self.context['request'].user
                )
            new_assignee_names = list(task.assigned_to.values_list('username', flat=True))
            if set(old_assignee_names) != set(new_assignee_names):
                changes['assignees'] = {'old': old_assignee_names, 'new': new_assignee_names}
        
        # Create history entries for changes
        self._create_history_entries(task, changes)
        
        return task
    
    def _create_history_entries(self, task, changes):
        """Create history entries for task changes."""
        user = self.context['request'].user
        
        for field, change in changes.items():
            TaskHistory.objects.create(
                task=task,
                user=user,
                action=f"{field}_changed",
                field_name=field,
                old_value=str(change['old']),
                new_value=str(change['new'])
            )


class TaskCreateSerializer(BaseModelSerializer):
    """Serializer for creating new tasks."""
    
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of tag IDs to assign to the task"
    )
    assignee_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of user IDs to assign to the task"
    )
    parent_task_id = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="ID of parent task if this is a subtask"
    )
    
    class Meta:
        model = Task
        fields = [
            'title', 'description', 'status', 'priority', 'due_date',
            'estimated_hours', 'completion_percentage', 'metadata',
            'is_recurring', 'recurrence_pattern', 'tag_ids', 'assignee_ids',
            'parent_task_id'
        ]
        extra_kwargs = {
            'status': {'default': TaskStatus.TODO},
            'priority': {'default': TaskPriority.MEDIUM},
            'completion_percentage': {'default': 0}
        }
    
    def validate_parent_task_id(self, value):
        """Validate parent task exists and user has access."""
        if value:
            try:
                parent_task = Task.objects.get(id=value, is_deleted=False)
                # Check if user has access to parent task
                user = self.context['request'].user
                if not (parent_task.created_by == user or 
                        parent_task.assigned_to.filter(id=user.id).exists()):
                    raise serializers.ValidationError("You don't have access to this parent task.")
                return value
            except Task.DoesNotExist:
                raise serializers.ValidationError("Parent task does not exist.")
        return value
    
    def validate_tag_ids(self, value):
        """Validate tag IDs exist."""
        if value:
            existing_ids = set(Tag.objects.filter(id__in=value).values_list('id', flat=True))
            invalid_ids = set(value) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError(f"Invalid tag IDs: {list(invalid_ids)}")
        return value
    
    def validate_assignee_ids(self, value):
        """Validate assignee IDs exist."""
        if value:
            existing_ids = set(User.objects.filter(id__in=value).values_list('id', flat=True))
            invalid_ids = set(value) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError(f"Invalid user IDs: {list(invalid_ids)}")
        return value
    
    @transaction.atomic
    def create(self, validated_data):
        """Create task with related objects."""
        tag_ids = validated_data.pop('tag_ids', [])
        assignee_ids = validated_data.pop('assignee_ids', [])
        parent_task_id = validated_data.pop('parent_task_id', None)
        
        # Set parent task
        if parent_task_id:
            validated_data['parent_task_id'] = parent_task_id
        
        # Set creator
        validated_data['created_by'] = self.context['request'].user
        
        # Create task
        task = Task.objects.create(**validated_data)
        
        # Add tags
        if tag_ids:
            task.tags.set(tag_ids)
        
        # Add assignees
        if assignee_ids:
            assignments = []
            for user_id in assignee_ids:
                assignments.append(
                    TaskAssignment(
                        task=task,
                        user_id=user_id,
                        assigned_by=self.context['request'].user
                    )
                )
            TaskAssignment.objects.bulk_create(assignments)
        
        # Create history entry
        TaskHistory.objects.create(
            task=task,
            user=self.context['request'].user,
            action='created',
            metadata={'initial_data': validated_data}
        )
        
        return task


class TaskTemplateSerializer(BaseModelSerializer):
    """Serializer for TaskTemplate model."""
    
    default_tags = TagSerializer(many=True, read_only=True)
    default_tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    usage_count = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskTemplate
        fields = [
            'id', 'name', 'title_template', 'description_template',
            'default_priority', 'default_estimated_hours', 'default_tags',
            'default_tag_ids', 'is_active', 'usage_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_usage_count(self, obj):
        """Get count of tasks created from this template."""
        # This would need to be tracked in metadata or separate model
        return 0
    
    def validate_default_tag_ids(self, value):
        """Validate default tag IDs exist."""
        if value:
            existing_ids = set(Tag.objects.filter(id__in=value).values_list('id', flat=True))
            invalid_ids = set(value) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError(f"Invalid tag IDs: {list(invalid_ids)}")
        return value
    
    def update(self, instance, validated_data):
        """Update template with tags."""
        default_tag_ids = validated_data.pop('default_tag_ids', None)
        
        template = super().update(instance, validated_data)
        
        if default_tag_ids is not None:
            template.default_tags.set(default_tag_ids)
        
        return template


class TeamMembershipSerializer(BaseModelSerializer):
    """Serializer for TeamMembership model."""
    
    user = UserMinimalSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = TeamMembership
        fields = [
            'id', 'user', 'user_id', 'role', 'joined_at', 
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'joined_at', 'created_at', 'updated_at']


class TeamSerializer(BaseModelSerializer):
    """Serializer for Team model."""
    
    lead = UserMinimalSerializer(read_only=True)
    members = UserMinimalSerializer(many=True, read_only=True)
    memberships = TeamMembershipSerializer(
        source='teammembership_set', 
        many=True, 
        read_only=True
    )
    member_count = serializers.SerializerMethodField()
    active_member_count = serializers.SerializerMethodField()
    
    # Write-only fields
    lead_id = serializers.IntegerField(write_only=True, required=False)
    member_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Team
        fields = [
            'id', 'name', 'description', 'lead', 'lead_id', 'members',
            'member_ids', 'memberships', 'member_count', 'active_member_count',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_member_count(self, obj):
        """Get total member count."""
        return obj.members.count()
    
    def get_active_member_count(self, obj):
        """Get active member count."""
        return obj.teammembership_set.filter(is_active=True).count()
    
    def validate_lead_id(self, value):
        """Validate lead user exists."""
        if value:
            try:
                User.objects.get(id=value)
                return value
            except User.DoesNotExist:
                raise serializers.ValidationError("Lead user does not exist.")
        return value
    
    def validate_member_ids(self, value):
        """Validate member IDs exist."""
        if value:
            existing_ids = set(User.objects.filter(id__in=value).values_list('id', flat=True))
            invalid_ids = set(value) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError(f"Invalid user IDs: {list(invalid_ids)}")
        return value
    
    @transaction.atomic
    def create(self, validated_data):
        """Create team with members."""
        member_ids = validated_data.pop('member_ids', [])
        lead_id = validated_data.pop('lead_id', None)
        
        if lead_id:
            validated_data['lead_id'] = lead_id
        
        team = Team.objects.create(**validated_data)
        
        # Add members
        if member_ids:
            memberships = []
            for user_id in member_ids:
                role = 'lead' if user_id == lead_id else 'member'
                memberships.append(
                    TeamMembership(team=team, user_id=user_id, role=role)
                )
            TeamMembership.objects.bulk_create(memberships)
        
        return team
    
    @transaction.atomic
    def update(self, instance, validated_data):
        """Update team with members."""
        member_ids = validated_data.pop('member_ids', None)
        lead_id = validated_data.pop('lead_id', None)
        
        if lead_id:
            validated_data['lead_id'] = lead_id
        
        team = super().update(instance, validated_data)
        
        if member_ids is not None:
            # Deactivate old memberships
            team.teammembership_set.update(is_active=False)
            
            # Create new memberships
            memberships = []
            for user_id in member_ids:
                role = 'lead' if user_id == lead_id else 'member'
                membership, created = TeamMembership.objects.get_or_create(
                    team=team,
                    user_id=user_id,
                    defaults={'role': role, 'is_active': True}
                )
                if not created:
                    membership.role = role
                    membership.is_active = True
                    membership.save()
        
        return team


class TaskAssignmentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating task assignments."""
    
    class Meta:
        model = TaskAssignment
        fields = ['user', 'role']
    
    def validate_user(self, value):
        """Validate user is not already assigned."""
        task = self.context['task']
        if TaskAssignment.objects.filter(task=task, user=value, is_active=True).exists():
            raise serializers.ValidationError("User is already assigned to this task.")
        return value
    
    def create(self, validated_data):
        """Create assignment with context."""
        validated_data['task'] = self.context['task']
        validated_data['assigned_by'] = self.context['request'].user
        return super().create(validated_data)
