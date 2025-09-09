"""
Authentication URL Configuration

This module defines URL patterns for authentication-related endpoints including
both API endpoints for programmatic access and web views for browser-based interactions.

API Endpoints:
- POST /api/auth/register/ - User registration
- POST /api/auth/login/ - User authentication  
- POST /api/auth/logout/ - User logout
- POST /api/auth/refresh/ - Token refresh

Web Views:
- GET/POST /auth/login/ - Browser login form
- GET/POST /auth/register/ - Browser registration form
- POST /auth/logout/ - Browser logout

Author: Enterprise Task Management System
Version: 1.0.0
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    # API Views
    UserRegistrationAPIView,
    UserLoginAPIView,
    UserLogoutAPIView,
    UserProfileAPIView,
    # Web Views  
    LoginView,
    RegisterView,
    LogoutView,
    ProfileView,
)

app_name = 'authentication'

# API URL patterns for REST endpoints
api_urlpatterns = [
    path(
        'register/',
        UserRegistrationAPIView.as_view(),
        name='api_register'
    ),
    path(
        'login/',
        UserLoginAPIView.as_view(),
        name='api_login'
    ),
    path(
        'logout/',
        UserLogoutAPIView.as_view(),
        name='api_logout'
    ),
    path(
        'refresh/',
        TokenRefreshView.as_view(),
        name='api_token_refresh'
    ),
    path(
        'profile/',
        UserProfileAPIView.as_view(),
        name='api_profile'
    ),
]

# Web URL patterns for browser-based views
web_urlpatterns = [
    path(
        'login/',
        LoginView.as_view(),
        name='web_login'
    ),
    path(
        'register/',
        RegisterView.as_view(),
        name='web_register'  
    ),
    path(
        'logout/',
        LogoutView.as_view(),
        name='web_logout'
    ),
    path(
        'profile/',
        ProfileView.as_view(),
        name='web_profile'
    ),
]

# Main URL patterns combining API and web routes
urlpatterns = [
    # API routes with versioning prefix
    path('api/', include(api_urlpatterns)),
    
    # Web routes for browser interface
    path('', include(web_urlpatterns)),
]

# Additional patterns for development/debugging (only in DEBUG mode)
from django.conf import settings
if settings.DEBUG:
    from django.views.generic import TemplateView
    
    urlpatterns += [
        path(
            'debug/tokens/',
            TemplateView.as_view(template_name='authentication/debug_tokens.html'),
            name='debug_tokens'
        ),
    ]
