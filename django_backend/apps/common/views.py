from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def health_check(request):
    """
    Simple health check endpoint for Docker health checks.
    Returns basic health status with database and cache connectivity.
    """
    health_data = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'service': 'task-management-api',
        'checks': {}
    }
    
    overall_healthy = True
    
    # Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health_data['checks']['database'] = 'healthy'
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_data['checks']['database'] = 'unhealthy'
        overall_healthy = False
    
    # Cache check
    try:
        cache.set('health_test', 'ok', timeout=10)
        if cache.get('health_test') == 'ok':
            health_data['checks']['cache'] = 'healthy'
            cache.delete('health_test')
        else:
            raise Exception("Cache test failed")
    except Exception as e:
        logger.error(f"Cache health check failed: {e}")
        health_data['checks']['cache'] = 'unhealthy'
        overall_healthy = False
    
    if not overall_healthy:
        health_data['status'] = 'unhealthy'
        return JsonResponse(health_data, status=503)
    
    return JsonResponse(health_data)
