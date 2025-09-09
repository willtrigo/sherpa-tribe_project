"""
Common pagination classes for the task management system.

Provides consistent pagination across all API endpoints.
"""

from typing import Dict, Any, Optional
from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    """
    Standard pagination class with consistent page sizes.
    """

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data: list) -> Response:
        """Return paginated response with additional metadata."""
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('page_size', self.get_page_size(self.request)),
            ('current_page', self.page.number),
            ('total_pages', self.page.paginator.num_pages),
            ('results', data)
        ]))

    def get_paginated_response_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Return schema for paginated response."""
        return {
            'type': 'object',
            'properties': {
                'count': {
                    'type': 'integer',
                    'example': 123,
                    'description': 'Total number of items'
                },
                'next': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?page=4',
                    'description': 'URL for next page'
                },
                'previous': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?page=2',
                    'description': 'URL for previous page'
                },
                'page_size': {
                    'type': 'integer',
                    'example': 20,
                    'description': 'Number of items per page'
                },
                'current_page': {
                    'type': 'integer',
                    'example': 3,
                    'description': 'Current page number'
                },
                'total_pages': {
                    'type': 'integer',
                    'example': 7,
                    'description': 'Total number of pages'
                },
                'results': schema,
            },
        }


class LargeResultsSetPagination(PageNumberPagination):
    """
    Pagination class for endpoints that may return large result sets.
    """

    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500

    def get_paginated_response(self, data: list) -> Response:
        """Return paginated response with additional metadata."""
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('page_size', self.get_page_size(self.request)),
            ('current_page', self.page.number),
            ('total_pages', self.page.paginator.num_pages),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('results', data)
        ]))


class SmallResultsSetPagination(PageNumberPagination):
    """
    Pagination class for endpoints with smaller result sets.
    """

    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data: list) -> Response:
        """Return paginated response with additional metadata."""
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('page_size', self.get_page_size(self.request)),
            ('current_page', self.page.number),
            ('total_pages', self.page.paginator.num_pages),
            ('results', data)
        ]))


class OptionalPagination(StandardResultsSetPagination):
    """
    Pagination that can be disabled by setting page_size=0.
    """

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate queryset, or return None if pagination is disabled.
        """
        page_size = self.get_page_size(request)

        # If page_size is 0, disable pagination
        if page_size == 0:
            return None

        return super().paginate_queryset(queryset, request, view)

    def get_page_size(self, request):
        """Get page size from request, allowing 0 to disable pagination."""
        if self.page_size_query_param:
            try:
                page_size = int(request.query_params[self.page_size_query_param])
                if page_size == 0:
                    return 0
                if page_size > 0:
                    return min(page_size, self.max_page_size)
            except (KeyError, ValueError):
                pass

        return self.page_size


class CursorPaginationWithCount(LimitOffsetPagination):
    """
    Limit/offset pagination with total count for better performance on large datasets.
    """

    default_limit = 20
    limit_query_param = 'limit'
    offset_query_param = 'offset'
    max_limit = 100

    def get_paginated_response(self, data: list) -> Response:
        """Return paginated response with count."""
        return Response(OrderedDict([
            ('count', self.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('limit', self.get_limit(self.request)),
            ('offset', self.get_offset(self.request)),
            ('results', data)
        ]))


class NoPagination:
    """
    Pagination class that disables pagination entirely.
    """

    def paginate_queryset(self, queryset, request, view=None):
        """Return None to disable pagination."""
        return None

    def get_paginated_response(self, data):
        """Return unpaginated response."""
        return Response(data)


class DynamicPagination(StandardResultsSetPagination):
    """
    Pagination that adapts based on request parameters.
    """

    def __init__(self):
        super().__init__()
        self.pagination_styles = {
            'small': SmallResultsSetPagination(),
            'standard': StandardResultsSetPagination(),
            'large': LargeResultsSetPagination(),
            'cursor': CursorPaginationWithCount(),
            'none': NoPagination(),
        }

    def paginate_queryset(self, queryset, request, view=None):
        """Use different pagination based on request parameter."""
        style = request.query_params.get('pagination_style', 'standard')

        if style in self.pagination_styles:
            paginator = self.pagination_styles[style]
            return paginator.paginate_queryset(queryset, request, view)

        # Fallback to standard pagination
        return super().paginate_queryset(queryset, request, view)


# Convenience aliases for commonly used pagination classes
DefaultPagination = StandardResultsSetPagination
FastPagination = CursorPaginationWithCount
