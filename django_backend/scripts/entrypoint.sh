#!/bin/bash

# Professional Django Application Entrypoint
# Initializes Django application with database migrations, static files, and superuser creation

set -o errexit
set -o pipefail
set -o nounset

# =============================================================================
# CONFIGURATION AND CONSTANTS
# =============================================================================

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Default superuser configuration
readonly DEFAULT_SUPERUSER_USERNAME="admin"
readonly DEFAULT_SUPERUSER_EMAIL="admin@example.com"

# =============================================================================
# LOGGING UTILITIES
# =============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# =============================================================================
# DJANGO COMMAND EXECUTION
# =============================================================================

run_django_command() {
    local -r command="$1"
    local -r description="${2:-$command}"

    log_info "Running: python manage.py ${command}"

    if python manage.py ${command}; then
        log_info "✓ Command '${description}' completed successfully"
        return 0
    else
        log_error "✗ Command '${description}' failed"
        exit 1
    fi
}

# =============================================================================
# SUPERUSER MANAGEMENT
# =============================================================================

create_superuser_if_needed() {
    local -r admin_username="${DJANGO_SUPERUSER_USERNAME:-${DEFAULT_SUPERUSER_USERNAME}}"
    local -r admin_email="${DJANGO_SUPERUSER_EMAIL:-${DEFAULT_SUPERUSER_EMAIL}}"
    local -r admin_password="${DJANGO_SUPERUSER_PASSWORD:-}"

    log_info "Checking superuser configuration..."

    # Skip superuser creation if password is not provided
    if [[ -z "${admin_password}" ]]; then
        log_warn "DJANGO_SUPERUSER_PASSWORD not set. Skipping superuser creation for security."
        log_warn "Set DJANGO_SUPERUSER_PASSWORD in your environment to enable automatic superuser creation."
        return 0
    fi

    log_info "Creating superuser if needed (username: ${admin_username})..."

    # Professional Python script for superuser management
    local -r superuser_script="
import os
import django
import sys
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

# Ensure Django is properly configured
try:
    django.setup()
except Exception as e:
    print(f'ERROR: Django setup failed: {e}')
    sys.exit(1)

def create_superuser_safely():
    try:
        User = get_user_model()
        username = '${admin_username}'
        email = '${admin_email}'
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')

        if not password:
            print('ERROR: DJANGO_SUPERUSER_PASSWORD environment variable is required')
            return False

        # Check if superuser already exists
        if User.objects.filter(username=username).exists():
            print(f'INFO: Superuser \"{username}\" already exists')
            return True

        # Create superuser within a transaction for data integrity
        with transaction.atomic():
            superuser = User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            print(f'SUCCESS: Superuser \"{username}\" created successfully')
            print(f'INFO: Email: {email}')
            return True

    except ValidationError as e:
        print(f'ERROR: Validation failed - {e}')
        return False
    except Exception as e:
        print(f'ERROR: Failed to create superuser - {e}')
        return False

# Execute superuser creation
if __name__ == '__main__':
    success = create_superuser_safely()
    sys.exit(0 if success else 1)
"

    # Execute the superuser creation script
    if echo "${superuser_script}" | python -; then
        log_info "✓ Superuser management completed successfully"
    else
        log_error "✗ Superuser creation failed"
        # Don't exit here to allow container to continue running
        log_warn "Continuing without superuser creation..."
    fi
}

# =============================================================================
# MAIN APPLICATION FLOW
# =============================================================================

main() {
    log_info "Starting Django application entrypoint..."
    log_debug "Working directory: $(pwd)"
    log_debug "Environment: DEBUG=${DEBUG:-Not Set}, DJANGO_PORT=${DJANGO_PORT:-Not Set}"

    # Database connectivity check
    log_info "Testing database connection..."
    if ! python manage.py check --database default; then
        log_error "Database connection failed"
        exit 1
    fi
    log_info "✓ Database connectivity verified"

    # Apply database migrations
    run_django_command "migrate --noinput" "database migrations"

    # Collect static files
    run_django_command "collectstatic --noinput" "static file collection"

    # Create superuser if configured
    create_superuser_if_needed

    # Start the application server
    local -r port="${PORT:-${DJANGO_PORT:-8000}}"
    log_info "Starting application server on 0.0.0.0:${port}"
    log_info "Server will be available at: http://localhost:${port}"

    # Execute the command passed as arguments (allows flexibility)
    if [[ $# -gt 0 ]]; then
        log_info "Executing command: $*"
        exec "$@"
    else
        # Default to Django development server if no command provided
        log_info "No command provided, defaulting to Django development server"
        exec python manage.py runserver "0.0.0.0:${port}"
    fi
}

# =============================================================================
# SIGNAL HANDLING FOR GRACEFUL SHUTDOWN
# =============================================================================

setup_signal_handlers() {
    trap 'log_warn "Received SIGTERM, shutting down gracefully..."; exit 0' TERM
    trap 'log_warn "Received SIGINT, shutting down gracefully..."; exit 0' INT
}

# =============================================================================
# SCRIPT EXECUTION
# =============================================================================

# Setup signal handlers and execute main function
setup_signal_handlers
main "$@"
