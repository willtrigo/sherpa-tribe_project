"""
Task-related signal handlers for audit logging, notifications, and business logic automation.

This module implements Django signals for the Task model to handle:
- Audit trail creation (TaskHistory)
- Automatic notifications
- Status transition validation
- Parent task updates
- Search index updates
- Cache invalidation
"""

import logging
from typing import Any, Dict, Optional, Set

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models.signals import post_save, pre_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.utils import timezone

from apps.tasks.models import Task, TaskHistory, Comment
from apps.tasks.choices import TaskStatus, TaskPriority
from apps.notifications.services import NotificationService
from apps.common.utils import get_client_ip

logger = logging.getLogger(__name__)
User = get_user_model()


class TaskSignalHandler:
    """
    Centralized handler for task-related signals with comprehensive logging and error handling.
    """
    
    @staticmethod
    def _create_audit_entry(
        task: Task,
        action: str,
        user: Optional[User] = None,
        changes: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Create an audit trail entry for task modifications.
        
        Args:
            task: The task instance
            action: The action performed (created, updated, deleted, etc.)
            user: The user who performed the action
            changes: Dictionary of field changes
            metadata: Additional metadata for the audit entry
        """
        try:
            TaskHistory.objects.create(
                task=task,
                action=action,
                user=user,
                changes=changes or {},
                metadata=metadata or {},
                timestamp=timezone.now()
            )
            logger.debug(f"Audit entry created for task {task.id}: {action}")
        except Exception as e:
            logger.error(f"Failed to create audit entry for task {task.id}: {str(e)}")

    @staticmethod
    def _invalidate_task_caches(task: Task) -> None:
        """
        Invalidate relevant cache entries for the task.
        
        Args:
            task: The task instance
        """
        cache_keys = [
            f"task:{task.id}",
            f"task_list:user:{task.created_by_id}",
            f"task_stats:user:{task.created_by_id}",
            "dashboard_stats",
        ]
        
        # Add assignee caches
        for assignee_id in task.assigned_to.values_list('id', flat=True):
            cache_keys.extend([
                f"task_list:user:{assignee_id}",
                f"task_stats:user:{assignee_id}",
            ])
        
        cache.delete_many(cache_keys)
        logger.debug(f"Invalidated {len(cache_keys)} cache entries for task {task.id}")

    @staticmethod
    def _get_field_changes(instance: Task, original: Optional[Task]) -> Dict[str, Any]:
        """
        Compare task instances and return dictionary of changed fields.
        
        Args:
            instance: Current task instance
            original: Original task instance before changes
            
        Returns:
            Dictionary mapping field names to {'old': value, 'new': value}
        """
        if not original:
            return {}
        
        changes = {}
        tracked_fields = [
            'title', 'description', 'status', 'priority', 'due_date',
            'estimated_hours', 'actual_hours', 'is_archived'
        ]
        
        for field in tracked_fields:
            old_value = getattr(original, field, None)
            new_value = getattr(instance, field, None)
            
            if old_value != new_value:
                changes[field] = {
                    'old': str(old_value) if old_value else None,
                    'new': str(new_value) if new_value else None,
                }
        
        return changes

    @staticmethod
    def _should_send_notification(
        task: Task,
        action: str,
        changes: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Determine if a notification should be sent based on task changes.
        
        Args:
            task: The task instance
            action: The action performed
            changes: Dictionary of field changes
            
        Returns:
            True if notification should be sent
        """
        notification_triggers = {
            'created': True,
            'status_changed': bool(changes and 'status' in changes),
            'assigned': True,
            'due_date_changed': bool(changes and 'due_date' in changes),
            'priority_changed': bool(
                changes and 'priority' in changes and 
                changes['priority']['new'] in [TaskPriority.HIGH, TaskPriority.CRITICAL]
            ),
        }
        
        return notification_triggers.get(action, False)


@receiver(pre_save, sender=Task)
def task_pre_save_handler(sender: type, instance: Task, **kwargs: Any) -> None:
    """
    Handle task pre-save operations including status validation and change tracking.
    
    Args:
        sender: The model class (Task)
        instance: The task instance being saved
        **kwargs: Additional keyword arguments
    """
    try:
        # Store original instance for comparison
        if instance.pk:
            try:
                original = Task.objects.get(pk=instance.pk)
                instance._original = original
            except Task.DoesNotExist:
                instance._original = None
        else:
            instance._original = None
        
        # Validate status transitions
        if instance._original and instance._original.status != instance.status:
            _validate_status_transition(instance._original.status, instance.status)
        
        # Auto-update timestamps
        if instance._original:
            if instance.status == TaskStatus.IN_PROGRESS and instance._original.status != TaskStatus.IN_PROGRESS:
                instance.started_at = timezone.now()
            elif instance.status == TaskStatus.COMPLETED and instance._original.status != TaskStatus.COMPLETED:
                instance.completed_at = timezone.now()
        
        # Auto-calculate actual hours if task is completed
        if instance.status == TaskStatus.COMPLETED and not instance.actual_hours:
            instance.actual_hours = instance.estimated_hours
            
    except Exception as e:
        logger.error(f"Error in task pre_save handler for task {instance.id}: {str(e)}")


@receiver(post_save, sender=Task)
def task_post_save_handler(sender: type, instance: Task, created: bool, **kwargs: Any) -> None:
    """
    Handle task post-save operations including audit logging and notifications.
    
    Args:
        sender: The model class (Task)
        instance: The task instance that was saved
        created: True if this is a new instance
        **kwargs: Additional keyword arguments
    """
    handler = TaskSignalHandler()
    
    try:
        original = getattr(instance, '_original', None)
        changes = handler._get_field_changes(instance, original)
        
        if created:
            # Handle new task creation
            handler._create_audit_entry(
                task=instance,
                action='created',
                user=getattr(instance, '_current_user', instance.created_by),
                metadata={'ip_address': getattr(instance, '_client_ip', None)}
            )
            
            # Send creation notification
            if handler._should_send_notification(instance, 'created'):
                _schedule_notification(instance, 'task_created')
            
            logger.info(f"New task created: {instance.id} - {instance.title}")
            
        else:
            # Handle task updates
            if changes:
                action = 'updated'
                
                # Determine specific action type
                if 'status' in changes:
                    action = 'status_changed'
                elif 'priority' in changes:
                    action = 'priority_changed'
                
                handler._create_audit_entry(
                    task=instance,
                    action=action,
                    user=getattr(instance, '_current_user', None),
                    changes=changes,
                    metadata={'ip_address': getattr(instance, '_client_ip', None)}
                )
                
                # Send update notifications
                if handler._should_send_notification(instance, action, changes):
                    _schedule_notification(instance, f'task_{action}', changes)
                
                logger.info(f"Task updated: {instance.id} - Changes: {list(changes.keys())}")
        
        # Update parent task if exists
        if instance.parent_task:
            _update_parent_task_progress(instance.parent_task)
        
        # Invalidate related caches
        handler._invalidate_task_caches(instance)
        
        # Schedule search index update
        _schedule_search_index_update(instance)
        
    except Exception as e:
        logger.error(f"Error in task post_save handler for task {instance.id}: {str(e)}")


@receiver(post_delete, sender=Task)
def task_post_delete_handler(sender: type, instance: Task, **kwargs: Any) -> None:
    """
    Handle task deletion operations.
    
    Args:
        sender: The model class (Task)
        instance: The task instance that was deleted
        **kwargs: Additional keyword arguments
    """
    handler = TaskSignalHandler()
    
    try:
        # Create audit entry for deletion
        handler._create_audit_entry(
            task=instance,
            action='deleted',
            user=getattr(instance, '_current_user', None),
            metadata={
                'ip_address': getattr(instance, '_client_ip', None),
                'deleted_at': timezone.now().isoformat()
            }
        )
        
        # Update parent task if exists
        if instance.parent_task:
            _update_parent_task_progress(instance.parent_task)
        
        # Invalidate caches
        handler._invalidate_task_caches(instance)
        
        # Remove from search index
        _schedule_search_index_removal(instance)
        
        logger.info(f"Task deleted: {instance.id} - {instance.title}")
        
    except Exception as e:
        logger.error(f"Error in task post_delete handler for task {instance.id}: {str(e)}")


@receiver(m2m_changed, sender=Task.assigned_to.through)
def task_assignment_changed_handler(
    sender: type,
    instance: Task,
    action: str,
    pk_set: Optional[Set[int]],
    **kwargs: Any
) -> None:
    """
    Handle changes to task assignments.
    
    Args:
        sender: The through model class
        instance: The task instance
        action: The M2M action (pre_add, post_add, pre_remove, post_remove, etc.)
        pk_set: Set of primary keys for the related objects
        **kwargs: Additional keyword arguments
    """
    if action not in ['post_add', 'post_remove'] or not pk_set:
        return
    
    handler = TaskSignalHandler()
    
    try:
        user_ids = list(pk_set)
        users = User.objects.filter(id__in=user_ids)
        
        if action == 'post_add':
            # Handle new assignments
            handler._create_audit_entry(
                task=instance,
                action='assigned',
                user=getattr(instance, '_current_user', None),
                metadata={
                    'assigned_users': [{'id': u.id, 'username': u.username} for u in users],
                    'ip_address': getattr(instance, '_client_ip', None)
                }
            )
            
            # Send assignment notifications
            for user in users:
                _schedule_notification(instance, 'task_assigned', recipient=user)
            
            logger.info(f"Task {instance.id} assigned to users: {user_ids}")
            
        elif action == 'post_remove':
            # Handle assignment removals
            handler._create_audit_entry(
                task=instance,
                action='unassigned',
                user=getattr(instance, '_current_user', None),
                metadata={
                    'unassigned_users': [{'id': u.id, 'username': u.username} for u in users],
                    'ip_address': getattr(instance, '_client_ip', None)
                }
            )
            
            logger.info(f"Task {instance.id} unassigned from users: {user_ids}")
        
        # Invalidate caches for affected users
        for user_id in user_ids:
            cache.delete_many([
                f"task_list:user:{user_id}",
                f"task_stats:user:{user_id}",
            ])
        
    except Exception as e:
        logger.error(f"Error in task assignment handler for task {instance.id}: {str(e)}")


@receiver(m2m_changed, sender=Task.tags.through)
def task_tags_changed_handler(
    sender: type,
    instance: Task,
    action: str,
    pk_set: Optional[Set[int]],
    **kwargs: Any
) -> None:
    """
    Handle changes to task tags for search indexing.
    
    Args:
        sender: The through model class
        instance: The task instance
        action: The M2M action
        pk_set: Set of tag primary keys
        **kwargs: Additional keyword arguments
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return
    
    try:
        # Schedule search index update when tags change
        _schedule_search_index_update(instance)
        
        # Invalidate tag-related caches
        cache.delete(f"task_tags:{instance.id}")
        
        logger.debug(f"Task {instance.id} tags changed - action: {action}")
        
    except Exception as e:
        logger.error(f"Error in task tags handler for task {instance.id}: {str(e)}")


# Utility functions for signal handlers

def _validate_status_transition(old_status: str, new_status: str) -> None:
    """
    Validate that a status transition is allowed.
    
    Args:
        old_status: The current status
        new_status: The desired new status
        
    Raises:
        ValidationError: If the transition is not allowed
    """
    from django.core.exceptions import ValidationError
    
    # Define allowed transitions
    allowed_transitions = {
        TaskStatus.TODO: [TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
        TaskStatus.IN_PROGRESS: [TaskStatus.COMPLETED, TaskStatus.BLOCKED, TaskStatus.TODO, TaskStatus.CANCELLED],
        TaskStatus.COMPLETED: [TaskStatus.IN_PROGRESS],  # Allow reopening
        TaskStatus.BLOCKED: [TaskStatus.IN_PROGRESS, TaskStatus.TODO],
        TaskStatus.CANCELLED: [TaskStatus.TODO, TaskStatus.IN_PROGRESS],
    }
    
    if new_status not in allowed_transitions.get(old_status, []):
        raise ValidationError(
            f"Invalid status transition from '{old_status}' to '{new_status}'"
        )


def _update_parent_task_progress(parent_task: Task) -> None:
    """
    Update parent task progress based on subtask completion.
    
    Args:
        parent_task: The parent task to update
    """
    try:
        subtasks = parent_task.subtasks.all()
        total_subtasks = subtasks.count()
        
        if total_subtasks == 0:
            return
        
        completed_subtasks = subtasks.filter(status=TaskStatus.COMPLETED).count()
        progress_percentage = (completed_subtasks / total_subtasks) * 100
        
        # Update parent task metadata
        parent_task.metadata['subtask_progress'] = {
            'total': total_subtasks,
            'completed': completed_subtasks,
            'percentage': round(progress_percentage, 2)
        }
        
        # Auto-complete parent if all subtasks are done
        if progress_percentage == 100 and parent_task.status != TaskStatus.COMPLETED:
            parent_task.status = TaskStatus.COMPLETED
            parent_task.completed_at = timezone.now()
        
        parent_task.save(update_fields=['metadata', 'status', 'completed_at', 'updated_at'])
        
        logger.debug(f"Updated parent task {parent_task.id} progress: {progress_percentage}%")
        
    except Exception as e:
        logger.error(f"Error updating parent task {parent_task.id}: {str(e)}")


def _schedule_notification(
    task: Task,
    notification_type: str,
    changes: Optional[Dict[str, Any]] = None,
    recipient: Optional[User] = None
) -> None:
    """
    Schedule a notification to be sent asynchronously.
    
    Args:
        task: The task instance
        notification_type: Type of notification to send
        changes: Optional changes dictionary
        recipient: Specific recipient (if not provided, will notify assignees)
    """
    try:
        from celery_app.tasks import send_task_notification
        
        send_task_notification.delay(
            task_id=task.id,
            notification_type=notification_type,
            changes=changes,
            recipient_id=recipient.id if recipient else None
        )
        
        logger.debug(f"Scheduled {notification_type} notification for task {task.id}")
        
    except Exception as e:
        logger.error(f"Error scheduling notification for task {task.id}: {str(e)}")


def _schedule_search_index_update(task: Task) -> None:
    """
    Schedule search index update for the task.
    
    Args:
        task: The task instance
    """
    try:
        from celery_app.tasks import update_search_index
        
        update_search_index.delay('task', task.id)
        logger.debug(f"Scheduled search index update for task {task.id}")
        
    except Exception as e:
        logger.error(f"Error scheduling search index update for task {task.id}: {str(e)}")


def _schedule_search_index_removal(task: Task) -> None:
    """
    Schedule search index removal for the deleted task.
    
    Args:
        task: The task instance
    """
    try:
        from celery_app.tasks import remove_from_search_index
        
        remove_from_search_index.delay('task', task.id)
        logger.debug(f"Scheduled search index removal for task {task.id}")
        
    except Exception as e:
        logger.error(f"Error scheduling search index removal for task {task.id}: {str(e)}")
