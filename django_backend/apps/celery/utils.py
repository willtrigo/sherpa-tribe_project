"""
Celery utilities for the Enterprise Task Management System.

This module provides comprehensive utilities for Celery task management including:
- Task result handling and monitoring
- Error handling and retry mechanisms  
- Task state management
- Performance monitoring and logging
- Task cleanup and maintenance
- Email notification utilities
- Database connection management for tasks
"""

import logging
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union

import redis
from celery import Task, current_app
from celery.exceptions import Ignore, Retry
from celery.result import AsyncResult
from celery.signals import task_failure, task_postrun, task_prerun, task_retry
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import connection, transaction
from django.template.loader import render_to_string
from django.utils import timezone

# Configure logger
logger = get_task_logger(__name__)

# Redis connection for Celery utilities
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


class TaskExecutionError(Exception):
    """Custom exception for task execution errors."""
    pass


class TaskResultManager:
    """
    Manager for handling Celery task results and states.
    
    Provides utilities for:
    - Task result storage and retrieval
    - Task state monitoring
    - Result expiration management
    """
    
    RESULT_EXPIRES = 3600  # 1 hour
    
    @classmethod
    def store_task_result(
        cls, 
        task_id: str, 
        result: Any, 
        status: str = 'SUCCESS',
        expires: Optional[int] = None
    ) -> None:
        """
        Store task result with metadata.
        
        Args:
            task_id: Unique task identifier
            result: Task execution result
            status: Task status (SUCCESS, FAILURE, PENDING, etc.)
            expires: Result expiration time in seconds
        """
        expires = expires or cls.RESULT_EXPIRES
        cache_key = f"task_result:{task_id}"
        
        result_data = {
            'result': result,
            'status': status,
            'timestamp': timezone.now().isoformat(),
            'task_id': task_id
        }
        
        cache.set(cache_key, result_data, timeout=expires)
        logger.info(f"Task result stored for {task_id} with status {status}")

    @classmethod
    def get_task_result(cls, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve task result by task ID.
        
        Args:
            task_id: Unique task identifier
            
        Returns:
            Task result data or None if not found
        """
        cache_key = f"task_result:{task_id}"
        return cache.get(cache_key)

    @classmethod
    def get_task_status(cls, task_id: str) -> str:
        """
        Get current task status.
        
        Args:
            task_id: Unique task identifier
            
        Returns:
            Task status string
        """
        result = AsyncResult(task_id, app=current_app)
        return result.status

    @classmethod
    def is_task_ready(cls, task_id: str) -> bool:
        """
        Check if task is completed (success or failure).
        
        Args:
            task_id: Unique task identifier
            
        Returns:
            True if task is completed, False otherwise
        """
        result = AsyncResult(task_id, app=current_app)
        return result.ready()


class TaskRetryManager:
    """
    Manager for task retry logic and exponential backoff.
    
    Provides sophisticated retry mechanisms with:
    - Exponential backoff
    - Maximum retry limits
    - Custom retry conditions
    - Retry state tracking
    """
    
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_COUNTDOWN = 60
    EXPONENTIAL_BASE = 2
    
    @classmethod
    def calculate_retry_countdown(cls, retry_count: int, base_countdown: int = None) -> int:
        """
        Calculate exponential backoff countdown.
        
        Args:
            retry_count: Current retry attempt number
            base_countdown: Base countdown in seconds
            
        Returns:
            Calculated countdown in seconds
        """
        base_countdown = base_countdown or cls.DEFAULT_COUNTDOWN
        return base_countdown * (cls.EXPONENTIAL_BASE ** retry_count)

    @classmethod
    def should_retry(cls, exception: Exception, retry_count: int, max_retries: int) -> bool:
        """
        Determine if task should be retried based on exception and retry count.
        
        Args:
            exception: Exception that caused task failure
            retry_count: Current retry attempt number
            max_retries: Maximum allowed retries
            
        Returns:
            True if task should be retried, False otherwise
        """
        if retry_count >= max_retries:
            return False
            
        # Don't retry for certain exception types
        non_retryable_exceptions = (
            ValueError,
            TypeError,
            AttributeError,
            KeyError
        )
        
        if isinstance(exception, non_retryable_exceptions):
            return False
            
        return True

    @classmethod
    def get_retry_key(cls, task_id: str) -> str:
        """Generate Redis key for retry tracking."""
        return f"task_retry_count:{task_id}"

    @classmethod
    def increment_retry_count(cls, task_id: str) -> int:
        """
        Increment and return retry count for task.
        
        Args:
            task_id: Unique task identifier
            
        Returns:
            Current retry count
        """
        key = cls.get_retry_key(task_id)
        count = redis_client.incr(key)
        redis_client.expire(key, 86400)  # Expire after 24 hours
        return count

    @classmethod
    def get_retry_count(cls, task_id: str) -> int:
        """
        Get current retry count for task.
        
        Args:
            task_id: Unique task identifier
            
        Returns:
            Current retry count
        """
        key = cls.get_retry_key(task_id)
        count = redis_client.get(key)
        return int(count) if count else 0


class TaskPerformanceMonitor:
    """
    Monitor and log task performance metrics.
    
    Tracks:
    - Task execution time
    - Memory usage
    - Success/failure rates
    - Queue sizes
    """
    
    @classmethod
    def log_task_performance(
        cls, 
        task_name: str, 
        duration: float, 
        success: bool,
        memory_usage: Optional[float] = None
    ) -> None:
        """
        Log task performance metrics.
        
        Args:
            task_name: Name of the executed task
            duration: Execution duration in seconds
            success: Whether task succeeded
            memory_usage: Memory usage in MB (optional)
        """
        metrics_key = f"task_metrics:{task_name}"
        
        metrics = {
            'duration': duration,
            'success': success,
            'timestamp': timezone.now().isoformat(),
            'memory_usage': memory_usage
        }
        
        # Store in Redis with expiration
        redis_client.lpush(f"{metrics_key}:history", str(metrics))
        redis_client.ltrim(f"{metrics_key}:history", 0, 999)  # Keep last 1000 entries
        redis_client.expire(f"{metrics_key}:history", 86400 * 7)  # 7 days
        
        logger.info(
            f"Task {task_name} performance: "
            f"duration={duration:.2f}s, success={success}, memory={memory_usage}MB"
        )

    @classmethod
    def get_task_metrics_summary(cls, task_name: str) -> Dict[str, Any]:
        """
        Get performance metrics summary for a task.
        
        Args:
            task_name: Name of the task
            
        Returns:
            Dictionary with performance metrics
        """
        metrics_key = f"task_metrics:{task_name}:history"
        history = redis_client.lrange(metrics_key, 0, -1)
        
        if not history:
            return {'task_name': task_name, 'total_executions': 0}
            
        total_executions = len(history)
        successful_executions = sum(
            1 for entry in history 
            if eval(entry).get('success', False)
        )
        
        durations = [
            eval(entry).get('duration', 0) 
            for entry in history
        ]
        
        return {
            'task_name': task_name,
            'total_executions': total_executions,
            'successful_executions': successful_executions,
            'success_rate': successful_executions / total_executions * 100,
            'average_duration': sum(durations) / len(durations),
            'min_duration': min(durations),
            'max_duration': max(durations)
        }


class EmailNotificationService:
    """
    Service for sending email notifications from Celery tasks.
    
    Features:
    - Template-based emails
    - HTML and text versions
    - Batch email sending
    - Email delivery tracking
    - Error handling and retries
    """
    
    DEFAULT_FROM_EMAIL = settings.DEFAULT_FROM_EMAIL
    
    @classmethod
    def send_notification_email(
        cls,
        to_emails: Union[str, List[str]],
        subject: str,
        template_name: str,
        context: Dict[str, Any],
        from_email: Optional[str] = None,
        priority: str = 'normal'
    ) -> bool:
        """
        Send notification email using template.
        
        Args:
            to_emails: Recipient email address(es)
            subject: Email subject
            template_name: Template name (without extension)
            context: Template context data
            from_email: Sender email address
            priority: Email priority ('high', 'normal', 'low')
            
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            if isinstance(to_emails, str):
                to_emails = [to_emails]
                
            from_email = from_email or cls.DEFAULT_FROM_EMAIL
            
            # Render HTML and text versions
            html_content = render_to_string(f"emails/{template_name}.html", context)
            text_content = render_to_string(f"emails/{template_name}.txt", context)
            
            # Create email message
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=to_emails
            )
            msg.attach_alternative(html_content, "text/html")
            
            # Set priority headers
            if priority == 'high':
                msg.extra_headers['X-Priority'] = '1'
                msg.extra_headers['Importance'] = 'high'
            elif priority == 'low':
                msg.extra_headers['X-Priority'] = '5'
                msg.extra_headers['Importance'] = 'low'
            
            # Send email
            msg.send()
            
            logger.info(f"Email sent successfully to {to_emails}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_emails}: {str(e)}")
            return False

    @classmethod
    def send_bulk_notifications(
        cls,
        notifications: List[Dict[str, Any]],
        batch_size: int = 50
    ) -> Dict[str, int]:
        """
        Send multiple notifications in batches.
        
        Args:
            notifications: List of notification dictionaries
            batch_size: Number of emails to send per batch
            
        Returns:
            Dictionary with success/failure counts
        """
        successful = 0
        failed = 0
        
        for i in range(0, len(notifications), batch_size):
            batch = notifications[i:i + batch_size]
            
            for notification in batch:
                success = cls.send_notification_email(**notification)
                if success:
                    successful += 1
                else:
                    failed += 1
                    
            # Small delay between batches to avoid overwhelming email server
            if i + batch_size < len(notifications):
                import time
                time.sleep(1)
        
        return {'successful': successful, 'failed': failed}


@contextmanager
def database_task_context():
    """
    Context manager for database operations in Celery tasks.
    
    Ensures proper database connection handling and transaction management.
    """
    try:
        # Ensure fresh database connection
        connection.ensure_connection()
        
        with transaction.atomic():
            yield
            
    except Exception as e:
        logger.error(f"Database error in task: {str(e)}")
        raise
    finally:
        # Close database connection
        connection.close()


def task_error_handler(func: Callable) -> Callable:
    """
    Decorator for comprehensive task error handling.
    
    Features:
    - Automatic error logging
    - Exception type categorization
    - Retry logic integration
    - Performance monitoring
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        task_start_time = timezone.now()
        task_name = func.__name__
        
        try:
            # Execute task
            result = func(self, *args, **kwargs)
            
            # Log success metrics
            duration = (timezone.now() - task_start_time).total_seconds()
            TaskPerformanceMonitor.log_task_performance(
                task_name, duration, success=True
            )
            
            # Store result
            TaskResultManager.store_task_result(
                self.request.id, result, 'SUCCESS'
            )
            
            return result
            
        except Exception as exc:
            duration = (timezone.now() - task_start_time).total_seconds()
            retry_count = TaskRetryManager.get_retry_count(self.request.id)
            
            # Log error metrics
            TaskPerformanceMonitor.log_task_performance(
                task_name, duration, success=False
            )
            
            # Log detailed error information
            logger.error(
                f"Task {task_name} failed: {str(exc)}\n"
                f"Task ID: {self.request.id}\n"
                f"Retry count: {retry_count}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            
            # Determine if should retry
            max_retries = getattr(self, 'max_retries', TaskRetryManager.DEFAULT_MAX_RETRIES)
            
            if TaskRetryManager.should_retry(exc, retry_count, max_retries):
                TaskRetryManager.increment_retry_count(self.request.id)
                countdown = TaskRetryManager.calculate_retry_countdown(retry_count)
                
                logger.info(
                    f"Retrying task {task_name} in {countdown} seconds "
                    f"(attempt {retry_count + 1}/{max_retries})"
                )
                
                raise self.retry(countdown=countdown, exc=exc)
            else:
                # Store failure result
                TaskResultManager.store_task_result(
                    self.request.id, str(exc), 'FAILURE'
                )
                
                logger.error(
                    f"Task {task_name} failed permanently after {retry_count} retries"
                )
                raise TaskExecutionError(f"Task failed permanently: {str(exc)}")
                
    return wrapper


def task_with_monitoring(
    bind: bool = True,
    max_retries: int = 3,
    default_retry_delay: int = 60
):
    """
    Decorator that combines task binding with comprehensive monitoring.
    
    Args:
        bind: Whether to bind task instance to first argument
        max_retries: Maximum number of retry attempts
        default_retry_delay: Default delay between retries in seconds
    """
    def decorator(func: Callable) -> Callable:
        # Apply Celery task decorator
        task_func = current_app.task(
            bind=bind,
            max_retries=max_retries,
            default_retry_delay=default_retry_delay
        )(func)
        
        # Apply error handling decorator
        monitored_func = task_error_handler(task_func)
        
        return monitored_func
    
    return decorator


class TaskCleanupService:
    """
    Service for cleaning up old task results and maintaining system health.
    """
    
    @classmethod
    def cleanup_expired_results(cls, max_age_hours: int = 24) -> int:
        """
        Clean up expired task results from cache.
        
        Args:
            max_age_hours: Maximum age of results to keep in hours
            
        Returns:
            Number of results cleaned up
        """
        pattern = "task_result:*"
        keys = cache.keys(pattern) if hasattr(cache, 'keys') else []
        
        cleaned_count = 0
        cutoff_time = timezone.now() - timedelta(hours=max_age_hours)
        
        for key in keys:
            result_data = cache.get(key)
            if result_data and 'timestamp' in result_data:
                result_time = datetime.fromisoformat(result_data['timestamp'])
                if result_time < cutoff_time:
                    cache.delete(key)
                    cleaned_count += 1
        
        logger.info(f"Cleaned up {cleaned_count} expired task results")
        return cleaned_count

    @classmethod
    def cleanup_retry_counters(cls, max_age_hours: int = 24) -> int:
        """
        Clean up old retry counters from Redis.
        
        Args:
            max_age_hours: Maximum age of counters to keep in hours
            
        Returns:
            Number of counters cleaned up
        """
        pattern = "task_retry_count:*"
        keys = redis_client.keys(pattern)
        
        cleaned_count = 0
        for key in keys:
            ttl = redis_client.ttl(key)
            if ttl < 0:  # Key has no expiration
                redis_client.delete(key)
                cleaned_count += 1
        
        logger.info(f"Cleaned up {cleaned_count} retry counters")
        return cleaned_count


# Signal handlers for task lifecycle monitoring
@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
    """Handle task prerun signal for monitoring."""
    logger.debug(f"Task {task.name} starting: {task_id}")


@task_postrun.connect  
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
    """Handle task postrun signal for monitoring."""
    logger.debug(f"Task {task.name} completed: {task_id} with state {state}")


@task_retry.connect
def task_retry_handler(sender=None, task_id=None, reason=None, traceback=None, einfo=None, **kwds):
    """Handle task retry signal for monitoring."""
    logger.warning(f"Task {sender.name} retrying: {task_id}, reason: {reason}")


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **kwds):
    """Handle task failure signal for monitoring."""
    logger.error(f"Task {sender.name} failed: {task_id}, exception: {exception}")
