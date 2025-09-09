"""
Common middleware for enterprise task management system.
"""
import logging
import time
import uuid
from typing import Callable, Optional

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


class RequestTrackingMiddleware(MiddlewareMixin):
    """
    Middleware to track request performance and add correlation IDs.
    """

    def process_request(self, request: HttpRequest) -> None:
        """Add correlation ID and start time to request."""
        request.correlation_id = str(uuid.uuid4())
        request.start_time = time.time()

        # Log request start
        logger.info(
            "Request started",
            extra={
                "correlation_id": request.correlation_id,
                "method": request.method,
                "path": request.path,
                "user_id": getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
                "remote_addr": self._get_client_ip(request),
            }
        )

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Log response and add correlation ID to headers."""
        if hasattr(request, 'correlation_id'):
            response['X-Correlation-ID'] = request.correlation_id

            # Calculate request duration
            duration = None
            if hasattr(request, 'start_time'):
                duration = time.time() - request.start_time

            # Log response
            logger.info(
                "Request completed",
                extra={
                    "correlation_id": request.correlation_id,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2) if duration else None,
                }
            )

        return response

    @staticmethod
    def _get_client_ip(request: HttpRequest) -> Optional[str]:
        """Get client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to add security headers to responses.
    """

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Add security headers to response."""
        security_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
        }

        # Only add HSTS in production with HTTPS
        if settings.DEBUG is False and request.is_secure():
            security_headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        for header, value in security_headers.items():
            if header not in response:
                response[header] = value

        return response


class RateLimitMiddleware(MiddlewareMixin):
    """
    Simple rate limiting middleware using cache backend.
    """

    def __init__(self, get_response: Callable) -> None:
        super().__init__(get_response)
        self.rate_limit = getattr(settings, 'RATE_LIMIT_REQUESTS', 100)
        self.rate_limit_window = getattr(settings, 'RATE_LIMIT_WINDOW', 3600)  # 1 hour

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Check if request should be rate limited."""
        # Skip rate limiting for exempt paths
        exempt_paths = getattr(settings, 'RATE_LIMIT_EXEMPT_PATHS', [])
        if any(request.path.startswith(path) for path in exempt_paths):
            return None

        # Get client identifier
        client_id = self._get_client_identifier(request)
        cache_key = f"rate_limit:{client_id}"

        # Get current request count
        current_requests = cache.get(cache_key, 0)

        if current_requests >= self.rate_limit:
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "client_id": client_id,
                    "current_requests": current_requests,
                    "limit": self.rate_limit,
                }
            )
            return HttpResponse(
                "Rate limit exceeded. Please try again later.",
                status=429,
                content_type="text/plain"
            )

        # Increment request count
        try:
            cache.set(cache_key, current_requests + 1, self.rate_limit_window)
        except Exception as e:
            logger.error(f"Failed to update rate limit cache: {e}")

        return None

    def _get_client_identifier(self, request: HttpRequest) -> str:
        """Get client identifier for rate limiting."""
        if hasattr(request, 'user') and request.user.is_authenticated:
            return f"user:{request.user.id}"

        # Fall back to IP address
        return f"ip:{RequestTrackingMiddleware._get_client_ip(request)}"


class DatabaseRoutingMiddleware(MiddlewareMixin):
    """
    Middleware for database routing hints based on request type.
    """

    def process_request(self, request: HttpRequest) -> None:
        """Add database routing hints to request."""
        # Mark read-only requests for potential read replica routing
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            request._db_routing_hint = 'read'
        else:
            request._db_routing_hint = 'write'


class HealthCheckMiddleware(MiddlewareMixin):
    """
    Middleware to handle health check requests without full Django processing.
    """

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Handle health check requests."""
        if request.path in ('/health/', '/healthz/', '/ping/'):
            return HttpResponse("OK", content_type="text/plain")

        return None


class MaintenanceModeMiddleware(MiddlewareMixin):
    """
    Middleware to enable maintenance mode.
    """

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Check if site is in maintenance mode."""
        if getattr(settings, 'MAINTENANCE_MODE', False):
            # Allow superusers to bypass maintenance mode
            if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_superuser:
                return None

            # Allow specific IPs to bypass maintenance mode
            allowed_ips = getattr(settings, 'MAINTENANCE_ALLOWED_IPS', [])
            client_ip = RequestTrackingMiddleware._get_client_ip(request)
            if client_ip in allowed_ips:
                return None

            return HttpResponse(
                "Site is currently under maintenance. Please try again later.",
                status=503,
                content_type="text/plain"
            )

        return None
