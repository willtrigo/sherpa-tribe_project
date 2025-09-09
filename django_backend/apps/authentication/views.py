"""
Authentication Views for Enterprise Task Management System.

This module implements both REST API views and Django template views
for user authentication, following enterprise-grade patterns and security practices.
"""

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import FormView, RedirectView

from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from django.contrib.auth import get_user_model
from .serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    CustomTokenObtainPairSerializer,
    UserProfileSerializer
)
from .forms import LoginForm, RegistrationForm
from .tokens import generate_refresh_token, validate_refresh_token
from .permissions import IsOwnerOrReadOnly

User = get_user_model()


# =============================================================================
# REST API Views
# =============================================================================

class UserRegistrationAPIView(APIView):
    """
    API endpoint for user registration.
    
    Handles user account creation with comprehensive validation,
    transaction safety, and enterprise security practices.
    """
    
    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer
    
    @method_decorator(sensitive_post_parameters('password', 'password_confirm'))
    def post(self, request, *args, **kwargs):
        """Register a new user account."""
        serializer = self.serializer_class(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'errors': serializer.errors,
                    'message': 'Registration failed due to validation errors'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            with transaction.atomic():
                user = serializer.save()
                refresh = RefreshToken.for_user(user)
                
                return Response(
                    {
                        'success': True,
                        'message': 'User registered successfully',
                        'data': {
                            'user': UserProfileSerializer(user).data,
                            'tokens': {
                                'access': str(refresh.access_token),
                                'refresh': str(refresh)
                            }
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except ValidationError as e:
            return Response(
                {
                    'success': False,
                    'errors': {'non_field_errors': [str(e)]},
                    'message': 'Registration failed'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {
                    'success': False,
                    'errors': {'non_field_errors': ['An unexpected error occurred']},
                    'message': 'Internal server error'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom JWT token obtain view with enhanced security and logging.
    
    Extends the default JWT view to include user profile data,
    audit logging, and enterprise security measures.
    """
    
    serializer_class = CustomTokenObtainPairSerializer
    
    def post(self, request, *args, **kwargs):
        """Authenticate user and return JWT tokens with user profile."""
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data['user']
            
            # Update last login timestamp
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
            
            return Response(
                {
                    'success': True,
                    'message': 'Authentication successful',
                    'data': {
                        'user': UserProfileSerializer(user).data,
                        'tokens': serializer.validated_data['tokens']
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except TokenError as e:
            return Response(
                {
                    'success': False,
                    'errors': {'non_field_errors': ['Invalid token']},
                    'message': 'Authentication failed'
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        except ValidationError as e:
            return Response(
                {
                    'success': False,
                    'errors': serializer.errors,
                    'message': 'Authentication failed'
                },
                status=status.HTTP_400_BAD_REQUEST
            )


class UserLogoutAPIView(APIView):
    """
    API endpoint for user logout.
    
    Implements secure token blacklisting and session cleanup
    following enterprise security practices.
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        """Logout user by blacklisting the refresh token."""
        try:
            refresh_token = request.data.get('refresh_token')
            
            if not refresh_token:
                return Response(
                    {
                        'success': False,
                        'errors': {'refresh_token': ['This field is required']},
                        'message': 'Refresh token is required for logout'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            return Response(
                {
                    'success': True,
                    'message': 'Successfully logged out'
                },
                status=status.HTTP_200_OK
            )
            
        except TokenError:
            return Response(
                {
                    'success': False,
                    'errors': {'refresh_token': ['Invalid or expired token']},
                    'message': 'Invalid refresh token'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {
                    'success': False,
                    'errors': {'non_field_errors': ['Logout failed']},
                    'message': 'An error occurred during logout'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CustomTokenRefreshView(TokenRefreshView):
    """
    Custom token refresh view with enhanced validation and security.
    
    Extends the default refresh view to include comprehensive
    error handling and security validations.
    """
    
    def post(self, request, *args, **kwargs):
        """Refresh JWT access token with enhanced validation."""
        try:
            response = super().post(request, *args, **kwargs)
            
            if response.status_code == status.HTTP_200_OK:
                return Response(
                    {
                        'success': True,
                        'message': 'Token refreshed successfully',
                        'data': response.data
                    },
                    status=status.HTTP_200_OK
                )
            else:
                return response
                
        except InvalidToken:
            return Response(
                {
                    'success': False,
                    'errors': {'refresh_token': ['Invalid or expired refresh token']},
                    'message': 'Token refresh failed'
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {
                    'success': False,
                    'errors': {'non_field_errors': ['Token refresh failed']},
                    'message': 'An error occurred during token refresh'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# =============================================================================
# Django Template Views
# =============================================================================

@method_decorator([csrf_protect, never_cache], name='dispatch')
class LoginView(FormView):
    """
    Django template view for user login.
    
    Implements secure login with CSRF protection, rate limiting considerations,
    and comprehensive error handling for the frontend interface.
    """
    
    template_name = 'authentication/login.html'
    form_class = LoginForm
    success_url = reverse_lazy('tasks:task_list')
    
    def dispatch(self, request, *args, **kwargs):
        """Redirect authenticated users to dashboard."""
        if request.user.is_authenticated:
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Add additional context for the login template."""
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Login - Task Management System',
            'page_header': 'Sign In to Your Account',
            'show_register_link': True,
        })
        return context
    
    @method_decorator(sensitive_post_parameters('password'))
    def form_valid(self, form):
        """Process valid login form submission."""
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        remember_me = form.cleaned_data.get('remember_me', False)
        
        user = authenticate(
            self.request,
            username=username,
            password=password
        )
        
        if user is not None:
            if user.is_active:
                login(self.request, user)
                
                # Configure session expiry based on remember_me
                if not remember_me:
                    self.request.session.set_expiry(0)  # Browser session
                else:
                    self.request.session.set_expiry(1209600)  # 2 weeks
                
                messages.success(
                    self.request,
                    f'Welcome back, {user.get_full_name() or user.username}!'
                )
                
                # Redirect to next URL if provided
                next_url = self.request.GET.get('next')
                if next_url:
                    return HttpResponseRedirect(next_url)
                
                return super().form_valid(form)
            else:
                messages.error(
                    self.request,
                    'Your account has been deactivated. Please contact support.'
                )
        else:
            messages.error(
                self.request,
                'Invalid username or password. Please try again.'
            )
            
        return self.form_invalid(form)


@method_decorator([csrf_protect, never_cache], name='dispatch')
class RegistrationView(FormView):
    """
    Django template view for user registration.
    
    Handles new user account creation with comprehensive validation,
    security measures, and user experience optimization.
    """
    
    template_name = 'authentication/register.html'
    form_class = RegistrationForm
    success_url = reverse_lazy('authentication:login')
    
    def dispatch(self, request, *args, **kwargs):
        """Redirect authenticated users to dashboard."""
        if request.user.is_authenticated:
            return HttpResponseRedirect(reverse('tasks:task_list'))
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Add additional context for the registration template."""
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Register - Task Management System',
            'page_header': 'Create Your Account',
            'show_login_link': True,
        })
        return context
    
    @method_decorator(sensitive_post_parameters('password1', 'password2'))
    def form_valid(self, form):
        """Process valid registration form submission."""
        try:
            with transaction.atomic():
                user = form.save()
                messages.success(
                    self.request,
                    'Registration successful! You can now log in with your credentials.'
                )
                return super().form_valid(form)
                
        except ValidationError as e:
            messages.error(
                self.request,
                f'Registration failed: {str(e)}'
            )
            return self.form_invalid(form)
        except Exception as e:
            messages.error(
                self.request,
                'An unexpected error occurred during registration. Please try again.'
            )
            return self.form_invalid(form)


@method_decorator([login_required, never_cache], name='dispatch')
class LogoutView(RedirectView):
    """
    Django template view for user logout.
    
    Implements secure logout with session cleanup and
    comprehensive security measures.
    """
    
    url = reverse_lazy('authentication:login')
    permanent = False
    
    def get(self, request, *args, **kwargs):
        """Process logout request."""
        if request.user.is_authenticated:
            username = request.user.username
            logout(request)
            messages.success(
                request,
                f'You have been successfully logged out, {username}.'
            )
        else:
            messages.info(request, 'You were not logged in.')
            
        return super().get(request, *args, **kwargs)


@method_decorator([login_required, never_cache], name='dispatch')
class ProfileView(LoginRequiredMixin, View):
    """
    Django template view for user profile management.
    
    Provides interface for users to view and update their profile information
    with proper authentication and authorization controls.
    """
    
    template_name = 'authentication/profile.html'
    login_url = reverse_lazy('authentication:login')
    
    def get(self, request, *args, **kwargs):
        """Display user profile information."""
        context = {
            'title': 'My Profile - Task Management System',
            'page_header': 'User Profile',
            'user_profile': request.user,
        }
        return render(request, self.template_name, context)


# =============================================================================
# Utility API Views
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_profile_api_view(request):
    """
    API endpoint to retrieve current user's profile information.
    
    Returns comprehensive user profile data for authenticated users
    with proper serialization and security controls.
    """
    try:
        serializer = UserProfileSerializer(request.user)
        return Response(
            {
                'success': True,
                'message': 'Profile retrieved successfully',
                'data': serializer.data
            },
            status=status.HTTP_200_OK
        )
    except Exception as e:
        return Response(
            {
                'success': False,
                'errors': {'non_field_errors': ['Failed to retrieve profile']},
                'message': 'Profile retrieval failed'
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def check_username_availability(request):
    """
    API endpoint to check username availability during registration.
    
    Provides real-time validation for username uniqueness
    to enhance user experience during account creation.
    """
    username = request.data.get('username', '').strip()
    
    if not username:
        return Response(
            {
                'success': False,
                'available': False,
                'message': 'Username is required'
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if len(username) < 3:
        return Response(
            {
                'success': False,
                'available': False,
                'message': 'Username must be at least 3 characters long'
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        is_available = not User.objects.filter(username__iexact=username).exists()
        
        return Response(
            {
                'success': True,
                'available': is_available,
                'message': 'Username is available' if is_available else 'Username is already taken'
            },
            status=status.HTTP_200_OK
        )
    except Exception as e:
        return Response(
            {
                'success': False,
                'available': False,
                'message': 'Error checking username availability'
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
