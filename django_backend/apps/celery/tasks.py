"""
Celery tasks for the task management system.

This module contains all background tasks including notifications, monitoring,
maintenance, analytics, and workflow processing tasks.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from decimal import Decimal

from celery import shared_task, group, chain, chord
from celery.exceptions import Retry, MaxRetriesExceededError
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail, send_mass_mail
from django.template.loader import render_to_string
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Count, Avg, Sum, F
from django.core.cache import cache
from django.core.serializers import serialize

from apps.tasks.models import Task, TaskHistory, Comment
from apps.users.models import Team
from apps.notifications.models import Notification
from apps.workflows.models import WorkflowRule

# Configure logging
logger = logging.getLogger(__name__)
User = get_user_model()


class TaskNotificationError(Exception):
    """Custom exception for task notification errors."""
    pass


class TaskProcessingError(Exception):
    """Custom exception for task processing errors."""
    pass


# =============================================================================
# NOTIFICATION TASKS
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_task_notification(
    self,
    task_id: int,
    notification_type: str,
    recipient_ids: Optional[List[int]] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send email notifications for task events.
    
    Args:
        task_id: The ID of the task triggering the notification
        notification_type: Type of notification ('created', 'assigned', 'completed', etc.)
        recipient_ids: List of user IDs to receive notifications
        context: Additional context data for the notification
        
    Returns:
        Dict with notification results and metadata
        
    Raises:
        TaskNotificationError: If notification processing fails
    """
    try:
        from apps.tasks.models import Task
        from apps.notifications.services import NotificationService
        
        logger.info(f"Processing notification for task {task_id}, type: {notification_type}")
        
        # Retrieve task with optimized queries
        task = Task.objects.select_related(
            'created_by', 'parent_task'
        ).prefetch_related(
            'assigned_to', 'tags'
        ).get(id=task_id)
        
        # Determine recipients if not explicitly provided
        if not recipient_ids:
            recipients = set()
            
            # Add task creator
            recipients.add(task.created_by.id)
            
            # Add assigned users
            recipients.update(task.assigned_to.values_list('id', flat=True))
            
            # Add team members if task has team context
            if hasattr(task, 'team') and task.team:
                recipients.update(
                    task.team.members.values_list('id', flat=True)
                )
            
            recipient_ids = list(recipients)
        
        # Get recipient users
        recipients = User.objects.filter(
            id__in=recipient_ids,
            is_active=True
        ).select_related('profile')
        
        notification_service = NotificationService()
        
        # Process notifications for each recipient
        notification_results = []
        for recipient in recipients:
            try:
                # Check user notification preferences
                if not notification_service.should_send_notification(
                    recipient, notification_type
                ):
                    continue
                
                # Prepare notification context
                notification_context = {
                    'task': task,
                    'recipient': recipient,
                    'notification_type': notification_type,
                    'timestamp': timezone.now(),
                    **(context or {})
                }
                
                # Send email notification
                email_sent = notification_service.send_email_notification(
                    recipient=recipient,
                    template_name=f'notifications/task_{notification_type}.html',
                    subject=f'Task {notification_type.title()}: {task.title}',
                    context=notification_context
                )
                
                # Create database notification record
                notification_record = notification_service.create_notification_record(
                    recipient=recipient,
                    task=task,
                    notification_type=notification_type,
                    context=notification_context
                )
                
                notification_results.append({
                    'recipient_id': recipient.id,
                    'email_sent': email_sent,
                    'notification_id': notification_record.id if notification_record else None,
                    'status': 'success'
                })
                
            except Exception as recipient_error:
                logger.error(
                    f"Failed to send notification to user {recipient.id}: {recipient_error}"
                )
                notification_results.append({
                    'recipient_id': recipient.id,
                    'email_sent': False,
                    'notification_id': None,
                    'status': 'error',
                    'error': str(recipient_error)
                })
        
        # Update task notification status
        TaskHistory.objects.create(
            task=task,
            action=f'notification_{notification_type}',
            user=task.created_by,
            details={
                'notification_type': notification_type,
                'recipients_count': len(notification_results),
                'successful_notifications': sum(
                    1 for r in notification_results if r['status'] == 'success'
                )
            }
        )
        
        result = {
            'task_id': task_id,
            'notification_type': notification_type,
            'total_recipients': len(notification_results),
            'successful_notifications': sum(
                1 for r in notification_results if r['status'] == 'success'
            ),
            'failed_notifications': sum(
                1 for r in notification_results if r['status'] == 'error'
            ),
            'results': notification_results,
            'processed_at': timezone.now().isoformat()
        }
        
        logger.info(f"Notification task completed: {result}")
        return result
        
    except Task.DoesNotExist:
        error_msg = f"Task with ID {task_id} does not exist"
        logger.error(error_msg)
        raise TaskNotificationError(error_msg)
        
    except Exception as exc:
        logger.error(f"Notification task failed: {exc}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 60 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=retry_delay)
        
        raise TaskNotificationError(f"Max retries exceeded: {exc}")


@shared_task(bind=True, max_retries=2)
def send_bulk_notifications(
    self,
    notification_batch: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Send bulk notifications efficiently using group tasks.
    
    Args:
        notification_batch: List of notification data dictionaries
        
    Returns:
        Dict with batch processing results
    """
    try:
        logger.info(f"Processing bulk notifications batch: {len(notification_batch)} items")
        
        # Create notification tasks group
        notification_tasks = group(
            send_task_notification.s(
                task_id=item['task_id'],
                notification_type=item['notification_type'],
                recipient_ids=item.get('recipient_ids'),
                context=item.get('context')
            )
            for item in notification_batch
        )
        
        # Execute batch notifications
        job = notification_tasks.apply_async()
        results = job.get(propagate=False)
        
        # Aggregate results
        total_notifications = len(results)
        successful_notifications = sum(
            1 for result in results 
            if isinstance(result, dict) and result.get('successful_notifications', 0) > 0
        )
        
        batch_result = {
            'batch_size': len(notification_batch),
            'total_notifications': total_notifications,
            'successful_batches': successful_notifications,
            'failed_batches': total_notifications - successful_notifications,
            'processed_at': timezone.now().isoformat()
        }
        
        logger.info(f"Bulk notification batch completed: {batch_result}")
        return batch_result
        
    except Exception as exc:
        logger.error(f"Bulk notification task failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=120)
        
        raise


# =============================================================================
# MONITORING AND MAINTENANCE TASKS
# =============================================================================

@shared_task(bind=True, max_retries=2)
def generate_daily_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate daily task summary for all active users.
    
    Args:
        date: Date string (YYYY-MM-DD) for summary generation, defaults to today
        
    Returns:
        Dict with summary generation results
    """
    try:
        summary_date = datetime.fromisoformat(date) if date else timezone.now().date()
        logger.info(f"Generating daily summary for {summary_date}")
        
        # Get all active users
        active_users = User.objects.filter(
            is_active=True,
            last_login__gte=timezone.now() - timedelta(days=30)
        ).select_related('profile')
        
        summary_results = []
        
        for user in active_users:
            try:
                # Calculate user task statistics
                user_tasks = Task.objects.filter(
                    Q(assigned_to=user) | Q(created_by=user),
                    created_at__date=summary_date
                ).select_related('created_by').prefetch_related('assigned_to')
                
                task_stats = {
                    'total_tasks': user_tasks.count(),
                    'completed_tasks': user_tasks.filter(status='completed').count(),
                    'pending_tasks': user_tasks.filter(
                        status__in=['pending', 'in_progress']
                    ).count(),
                    'overdue_tasks': user_tasks.filter(
                        due_date__lt=timezone.now(),
                        status__in=['pending', 'in_progress']
                    ).count(),
                    'created_tasks': user_tasks.filter(created_by=user).count(),
                    'assigned_tasks': user_tasks.filter(assigned_to=user).count(),
                }
                
                # Calculate productivity metrics
                completed_tasks_with_hours = user_tasks.filter(
                    status='completed',
                    actual_hours__isnull=False
                )
                
                productivity_stats = {
                    'total_hours_logged': float(
                        completed_tasks_with_hours.aggregate(
                            total=Sum('actual_hours')
                        )['total'] or 0
                    ),
                    'average_completion_time': float(
                        completed_tasks_with_hours.aggregate(
                            avg=Avg('actual_hours')
                        )['avg'] or 0
                    ),
                    'efficiency_ratio': 0.0
                }
                
                # Calculate efficiency ratio
                if completed_tasks_with_hours.exists():
                    estimated_vs_actual = completed_tasks_with_hours.aggregate(
                        total_estimated=Sum('estimated_hours'),
                        total_actual=Sum('actual_hours')
                    )
                    
                    if (estimated_vs_actual['total_actual'] and 
                        estimated_vs_actual['total_estimated']):
                        productivity_stats['efficiency_ratio'] = float(
                            estimated_vs_actual['total_estimated'] / 
                            estimated_vs_actual['total_actual']
                        )
                
                # Prepare email context
                email_context = {
                    'user': user,
                    'date': summary_date,
                    'task_stats': task_stats,
                    'productivity_stats': productivity_stats,
                }
                
                # Send daily summary email
                if user.email and getattr(user, 'receive_daily_summary', True):
                    email_subject = f'Daily Task Summary - {summary_date}'
                    email_body = render_to_string(
                        'notifications/daily_summary.html',
                        email_context
                    )
                    
                    send_mail(
                        subject=email_subject,
                        message='',
                        html_message=email_body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False
                    )
                
                summary_results.append({
                    'user_id': user.id,
                    'email_sent': bool(user.email),
                    'task_stats': task_stats,
                    'productivity_stats': productivity_stats,
                    'status': 'success'
                })
                
            except Exception as user_error:
                logger.error(f"Failed to generate summary for user {user.id}: {user_error}")
                summary_results.append({
                    'user_id': user.id,
                    'status': 'error',
                    'error': str(user_error)
                })
        
        result = {
            'summary_date': str(summary_date),
            'total_users': len(active_users),
            'successful_summaries': sum(
                1 for r in summary_results if r['status'] == 'success'
            ),
            'failed_summaries': sum(
                1 for r in summary_results if r['status'] == 'error'
            ),
            'results': summary_results,
            'generated_at': timezone.now().isoformat()
        }
        
        logger.info(f"Daily summary generation completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Daily summary generation failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=300)  # 5 minutes
        
        raise


@shared_task(bind=True, max_retries=2)
def check_overdue_tasks(self) -> Dict[str, Any]:
    """
    Check for overdue tasks and notify assignees.
    
    Returns:
        Dict with overdue task processing results
    """
    try:
        logger.info("Checking for overdue tasks")
        
        current_time = timezone.now()
        
        # Find overdue tasks that haven't been marked as overdue yet
        overdue_tasks = Task.objects.filter(
            due_date__lt=current_time,
            status__in=['pending', 'in_progress'],
            is_archived=False
        ).select_related(
            'created_by'
        ).prefetch_related(
            'assigned_to'
        )
        
        overdue_results = []
        
        for task in overdue_tasks:
            try:
                # Update task metadata to mark as overdue
                if 'overdue_flagged' not in task.metadata:
                    with transaction.atomic():
                        task.metadata['overdue_flagged'] = True
                        task.metadata['overdue_flagged_at'] = current_time.isoformat()
                        task.save(update_fields=['metadata'])
                        
                        # Create history entry
                        TaskHistory.objects.create(
                            task=task,
                            action='marked_overdue',
                            user=task.created_by,
                            details={
                                'due_date': task.due_date.isoformat(),
                                'overdue_duration': str(current_time - task.due_date),
                                'priority': task.priority
                            }
                        )
                    
                    # Send overdue notifications
                    notification_task = send_task_notification.delay(
                        task_id=task.id,
                        notification_type='overdue',
                        context={
                            'overdue_duration': current_time - task.due_date,
                            'priority_escalation': task.priority == 'high'
                        }
                    )
                    
                    overdue_results.append({
                        'task_id': task.id,
                        'title': task.title,
                        'due_date': task.due_date.isoformat(),
                        'overdue_duration': str(current_time - task.due_date),
                        'assignees_count': task.assigned_to.count(),
                        'notification_task_id': notification_task.id,
                        'status': 'processed'
                    })
                else:
                    overdue_results.append({
                        'task_id': task.id,
                        'title': task.title,
                        'status': 'already_flagged'
                    })
                    
            except Exception as task_error:
                logger.error(f"Failed to process overdue task {task.id}: {task_error}")
                overdue_results.append({
                    'task_id': task.id,
                    'title': task.title,
                    'status': 'error',
                    'error': str(task_error)
                })
        
        result = {
            'check_time': current_time.isoformat(),
            'total_overdue_tasks': len(overdue_results),
            'newly_flagged_tasks': sum(
                1 for r in overdue_results if r['status'] == 'processed'
            ),
            'already_flagged_tasks': sum(
                1 for r in overdue_results if r['status'] == 'already_flagged'
            ),
            'processing_errors': sum(
                1 for r in overdue_results if r['status'] == 'error'
            ),
            'results': overdue_results
        }
        
        logger.info(f"Overdue task check completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Overdue task check failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=300)
        
        raise


@shared_task(bind=True, max_retries=2)
def cleanup_archived_tasks(self, days_threshold: int = 30) -> Dict[str, Any]:
    """
    Delete archived tasks older than specified threshold.
    
    Args:
        days_threshold: Number of days after which archived tasks are deleted
        
    Returns:
        Dict with cleanup results
    """
    try:
        logger.info(f"Starting cleanup of archived tasks older than {days_threshold} days")
        
        cutoff_date = timezone.now() - timedelta(days=days_threshold)
        
        # Find archived tasks to delete
        tasks_to_delete = Task.objects.filter(
            is_archived=True,
            updated_at__lt=cutoff_date
        ).select_related('created_by')
        
        deletion_results = []
        
        # Process deletion in batches to avoid memory issues
        batch_size = 100
        total_deleted = 0
        
        while True:
            batch = list(tasks_to_delete[:batch_size])
            if not batch:
                break
            
            batch_ids = [task.id for task in batch]
            
            try:
                with transaction.atomic():
                    # Delete related objects first
                    Comment.objects.filter(task_id__in=batch_ids).delete()
                    TaskHistory.objects.filter(task_id__in=batch_ids).delete()
                    
                    # Delete tasks
                    deleted_count = Task.objects.filter(id__in=batch_ids).delete()[0]
                    
                    deletion_results.extend([
                        {
                            'task_id': task.id,
                            'title': task.title,
                            'archived_date': task.updated_at.isoformat(),
                            'status': 'deleted'
                        }
                        for task in batch
                    ])
                    
                    total_deleted += deleted_count
                    
            except Exception as batch_error:
                logger.error(f"Failed to delete batch: {batch_error}")
                deletion_results.extend([
                    {
                        'task_id': task.id,
                        'title': task.title,
                        'status': 'error',
                        'error': str(batch_error)
                    }
                    for task in batch
                ])
        
        # Cache cleanup statistics
        cache_key = 'task_cleanup_stats'
        cleanup_stats = {
            'last_cleanup': timezone.now().isoformat(),
            'tasks_deleted': total_deleted,
            'cutoff_date': cutoff_date.isoformat()
        }
        cache.set(cache_key, cleanup_stats, timeout=86400)  # 24 hours
        
        result = {
            'cleanup_date': timezone.now().isoformat(),
            'cutoff_date': cutoff_date.isoformat(),
            'days_threshold': days_threshold,
            'total_tasks_deleted': total_deleted,
            'successful_deletions': sum(
                1 for r in deletion_results if r['status'] == 'deleted'
            ),
            'failed_deletions': sum(
                1 for r in deletion_results if r['status'] == 'error'
            ),
            'results': deletion_results
        }
        
        logger.info(f"Archived task cleanup completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Archived task cleanup failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=600)  # 10 minutes
        
        raise


# =============================================================================
# ANALYTICS AND REPORTING TASKS
# =============================================================================

@shared_task(bind=True, max_retries=2)
def calculate_team_metrics(self, team_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Calculate team performance metrics and update cached statistics.
    
    Args:
        team_id: Specific team ID to calculate metrics for, or None for all teams
        
    Returns:
        Dict with calculated metrics
    """
    try:
        logger.info(f"Calculating team metrics for team_id: {team_id or 'all teams'}")
        
        # Get teams to process
        if team_id:
            teams = Team.objects.filter(id=team_id, is_active=True)
        else:
            teams = Team.objects.filter(is_active=True)
        
        teams = teams.prefetch_related('members')
        
        metrics_results = []
        current_time = timezone.now()
        thirty_days_ago = current_time - timedelta(days=30)
        
        for team in teams:
            try:
                team_members = list(team.members.all())
                member_ids = [member.id for member in team_members]
                
                # Get team tasks from last 30 days
                team_tasks = Task.objects.filter(
                    Q(created_by__in=member_ids) | Q(assigned_to__in=member_ids),
                    created_at__gte=thirty_days_ago,
                    is_archived=False
                ).distinct().select_related('created_by').prefetch_related('assigned_to')
                
                # Calculate basic metrics
                total_tasks = team_tasks.count()
                completed_tasks = team_tasks.filter(status='completed').count()
                in_progress_tasks = team_tasks.filter(status='in_progress').count()
                pending_tasks = team_tasks.filter(status='pending').count()
                overdue_tasks = team_tasks.filter(
                    due_date__lt=current_time,
                    status__in=['pending', 'in_progress']
                ).count()
                
                # Calculate completion rate
                completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
                
                # Calculate average task duration
                completed_with_hours = team_tasks.filter(
                    status='completed',
                    actual_hours__isnull=False
                )
                
                avg_completion_time = float(
                    completed_with_hours.aggregate(avg=Avg('actual_hours'))['avg'] or 0
                )
                
                # Calculate team velocity (tasks completed per day)
                velocity = completed_tasks / 30.0  # tasks per day over 30 days
                
                # Calculate workload distribution
                workload_distribution = {}
                for member in team_members:
                    member_tasks = team_tasks.filter(
                        Q(created_by=member) | Q(assigned_to=member)
                    ).distinct().count()
                    workload_distribution[member.id] = {
                        'user_id': member.id,
                        'username': member.username,
                        'task_count': member_tasks,
                        'percentage': (member_tasks / total_tasks * 100) if total_tasks > 0 else 0
                    }
                
                # Calculate efficiency metrics
                estimated_vs_actual = completed_with_hours.aggregate(
                    total_estimated=Sum('estimated_hours'),
                    total_actual=Sum('actual_hours')
                )
                
                efficiency_ratio = 1.0
                if (estimated_vs_actual['total_actual'] and 
                    estimated_vs_actual['total_estimated']):
                    efficiency_ratio = float(
                        estimated_vs_actual['total_estimated'] / 
                        estimated_vs_actual['total_actual']
                    )
                
                # Priority distribution
                priority_distribution = {
                    priority: team_tasks.filter(priority=priority).count()
                    for priority in ['low', 'medium', 'high', 'critical']
                }
                
                # Compile team metrics
                team_metrics = {
                    'team_id': team.id,
                    'team_name': team.name,
                    'calculation_period': {
                        'start_date': thirty_days_ago.isoformat(),
                        'end_date': current_time.isoformat()
                    },
                    'basic_metrics': {
                        'total_tasks': total_tasks,
                        'completed_tasks': completed_tasks,
                        'in_progress_tasks': in_progress_tasks,
                        'pending_tasks': pending_tasks,
                        'overdue_tasks': overdue_tasks,
                        'completion_rate': round(completion_rate, 2)
                    },
                    'performance_metrics': {
                        'average_completion_time_hours': round(avg_completion_time, 2),
                        'team_velocity_tasks_per_day': round(velocity, 2),
                        'efficiency_ratio': round(efficiency_ratio, 2)
                    },
                    'workload_distribution': workload_distribution,
                    'priority_distribution': priority_distribution,
                    'team_size': len(team_members)
                }
                
                # Cache team metrics
                cache_key = f'team_metrics_{team.id}'
                cache.set(cache_key, team_metrics, timeout=3600)  # 1 hour
                
                metrics_results.append({
                    'team_id': team.id,
                    'status': 'success',
                    'metrics': team_metrics
                })
                
            except Exception as team_error:
                logger.error(f"Failed to calculate metrics for team {team.id}: {team_error}")
                metrics_results.append({
                    'team_id': team.id,
                    'status': 'error',
                    'error': str(team_error)
                })
        
        result = {
            'calculation_time': current_time.isoformat(),
            'total_teams_processed': len(teams),
            'successful_calculations': sum(
                1 for r in metrics_results if r['status'] == 'success'
            ),
            'failed_calculations': sum(
                1 for r in metrics_results if r['status'] == 'error'
            ),
            'results': metrics_results
        }
        
        logger.info(f"Team metrics calculation completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Team metrics calculation failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=300)
        
        raise


@shared_task(bind=True, max_retries=3)
def export_task_data(
    self,
    export_format: str = 'json',
    filters: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Export task data in specified format with optional filtering.
    
    Args:
        export_format: Export format ('json', 'csv', 'excel')
        filters: Optional filters to apply to task queryset
        user_id: User ID requesting the export (for access control)
        
    Returns:
        Dict with export results and file information
    """
    try:
        logger.info(f"Starting task data export: format={export_format}, user_id={user_id}")
        
        # Build queryset with filters
        queryset = Task.objects.select_related(
            'created_by', 'parent_task'
        ).prefetch_related(
            'assigned_to', 'tags', 'comments'
        )
        
        # Apply filters if provided
        if filters:
            if 'status' in filters:
                queryset = queryset.filter(status__in=filters['status'])
            if 'priority' in filters:
                queryset = queryset.filter(priority__in=filters['priority'])
            if 'created_after' in filters:
                queryset = queryset.filter(created_at__gte=filters['created_after'])
            if 'created_before' in filters:
                queryset = queryset.filter(created_at__lte=filters['created_before'])
            if 'assigned_to' in filters:
                queryset = queryset.filter(assigned_to__in=filters['assigned_to'])
            if 'tags' in filters:
                queryset = queryset.filter(tags__in=filters['tags'])
        
        # Limit results for performance
        max_export_limit = getattr(settings, 'MAX_EXPORT_LIMIT', 10000)
        tasks = queryset[:max_export_limit]
        
        export_data = []
        for task in tasks:
            task_data = {
                'id': task.id,
                'title': task.title,
                'description': task.description,
                'status': task.status,
                'priority': task.priority,
                'due_date': task.due_date.isoformat() if task.due_date else None,
                'estimated_hours': float(task.estimated_hours) if task.estimated_hours else None,
                'actual_hours': float(task.actual_hours) if task.actual_hours else None,
                'created_by': task.created_by.username if task.created_by else None,
                'assigned_to': [user.username for user in task.assigned_to.all()],
                'tags': [tag.name for tag in task.tags.all()],
                'parent_task_id': task.parent_task.id if task.parent_task else None,
                'metadata': task.metadata,
                'created_at': task.created_at.isoformat(),
                'updated_at': task.updated_at.isoformat(),
                'is_archived': task.is_archived,
                'comments_count': task.comments.count()
            }
            export_data.append(task_data)
        
        # Generate export file based on format
        import json
        import csv
        import io
        from datetime import datetime
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'tasks_export_{timestamp}.{export_format}'
        
        if export_format == 'json':
            file_content = json.dumps(export_data, indent=2, ensure_ascii=False)
            content_type = 'application/json'
            
        elif export_format == 'csv':
            output = io.StringIO()
            if export_data:
                fieldnames = export_data[0].keys()
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                
                for row in export_data:
                    # Convert complex fields to strings for CSV
                    csv_row = row.copy()
                    csv_row['assigned_to'] = ', '.join(row['assigned_to'])
                    csv_row['tags'] = ', '.join(row['tags'])
                    csv_row['metadata'] = json.dumps(row['metadata'])
                    writer.writerow(csv_row)
            
            file_content = output.getvalue()
            content_type = 'text/csv'
            
        else:
            raise ValueError(f"Unsupported export format: {export_format}")
        
        # Store export file (in a real implementation, you'd save to cloud storage)
        # For now, we'll just return the content length and metadata
        export_info = {
            'filename': filename,
            'format': export_format,
            'content_type': content_type,
            'size_bytes': len(file_content.encode('utf-8')),
            'record_count': len(export_data),
            'exported_at': timezone.now().isoformat(),
            'filters_applied': filters or {},
            'user_id': user_id
        }
        
        # Cache export info for download retrieval
        cache_key = f'export_{timestamp}_{user_id}'
        cache.set(cache_key, {
            'info': export_info,
            'content': file_content
        }, timeout=3600)  # 1 hour
        
        result = {
            'export_id': f'{timestamp}_{user_id}',
            'export_info': export_info,
            'status': 'completed'
        }
        
        logger.info(f"Task data export completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Task data export failed: {exc}")
        
        if self.request.retries < self.max_retries:
            retry_delay = 60 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=retry_delay)
        
        raise


# =============================================================================
# WORKFLOW PROCESSING TASKS
# =============================================================================

@shared_task(bind=True, max_retries=3)
def process_task_workflow(
    self,
    task_id: int,
    workflow_event: str,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Process workflow rules for a specific task event.
    
    Args:
        task_id: ID of the task triggering the workflow
        workflow_event: Type of event ('created', 'assigned', 'status_changed', etc.)
        context: Additional context data for workflow processing
        
    Returns:
        Dict with workflow processing results
    """
    try:
        from apps.workflows.engines import WorkflowEngine
        
        logger.info(f"Processing workflow for task {task_id}, event: {workflow_event}")
        
        # Get task with related data
        task = Task.objects.select_related(
            'created_by', 'parent_task'
        ).prefetch_related(
            'assigned_to', 'tags'
        ).get(id=task_id)
        
        # Initialize workflow engine
        workflow_engine = WorkflowEngine()
        
        # Get applicable workflow rules
        workflow_rules = WorkflowRule.objects.filter(
            event_type=workflow_event,
            is_active=True
        ).order_by('priority')
        
        workflow_results = []
        
        for rule in workflow_rules:
            try:
                # Check if rule conditions are met
                if workflow_engine.evaluate_conditions(task, rule, context):
                    # Execute rule actions
                    action_results = workflow_engine.execute_actions(task, rule, context)
                    
                    workflow_results.append({
                        'rule_id': rule.id,
                        'rule_name': rule.name,
                        'status': 'executed',
                        'actions_performed': action_results
                    })
                    
                    # Create history entry
                    TaskHistory.objects.create(
                        task=task,
                        action=f'workflow_rule_executed',
                        user=task.created_by,
                        details={
                            'rule_id': rule.id,
                            'rule_name': rule.name,
                            'event_type': workflow_event,
                            'actions_performed': action_results,
                            'context': context or {}
                        }
                    )
                else:
                    workflow_results.append({
                        'rule_id': rule.id,
                        'rule_name': rule.name,
                        'status': 'conditions_not_met'
                    })
                    
            except Exception as rule_error:
                logger.error(f"Failed to process workflow rule {rule.id}: {rule_error}")
                workflow_results.append({
                    'rule_id': rule.id,
                    'rule_name': rule.name,
                    'status': 'error',
                    'error': str(rule_error)
                })
        
        result = {
            'task_id': task_id,
            'workflow_event': workflow_event,
            'total_rules_evaluated': len(workflow_rules),
            'rules_executed': sum(
                1 for r in workflow_results if r['status'] == 'executed'
            ),
            'rules_skipped': sum(
                1 for r in workflow_results if r['status'] == 'conditions_not_met'
            ),
            'rule_errors': sum(
                1 for r in workflow_results if r['status'] == 'error'
            ),
            'workflow_results': workflow_results,
            'processed_at': timezone.now().isoformat()
        }
        
        logger.info(f"Workflow processing completed: {result}")
        return result
        
    except Task.DoesNotExist:
        error_msg = f"Task with ID {task_id} does not exist"
        logger.error(error_msg)
        raise TaskProcessingError(error_msg)
        
    except Exception as exc:
        logger.error(f"Workflow processing failed: {exc}")
        
        if self.request.retries < self.max_retries:
            retry_delay = 60 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=retry_delay)
        
        raise TaskProcessingError(f"Max retries exceeded: {exc}")


@shared_task(bind=True, max_retries=2)
def process_pending_workflows(self) -> Dict[str, Any]:
    """
    Process all pending workflow events in the system.
    
    Returns:
        Dict with pending workflow processing results
    """
    try:
        logger.info("Processing pending workflow events")
        
        # Get tasks with pending workflow events
        # In a real implementation, you might have a WorkflowEvent model
        # For now, we'll process tasks that have been recently updated
        recent_time = timezone.now() - timedelta(minutes=5)
        
        recently_updated_tasks = Task.objects.filter(
            updated_at__gte=recent_time,
            is_archived=False
        ).select_related('created_by')
        
        workflow_jobs = []
        
        for task in recently_updated_tasks:
            # Determine what workflow events to trigger based on task state
            workflow_events = []
            
            # Check task history to determine what changed
            recent_history = TaskHistory.objects.filter(
                task=task,
                created_at__gte=recent_time
            ).order_by('-created_at')
            
            for history_entry in recent_history:
                if history_entry.action == 'status_changed':
                    workflow_events.append('status_changed')
                elif history_entry.action == 'assigned':
                    workflow_events.append('assigned')
                elif history_entry.action == 'created':
                    workflow_events.append('created')
            
            # Create workflow processing tasks
            for event in set(workflow_events):  # Remove duplicates
                workflow_job = process_task_workflow.delay(
                    task_id=task.id,
                    workflow_event=event,
                    context={
                        'triggered_by': 'pending_workflow_processor',
                        'batch_processing': True
                    }
                )
                workflow_jobs.append({
                    'task_id': task.id,
                    'event': event,
                    'job_id': workflow_job.id
                })
        
        result = {
            'processing_time': timezone.now().isoformat(),
            'tasks_processed': len(recently_updated_tasks),
            'workflow_jobs_created': len(workflow_jobs),
            'jobs': workflow_jobs
        }
        
        logger.info(f"Pending workflow processing completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Pending workflow processing failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=300)
        
        raise


# =============================================================================
# UTILITY AND MAINTENANCE TASKS
# =============================================================================

@shared_task(bind=True)
def health_check(self) -> Dict[str, Any]:
    """
    Perform system health checks for monitoring purposes.
    
    Returns:
        Dict with health check results
    """
    try:
        health_results = {
            'timestamp': timezone.now().isoformat(),
            'celery_worker': 'healthy',
            'database_connection': 'unknown',
            'cache_connection': 'unknown',
            'task_counts': {}
        }
        
        # Test database connection
        try:
            total_tasks = Task.objects.count()
            health_results['database_connection'] = 'healthy'
            health_results['task_counts']['total_tasks'] = total_tasks
        except Exception as db_error:
            health_results['database_connection'] = f'error: {str(db_error)}'
        
        # Test cache connection
        try:
            cache.set('health_check', 'test', timeout=60)
            cached_value = cache.get('health_check')
            if cached_value == 'test':
                health_results['cache_connection'] = 'healthy'
            else:
                health_results['cache_connection'] = 'error: cache test failed'
        except Exception as cache_error:
            health_results['cache_connection'] = f'error: {str(cache_error)}'
        
        # Get task status counts
        try:
            status_counts = Task.objects.values('status').annotate(
                count=Count('id')
            ).order_by('status')
            
            health_results['task_counts']['by_status'] = {
                item['status']: item['count'] for item in status_counts
            }
        except Exception:
            pass
        
        return health_results
        
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        return {
            'timestamp': timezone.now().isoformat(),
            'celery_worker': f'error: {str(exc)}',
            'database_connection': 'unknown',
            'cache_connection': 'unknown'
        }


@shared_task(bind=True, max_retries=1)
def optimize_database(self) -> Dict[str, Any]:
    """
    Perform database optimization tasks.
    
    Returns:
        Dict with optimization results
    """
    try:
        from django.db import connection
        
        logger.info("Starting database optimization")
        
        optimization_results = {
            'timestamp': timezone.now().isoformat(),
            'operations_performed': [],
            'statistics': {}
        }
        
        with connection.cursor() as cursor:
            # Analyze table statistics (PostgreSQL specific)
            if 'postgresql' in settings.DATABASES['default']['ENGINE']:
                # Update table statistics
                cursor.execute("ANALYZE;")
                optimization_results['operations_performed'].append('analyze_tables')
                
                # Get table sizes
                cursor.execute("""
                    SELECT schemaname, tablename, 
                           pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                    FROM pg_tables 
                    WHERE schemaname = 'public'
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                    LIMIT 10;
                """)
                
                table_sizes = cursor.fetchall()
                optimization_results['statistics']['largest_tables'] = [
                    {'schema': row[0], 'table': row[1], 'size': row[2]}
                    for row in table_sizes
                ]
        
        # Clean up expired cache entries
        try:
            cache.clear()
            optimization_results['operations_performed'].append('cache_cleanup')
        except Exception:
            pass
        
        logger.info(f"Database optimization completed: {optimization_results}")
        return optimization_results
        
    except Exception as exc:
        logger.error(f"Database optimization failed: {exc}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=1800)  # 30 minutes
        
        raise


# =============================================================================
# TASK COMPOSITION AND CHAINS
# =============================================================================

@shared_task
def process_task_lifecycle_chain(task_id: int) -> str:
    """
    Process a complete task lifecycle using Celery chains.
    
    Args:
        task_id: ID of the task to process
        
    Returns:
        Chain result ID
    """
    # Create a chain of tasks for complete lifecycle processing
    lifecycle_chain = chain(
        send_task_notification.s(task_id, 'created'),
        process_task_workflow.s(task_id, 'created'),
        calculate_team_metrics.s()
    )
    
    result = lifecycle_chain.apply_async()
    return result.id


@shared_task
def generate_comprehensive_report() -> str:
    """
    Generate a comprehensive system report using chord pattern.
    
    Returns:
        Chord result ID
    """
    # Create a chord: multiple tasks followed by a callback
    report_chord = chord([
        calculate_team_metrics.s(),
        check_overdue_tasks.s(),
        health_check.s()
    ])(compile_system_report.s())
    
    return report_chord.id


@shared_task
def compile_system_report(individual_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compile individual report results into a comprehensive system report.
    
    Args:
        individual_results: Results from individual report tasks
        
    Returns:
        Compiled system report
    """
    try:
        compiled_report = {
            'report_generated_at': timezone.now().isoformat(),
            'individual_results': individual_results,
            'summary': {
                'total_components_checked': len(individual_results),
                'successful_components': sum(
                    1 for result in individual_results 
                    if isinstance(result, dict) and 'error' not in result
                ),
                'failed_components': sum(
                    1 for result in individual_results 
                    if not isinstance(result, dict) or 'error' in result
                )
            }
        }
        
        # Cache the compiled report
        cache_key = 'latest_system_report'
        cache.set(cache_key, compiled_report, timeout=3600)  # 1 hour
        
        logger.info(f"System report compiled successfully: {compiled_report['summary']}")
        return compiled_report
        
    except Exception as exc:
        logger.error(f"Failed to compile system report: {exc}")
        raise
