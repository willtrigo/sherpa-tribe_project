"""
Authentication serializers for the Enterprise Task Management System.

This module contains serializers for user authentication operations including
registration, login, logout, token refresh, and user profile management.
"""

from typing import Any, Dict, Optional

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer as BaseTokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration with comprehensive validation.
    
    Handles user creation with password confirmation, email validation,
    and proper error handling for duplicate users.
    """
    
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=128,
        style={'input_type': 'password'},
        help_text=_('Password must be at least 8 characters long.')
    )
    password_confirm = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=128,
        style={'input_type': 'password'},
        help_text=_('Confirm your password.')
    )
    email = serializers.EmailField(
        required=True,
        help_text=_('Valid email address required.')
    )
    first_name = serializers.CharField(
        required=True,
        min_length=2,
        max_length=30,
        help_text=_('First name is required.')
    )
    last_name = serializers.CharField(
        required=True,
        min_length=2,
        max_length=30,
        help_text=_('Last name is required.')
    )
    
    class Meta:
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name',
            'password', 'password_confirm'
        )
        extra_kwargs = {
            'username': {
                'help_text': _('Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.'),
                'min_length': 3,
                'max_length': 150,
            },
        }

    def validate_username(self, value: str) -> str:
        """Validate username uniqueness and format."""
        if User.objects.filter(username__iexact=value).exists():
            raise ValidationError(
                _('A user with this username already exists.'),
                code='username_exists'
            )
        return value.lower()

    def validate_email(self, value: str) -> str:
        """Validate email uniqueness."""
        if User.objects.filter(email__iexact=value).exists():
            raise ValidationError(
                _('A user with this email address already exists.'),
                code='email_exists'
            )
        return value.lower()

    def validate_password(self, value: str) -> str:
        """Validate password using Django's password validators."""
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages, code='password_invalid')
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate password confirmation and overall data consistency."""
        password = attrs.get('password')
        password_confirm = attrs.get('password_confirm')
        
        if password != password_confirm:
            raise ValidationError({
                'password_confirm': _('Password confirmation does not match.')
            }, code='password_mismatch')
        
        # Remove password_confirm from validated data
        attrs.pop('password_confirm', None)
        return attrs

    @transaction.atomic
    def create(self, validated_data: Dict[str, Any]) -> User:
        """Create user with proper password hashing."""
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user

    def to_representation(self, instance: User) -> Dict[str, Any]:
        """Return user data without sensitive information."""
        return {
            'id': instance.id,
            'username': instance.username,
            'email': instance.email,
            'first_name': instance.first_name,
            'last_name': instance.last_name,
            'date_joined': instance.date_joined,
            'is_active': instance.is_active,
        }


class UserLoginSerializer(TokenObtainPairSerializer):
    """
    Enhanced JWT token serializer with additional user information.
    
    Extends the base token serializer to include user profile data
    and custom token claims.
    """
    
    username_field = 'username'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'] = serializers.CharField(
            required=True,
            help_text=_('Username or email address.')
        )
        self.fields['password'] = serializers.CharField(
            required=True,
            write_only=True,
            style={'input_type': 'password'},
            help_text=_('User password.')
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate credentials and authenticate user.
        
        Supports authentication with both username and email.
        """
        username = attrs.get('username')
        password = attrs.get('password')
        
        if not username or not password:
            raise ValidationError(
                _('Both username/email and password are required.'),
                code='missing_credentials'
            )
        
        # Try authentication with username first, then email
        user = self._authenticate_user(username, password)
        
        if not user:
            raise AuthenticationFailed(
                _('Invalid credentials provided.'),
                code='invalid_credentials'
            )
        
        if not user.is_active:
            raise AuthenticationFailed(
                _('User account is disabled.'),
                code='account_disabled'
            )
        
        # Generate tokens
        refresh = self.get_token(user)
        
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': self._get_user_data(user),
        }

    def _authenticate_user(self, identifier: str, password: str) -> Optional[User]:
        """
        Authenticate user by username or email.
        
        Args:
            identifier: Username or email address
            password: User password
            
        Returns:
            Authenticated user instance or None
        """
        # Try username authentication
        user = authenticate(username=identifier, password=password)
        
        # If username auth fails, try email authentication
        if not user and '@' in identifier:
            try:
                user_obj = User.objects.get(email__iexact=identifier)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass
                
        return user

    def _get_user_data(self, user: User) -> Dict[str, Any]:
        """Extract user profile data for response."""
        return {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_staff': user.is_staff,
            'is_active': user.is_active,
            'last_login': user.last_login,
            'date_joined': user.date_joined,
        }

    @classmethod
    def get_token(cls, user: User) -> RefreshToken:
        """Generate JWT token with custom claims."""
        token = super().get_token(user)
        
        # Add custom claims
        token['username'] = user.username
        token['email'] = user.email
        token['full_name'] = f'{user.first_name} {user.last_name}'.strip()
        token['is_staff'] = user.is_staff
        
        return token


class TokenRefreshSerializer(BaseTokenRefreshSerializer):
    """
    Enhanced token refresh serializer with additional validation.
    
    Provides detailed error messages and token validation.
    """
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate refresh token and generate new access token."""
        refresh_token = attrs.get('refresh')
        
        if not refresh_token:
            raise ValidationError(
                _('Refresh token is required.'),
                code='missing_refresh_token'
            )
        
        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)
            
            # Validate token is not blacklisted
            UntypedToken(refresh_token)
            
            return {
                'access': access_token,
                'refresh': str(refresh) if self._should_refresh_token(refresh) else refresh_token,
            }
            
        except TokenError as exc:
            raise InvalidToken(_('Invalid or expired refresh token.')) from exc

    def _should_refresh_token(self, refresh: RefreshToken) -> bool:
        """
        Determine if refresh token should be rotated.
        
        Can be extended to implement token rotation policies.
        """
        # Implement token rotation logic if needed
        return False


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for user profile operations.
    
    Handles profile updates with proper validation and security.
    """
    
    email = serializers.EmailField(
        required=False,
        help_text=_('Email address (must be unique).')
    )
    
    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name',
            'is_active', 'date_joined', 'last_login'
        )
        read_only_fields = ('id', 'username', 'date_joined', 'last_login', 'is_active')

    def validate_email(self, value: str) -> str:
        """Validate email uniqueness excluding current user."""
        user = self.instance
        if user and User.objects.filter(email__iexact=value).exclude(id=user.id).exists():
            raise ValidationError(
                _('A user with this email address already exists.'),
                code='email_exists'
            )
        return value.lower()

    def update(self, instance: User, validated_data: Dict[str, Any]) -> User:
        """Update user profile with validation."""
        # Handle email update carefully
        if 'email' in validated_data:
            instance.email = validated_data['email']
            
        # Update other fields
        for field, value in validated_data.items():
            if field != 'email' and hasattr(instance, field):
                setattr(instance, field, value)
                
        instance.save(update_fields=list(validated_data.keys()))
        return instance


class PasswordChangeSerializer(serializers.Serializer):
    """
    Serializer for password change operations.
    
    Validates current password and applies new password with proper validation.
    """
    
    current_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text=_('Current password for verification.')
    )
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        min_length=8,
        max_length=128,
        style={'input_type': 'password'},
        help_text=_('New password (minimum 8 characters).')
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        min_length=8,
        max_length=128,
        style={'input_type': 'password'},
        help_text=_('Confirm new password.')
    )

    def validate_current_password(self, value: str) -> str:
        """Validate current password against user's actual password."""
        user = self.context['request'].user
        if not user.check_password(value):
            raise ValidationError(
                _('Current password is incorrect.'),
                code='invalid_current_password'
            )
        return value

    def validate_new_password(self, value: str) -> str:
        """Validate new password using Django's password validators."""
        user = self.context['request'].user
        try:
            validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages, code='password_invalid')
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate password confirmation and ensure passwords differ."""
        new_password = attrs.get('new_password')
        confirm_password = attrs.get('confirm_password')
        current_password = attrs.get('current_password')
        
        if new_password != confirm_password:
            raise ValidationError({
                'confirm_password': _('New password confirmation does not match.')
            }, code='password_mismatch')
        
        if current_password == new_password:
            raise ValidationError({
                'new_password': _('New password must be different from current password.')
            }, code='same_password')
        
        return attrs

    def save(self) -> None:
        """Update user password."""
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])


class UserLogoutSerializer(serializers.Serializer):
    """
    Serializer for user logout operations.
    
    Handles refresh token blacklisting for secure logout.
    """
    
    refresh = serializers.CharField(
        required=True,
        help_text=_('Refresh token to blacklist.')
    )

    def validate_refresh(self, value: str) -> str:
        """Validate refresh token format and existence."""
        try:
            UntypedToken(value)
        except TokenError as exc:
            raise ValidationError(
                _('Invalid refresh token provided.'),
                code='invalid_token'
            ) from exc
        return value

    def save(self) -> None:
        """Blacklist refresh token."""
        try:
            refresh_token = RefreshToken(self.validated_data['refresh'])
            refresh_token.blacklist()
        except TokenError as exc:
            raise ValidationError(
                _('Failed to blacklist token.'),
                code='blacklist_failed'
            ) from exc
