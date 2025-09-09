"""
Common views and mixins for the task management system.

Provides base views with common functionality and patterns.
"""

from typing import Any, Dict, Optional

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView

from .mixins import AuditModelMixin, BulkActionMixin
from .pagination import StandardResultsSetPagination
from .permissions import IsOwnerOrReadOnly


class BaseAPIView(APIView):
    """Base API view with common functionality."""

    permission_classes = [IsAuthenticated]

    def get_serializer_context(self) -> Dict[str, Any]:
        """Return the serializer context."""
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self
        }

    def handle_exception(self, exc: Exception) -> Response:
        """Handle exceptions with consistent error format."""
        response = super().handle_exception(exc)

        if hasattr(response, 'data'):
            # Ensure consistent error format
            if isinstance(response.data, dict):
                if 'detail' not in response.data:
                    response.data = {
                        'detail': 'An error occurred',
                        'code': 'error',
                        'errors': response.data
                    }

        return response


class BaseModelViewSet(AuditModelMixin, BulkActionMixin, ModelViewSet):
    """
    Base ModelViewSet with common functionality.

    Provides:
    - Audit logging (created_by, updated_by)
    - Bulk actions
    - Soft delete support
    - Standard pagination
    - Permission handling
    """

    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self) -> QuerySet:
        """Return the queryset for this view."""
        queryset = super().get_queryset()

        # Apply soft delete filter if supported
        if hasattr(self.queryset.model, 'is_deleted'):
            queryset = queryset.filter(is_deleted=False)

        # Apply archive filter if supported
        if hasattr(self.queryset.model, 'is_archived'):
            if not self._include_archived():
                queryset = queryset.filter(is_archived=False)

        return queryset

    def _include_archived(self) -> bool:
        """Check if archived objects should be included."""
        return self.request.query_params.get('include_archived', '').lower() == 'true'

    @action(detail=True, methods=['post'])
    def archive(self, request: HttpRequest, pk: Optional[str] = None) -> Response:
        """Archive an object."""
        instance = self.get_object()

        if not hasattr(instance, 'archive'):
            return Response(
                {'detail': 'This object does not support archiving'},
                status=status.HTTP_400_BAD_REQUEST
            )

        instance.archive(user=request.user)

        return Response(
            {'detail': 'Object archived successfully'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def unarchive(self, request: HttpRequest, pk: Optional[str] = None) -> Response:
        """Unarchive an object."""
        instance = self.get_object()

        if not hasattr(instance, 'unarchive'):
            return Response(
                {'detail': 'This object does not support unarchiving'},
                status=status.HTTP_400_BAD_REQUEST
            )

        instance.unarchive()

        return Response(
            {'detail': 'Object unarchived successfully'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['delete'])
    def soft_delete(self, request: HttpRequest, pk: Optional[str] = None) -> Response:
        """Soft delete an object."""
        instance = self.get_object()

        if not hasattr(instance, 'soft_delete'):
            return Response(
                {'detail': 'This object does not support soft deletion'},
                status=status.HTTP_400_BAD_REQUEST
            )

        instance.soft_delete(user=request.user)

        return Response(
            {'detail': 'Object deleted successfully'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def restore(self, request: HttpRequest, pk: Optional[str] = None) -> Response:
        """Restore a soft deleted object."""
        # Get object including deleted ones
        queryset = self.get_queryset().model.all_objects.all()
        instance = self.get_object_or_404(queryset, pk=pk)

        if not hasattr(instance, 'restore'):
            return Response(
                {'detail': 'This object does not support restoration'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not instance.is_deleted:
            return Response(
                {'detail': 'Object is not deleted'},
                status=status.HTTP_400_BAD_REQUEST
            )

        instance.restore()

        return Response(
            {'detail': 'Object restored successfully'},
            status=status.HTTP_200_OK
        )


class BaseTemplateView(LoginRequiredMixin, TemplateView):
    """Base template view with common functionality for Django templates."""

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Add dashboard-specific context data."""
        context = super().get_context_data(**kwargs)

        # Add dashboard statistics
        context.update({
            'stats': self._get_dashboard_stats(),
            'recent_activities': self._get_recent_activities(),
        })

        return context

    def _get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics."""
        # This will be implemented when task models are available
        return {
            'total_tasks': 0,
            'pending_tasks': 0,
            'completed_tasks': 0,
            'overdue_tasks': 0,
        }

    def _get_recent_activities(self) -> list:
        """Get recent activities for the dashboard."""
        # This will be implemented when activity models are available
        return []


class HealthCheckView(APIView):
    """Health check endpoint for monitoring."""

    permission_classes = []  # Public endpoint

    def get(self, request: HttpRequest) -> Response:
        """Return health status."""
        from django.db import connection
        from django.core.cache import cache
        import redis

        health_status = {
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'checks': {}
        }

        # Database check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            health_status['checks']['database'] = 'healthy'
        except Exception as e:
            health_status['checks']['database'] = f'unhealthy: {str(e)}'
            health_status['status'] = 'unhealthy'

        # Cache check
        try:
            cache.set('health_check', 'ok', 10)
            if cache.get('health_check') == 'ok':
                health_status['checks']['cache'] = 'healthy'
            else:
                health_status['checks']['cache'] = 'unhealthy: cache write/read failed'
                health_status['status'] = 'unhealthy'
        except Exception as e:
            health_status['checks']['cache'] = f'unhealthy: {str(e)}'
            health_status['status'] = 'unhealthy'

        status_code = status.HTTP_200_OK if health_status['status'] == 'healthy' else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(health_status, status=status_code)
        """Add common context data."""
        context = super().get_context_data(**kwargs)
        context.update({
            'user': self.request.user,
            'page_title': getattr(self, 'page_title', ''),
            'breadcrumbs': getattr(self, 'breadcrumbs', []),
        })
        return context


class DashboardView(BaseTemplateView):
    """Dashboard view for the task management system."""

    template_name = 'common/dashboard.html'
    page_title = 'Dashboard'

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
