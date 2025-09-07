FROM python:3.12-slim as base

# Set environment variables for optimal Python behavior
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Install system dependencies required for PostgreSQL and networking
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    netcat-openbsd \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create application directory
WORKDIR /app

# Development stage - optimized for development workflow
FROM base as development

# Copy requirements first for optimal Docker layer caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Create non-root user for security best practices
RUN adduser --disabled-password --gecos '' --shell /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R appuser:appuser /app/staticfiles /app/media /app/logs

# Copy and set permissions for entrypoint script
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh && \
    chown appuser:appuser /app/scripts/entrypoint.sh

USER appuser

EXPOSE 8000

# Development command with auto-reload
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Production stage - optimized for production deployment
FROM base as production

# Install production dependencies including application server
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt gunicorn whitenoise

# Copy application source code
COPY . /app/

# Create non-root user and establish proper directory structure
RUN adduser --disabled-password --gecos '' --shell /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R appuser:appuser /app/staticfiles /app/media /app/logs

# Copy and configure entrypoint script with proper permissions
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh && \
    chown appuser:appuser /app/scripts/entrypoint.sh

# Switch to non-root user for security
USER appuser

EXPOSE 8000

# Configure comprehensive health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# Set production entrypoint
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# Default production command using Gunicorn WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "sync", "--timeout", "60", "--keep-alive", "5", "--max-requests", "1000", "--max-requests-jitter", "100", "--access-logfile", "-", "--error-logfile", "-", "config.wsgi:application"]
