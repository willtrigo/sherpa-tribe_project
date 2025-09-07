# Enterprise Task Management System

A containerized full-stack task management platform built with Django REST Framework, Celery, PostgreSQL, Redis, and optional Kafka integration. This system demonstrates enterprise-grade architecture patterns with microservices, event streaming, and comprehensive task workflow management.

## 🏗️ Architecture Overview

The system follows a microservices architecture with the following components:

- **Django Backend**: REST API with Django templates for UI
- **PostgreSQL**: Primary database with full-text search capabilities
- **Redis**: Caching layer and Celery message broker
- **Celery**: Asynchronous task processing with scheduled jobs
- **Flask Analytics** (Optional): Dedicated analytics and reporting microservice
- **Kafka** (Optional): Event streaming for real-time data processing

## 🚀 Quick Start

### Prerequisites

- Docker 28.3.3+
- Docker Compose 4.45.0+
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/willtrigo/sherpa-tribe_project.git task-management-system
cd task-management-system

# Copy environment configuration
cp .env.sample .env

# Generate Django SECRET_KEY
bash django_backend/scripts/secret_gen.sh

# Generate Django SECRET_KEY
bash django_backend/scripts/secret_gen.sh
```

### Environment Configuration

Edit the `.env` file and configure the following required variables:

```bash
# Copy the generated secret key from the script output
SECRET_KEY=your-generated-secret-key-here

# Configure superuser for automatic admin creation
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=your-secure-password
```

**Important**: These variables are required for the initial setup and automatic superuser creation.

### Start the Application

```bash
# Build and start all services
docker-compose up

# The application will be available at:
# - Main Application: http://localhost:8000
# - Admin Panel: http://localhost:8000/admin
# - PostgreSQL: localhost:5432
```

### First-time Setup

The system automatically handles:
- Database migrations
- **Superuser creation** (using environment variables configured above)
- Sample data seeding
- Static file collection
- Service health checks
