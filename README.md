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
git clone https://github.com/willtrigo/sherpa-tribe_project.git
cd task-management-system

