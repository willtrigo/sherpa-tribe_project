#!/bin/bash

set -o errexit
set -o pipefail
set -o nounset

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to run Django management commands safely
run_django_command() {
    local command="$1"
    log_info "Running: python manage.py $command"

    if python manage.py $$command; then
        log_info "✓ Command '$command' completed successfully"
    else
        log_error "✗ Command '$command' failed"
        exit 1
    fi
}

# Main execution
main() {
    log_info "Starting Django application entrypoint..."

    # Check database connection
    log_info "Testing database connection..."
    if ! python manage.py check --database default; then
        log_error "Database connection failed"
        exit 1
    fi

    # Run database migrations
    run_django_command "migrate --noinput"

	run_django_command "collectstatic --noinput"

    exec python manage.py runserver 0.0.0.0:${PORT:-8000}
    # Start the application based on environment
}

# Trap signals for graceful shutdown
trap 'log_warn "Received SIGTERM, shutting down gracefully..."; exit 0' TERM
trap 'log_warn "Received SIGINT, shutting down gracefully..."; exit 0' INT

# Run main function
main "$@"
