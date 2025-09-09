"""
Common mixins for views and models in the task management system.

Provides reusable functionality that can be mixed into various classes.
"""

from typing import Any, Dict, List, Optional

from django.db.models import QuerySet
from django.http import HttpRequest
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.request import Request

from .serializers import BulkActionSerializer


class AuditModelMixin:
    """
    Mixin to automatically set created_by and updated_by fields.
    """

    def perform_create(self, serializer) -> None:
        """Set created_by when creating an object."""
        if hasattr(serializer.Meta.model, 'created_by'):
            serializer.save(created_by=self.request.user)
        else:
            serializer.save()

    def perform_update(self, serializer) -> None:
        """Set updated_by when updating an object."""
        if hasattr(serializer.Meta.model, 'updated_by'):
            serializer.save(updated_by=self.request.user)
        else:
            serializer.save()


class BulkActionMixin:
    """
    Mixin that provides bulk actions for viewsets.
    """

    bulk_actions = ['delete', 'archive', 'unarchive']  # Override in subclasses

    @action(detail=False, methods=['post'])
    def bulk_action(self, request: Request) -> Response:
        """Perform bulk actions on multiple objects."""
        serializer = self.get_bulk_action_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_name = serializer.validated_data['action']
        object_ids = serializer.validated_data['ids']

        if action_name not in self.bulk_actions:
            return Response(
                {'detail': f'Action "{action_name}" is not supported'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get objects
        queryset = self.get_queryset().filter(id__in=object_ids)
        objects = list(queryset)

        if len(objects) != len(object_ids):
            return Response(
                {'detail': 'Some objects were not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Perform action
        result = self.perform_bulk_action(action_name, objects, request.user)

        return Response({
            'detail': f'Successfully performed {action_name} on {len(objects)} objects',
            'affected_count': len(objects),
            'result': result
        })

    def get_bulk_action_serializer(self, *args, **kwargs) -> BulkActionSerializer:
        """Get serializer for bulk actions."""
        class CustomBulkActionSerializer(BulkActionSerializer):
            action_choices = [(action, action.title()) for action in self.bulk_actions]

        return CustomBulkActionSerializer(*args, **kwargs)

    def perform_bulk_action(self, action: str, objects: List[Any], user: User) -> Dict[str, Any]:
        """
        Perform the actual bulk action.
        Override in subclasses to implement custom logic.
        """
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if user and not isinstance(user, User):
            raise ValueError("user must be an instance of User model")

        results = {'success': [], 'errors': []}

        for obj in objects:
            try:
                if action == 'delete':
                    if hasattr(obj, 'soft_delete'):
                        obj.soft_delete(user=user)
                    else:
                        obj.delete()
                elif action == 'archive':
                    if hasattr(obj, 'archive'):
                        obj.archive(user=user)
                elif action == 'unarchive':
                    if hasattr(obj, 'unarchive'):
                        obj.unarchive()

                results['success'].append(str(obj.id))
            except Exception as e:
                results['errors'].append({
                    'id': str(obj.id),
                    'error': str(e)
                })

        return results


class FilterMixin:
    """
    Mixin that provides common filtering functionality.
    """

    def get_queryset(self) -> QuerySet:
        """Apply common filters to queryset."""
        queryset = super().get_queryset()

        # Apply user filter if available
        if self.request.query_params.get('user'):
            user_id = self.request.query_params.get('user')
            if hasattr(queryset.model, 'created_by'):
                queryset = queryset.filter(created_by_id=user_id)

        # Apply date range filters
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if date_from and hasattr(queryset.model, 'created_at'):
            queryset = queryset.filter(created_at__gte=date_from)

        if date_to and hasattr(queryset.model, 'created_at'):
            queryset = queryset.filter(created_at__lte=date_to)

        # Apply search filter
        search = self.request.query_params.get('search')
        if search:
            queryset = self.apply_search_filter(queryset, search)

        return queryset

    def apply_search_filter(self, queryset: QuerySet, search_term: str) -> QuerySet:
        """
        Apply search filter to queryset.
        Override in subclasses to implement model-specific search.
        """
        return queryset


class CacheResponseMixin:
    """
    Mixin that provides response caching functionality.
    """

    cache_timeout = 300  # 5 minutes default
    cache_key_prefix = 'api_cache'

    def get_cache_key(self, request: Request) -> str:
        """Generate cache key for the request."""
        from django.utils.encoding import force_str
        from django.utils.http import urlencode

        key_parts = [
            self.cache_key_prefix,
            self.__class__.__name__,
            request.path,
            urlencode(sorted(request.query_params.items()))
        ]

        return ':'.join(force_str(part) for part in key_parts if part)

    def get_cached_response(self, request: Request) -> Optional[Response]:
        """Get cached response if available."""
        from django.core.cache import cache

        if request.method != 'GET':
            return None

        cache_key = self.get_cache_key(request)
        return cache.get(cache_key)

    def set_cached_response(self, request: Request, response: Response) -> None:
        """Cache the response."""
        from django.core.cache import cache

        if request.method != 'GET' or response.status_code != 200:
            return

        cache_key = self.get_cache_key(request)
        cache.set(cache_key, response, self.cache_timeout)


class RateLimitMixin:
    """
    Mixin that provides rate limiting functionality.
    """

    rate_limit = '100/hour'  # Default rate limit
    rate_limit_scope = 'default'

    def check_throttles(self, request: Request) -> None:
        """Check rate limits before processing request."""
        # This would integrate with a rate limiting system
        # For now, it's a placeholder for the interface
        pass


class ExportMixin:
    """
    Mixin that provides data export functionality.
    """

    export_formats = ['csv', 'xlsx', 'json']

    @action(detail=False, methods=['get'])
    def export(self, request: Request) -> Response:
        """Export data in requested format."""
        export_format = request.query_params.get('format', 'csv')

        if export_format not in self.export_formats:
            return Response(
                {'detail': f'Format "{export_format}" is not supported'},
                status=status.HTTP_400_BAD_REQUEST
            )

        queryset = self.filter_queryset(self.get_queryset())

        if export_format == 'csv':
            return self.export_csv(queryset)
        elif export_format == 'xlsx':
            return self.export_xlsx(queryset)
        elif export_format == 'json':
            return self.export_json(queryset)

    def export_csv(self, queryset: QuerySet) -> Response:
        """Export data as CSV."""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="export.csv"'

        writer = csv.writer(response)

        # Write headers (implement in subclasses)
        headers = self.get_export_headers()
        writer.writerow(headers)

        # Write data
        for obj in queryset:
            row = self.get_export_row(obj)
            writer.writerow(row)

        return response

    def export_xlsx(self, queryset: QuerySet) -> Response:
        """Export data as Excel file."""
        # This would require openpyxl or xlsxwriter
        # Placeholder implementation
        return Response(
            {'detail': 'Excel export not implemented'},
            status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def export_json(self, queryset: QuerySet) -> Response:
        """Export data as JSON."""
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def get_export_headers(self) -> List[str]:
        """Get headers for export. Override in subclasses."""
        return ['id', 'created_at', 'updated_at']

    def get_export_row(self, obj: Any) -> List[Any]:
        """Get row data for export. Override in subclasses."""
        return [obj.id, obj.created_at, obj.updated_at]


class StatisticsMixin:
    """
    Mixin that provides statistics endpoints.
    """

    @action(detail=False, methods=['get'])
    def statistics(self, request: Request) -> Response:
        """Get statistics for the model."""
        queryset = self.filter_queryset(self.get_queryset())
        stats = self.calculate_statistics(queryset)
        return Response(stats)

    def calculate_statistics(self, queryset: QuerySet) -> Dict[str, Any]:
        """
        Calculate statistics for the queryset.
        Override in subclasses to implement model-specific statistics.
        """
        return {
            'total_count': queryset.count(),
            'active_count': queryset.filter(is_archived=False).count() if hasattr(queryset.model, 'is_archived') else queryset.count(),
        }


class VersioningMixin:
    """
    Mixin that provides versioning support for models.
    """

    def perform_update(self, serializer) -> None:
        """Increment version on update."""
        instance = serializer.instance

        if hasattr(instance, 'version'):
            instance.increment_version()

        super().perform_update(serializer)


class MultiTenantMixin:
    """
    Mixin that provides multi-tenant functionality.
    """

    def get_queryset(self) -> QuerySet:
        """Filter queryset by tenant."""
        queryset = super().get_queryset()

        # This assumes a tenant field exists on the model
        if hasattr(self.request.user, 'tenant') and hasattr(queryset.model, 'tenant'):
            queryset = queryset.filter(tenant=self.request.user.tenant)

        return queryset

    def perform_create(self, serializer) -> None:
        """Set tenant on creation."""
        if hasattr(self.request.user, 'tenant') and hasattr(serializer.Meta.model, 'tenant'):
            serializer.save(tenant=self.request.user.tenant)
        else:
            super().perform_create(serializer)
