FROM python:3.12-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Development stage
FROM base as development

# Copy requirements first for better caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Development command
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Production stage
FROM base as production

# Install production dependencies only
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . /app/

# create non-root user and set permissions
run adduser --disabled-password --gecos '' appuser && \
    chown -r appuser:appuser /app && \
    mkdir -p /app/staticfiles /app/media && \
    chown -r appuser:appuser /app/staticfiles /app/media

# make entrypoint executable
copy scripts/entrypoint.sh /app/scripts/entrypoint.sh
run chmod +x /app/scripts/entrypoint.sh

user appuser

expose 8000

# health check
healthcheck --interval=30s --timeout=30s --start-period=5s --retries=3 \
    cmd curl -f http://localhost:8000/health/ || exit 1

# production entrypoint
entrypoint ["/app/scripts/entrypoint.sh"]
