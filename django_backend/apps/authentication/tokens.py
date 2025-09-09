"""
JWT Token Management for Enterprise Task Management System.

Provides secure token generation, validation, and refresh functionality
with configurable expiration times and proper security measures.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Any
from uuid import uuid4

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError

from ..common.exceptions import TokenValidationError

logger = logging.getLogger(__name__)
User = get_user_model()


class TokenConfiguration:
    """Centralized token configuration management."""
    
    ACCESS_TOKEN_LIFETIME = getattr(settings, 'ACCESS_TOKEN_LIFETIME', timedelta(minutes=15))
    REFRESH_TOKEN_LIFETIME = getattr(settings, 'REFRESH_TOKEN_LIFETIME', timedelta(days=7))
    ALGORITHM = getattr(settings, 'JWT_ALGORITHM', 'HS256')
    SECRET_KEY = getattr(settings, 'SECRET_KEY')
    ISSUER = getattr(settings, 'JWT_ISSUER', 'task-management-system')
    AUDIENCE = getattr(settings, 'JWT_AUDIENCE', 'task-management-api')
    
    # Cache keys
    BLACKLIST_PREFIX = 'token_blacklist'
    USER_TOKENS_PREFIX = 'user_active_tokens'
    
    @classmethod
    def get_blacklist_key(cls, jti: str) -> str:
        """Generate cache key for blacklisted tokens."""
        return f"{cls.BLACKLIST_PREFIX}:{jti}"
    
    @classmethod
    def get_user_tokens_key(cls, user_id: int) -> str:
        """Generate cache key for user's active tokens."""
        return f"{cls.USER_TOKENS_PREFIX}:{user_id}"


class TokenPayloadGenerator:
    """Handles token payload generation with proper claims."""
    
    @staticmethod
    def generate_base_payload(
        user: User,
        token_type: str,
        lifetime: timedelta
    ) -> Dict[str, Any]:
        """Generate base JWT payload with standard claims."""
        now = timezone.now()
        jti = str(uuid4())
        
        return {
            # Standard JWT claims
            'iss': TokenConfiguration.ISSUER,
            'aud': TokenConfiguration.AUDIENCE,
            'sub': str(user.pk),
            'iat': int(now.timestamp()),
            'exp': int((now + lifetime).timestamp()),
            'jti': jti,
            
            # Custom claims
            'token_type': token_type,
            'user_id': user.pk,
            'username': user.username,
            'email': user.email,
            'is_superuser': user.is_superuser,
            'is_staff': user.is_staff,
            'permissions': list(user.get_all_permissions()),
            'groups': list(user.groups.values_list('name', flat=True)),
        }
    
    @staticmethod
    def generate_access_payload(user: User) -> Dict[str, Any]:
        """Generate access token payload."""
        payload = TokenPayloadGenerator.generate_base_payload(
            user, 'access', TokenConfiguration.ACCESS_TOKEN_LIFETIME
        )
        
        # Add access-specific claims
        payload.update({
            'scope': 'read write',
            'last_login': user.last_login.isoformat() if user.last_login else None,
        })
        
        return payload
    
    @staticmethod
    def generate_refresh_payload(user: User) -> Dict[str, Any]:
        """Generate refresh token payload."""
        payload = TokenPayloadGenerator.generate_base_payload(
            user, 'refresh', TokenConfiguration.REFRESH_TOKEN_LIFETIME
        )
        
        # Add refresh-specific claims
        payload.update({
            'scope': 'refresh',
        })
        
        return payload


class TokenValidator:
    """Handles token validation and verification."""
    
    @staticmethod
    def decode_token(token: str, verify_exp: bool = True) -> Dict[str, Any]:
        """
        Decode and validate JWT token.
        
        Args:
            token: JWT token string
            verify_exp: Whether to verify token expiration
            
        Returns:
            Decoded token payload
            
        Raises:
            TokenValidationError: If token is invalid
        """
        try:
            payload = jwt.decode(
                token,
                TokenConfiguration.SECRET_KEY,
                algorithms=[TokenConfiguration.ALGORITHM],
                audience=TokenConfiguration.AUDIENCE,
                issuer=TokenConfiguration.ISSUER,
                options={'verify_exp': verify_exp}
            )
            
            # Validate required claims
            required_claims = ['sub', 'jti', 'token_type', 'user_id']
            missing_claims = [claim for claim in required_claims if claim not in payload]
            if missing_claims:
                raise TokenValidationError(f"Missing required claims: {missing_claims}")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            raise TokenValidationError("Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {str(e)}")
            raise TokenValidationError(f"Invalid token: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error validating token: {str(e)}")
            raise TokenValidationError("Token validation failed")
    
    @staticmethod
    def is_token_blacklisted(jti: str) -> bool:
        """Check if token is blacklisted."""
        cache_key = TokenConfiguration.get_blacklist_key(jti)
        return cache.get(cache_key, False)
    
    @staticmethod
    def validate_token_type(payload: Dict[str, Any], expected_type: str) -> None:
        """Validate token type matches expected."""
        token_type = payload.get('token_type')
        if token_type != expected_type:
            raise TokenValidationError(f"Expected {expected_type} token, got {token_type}")
    
    @staticmethod
    def validate_user_exists(user_id: int) -> User:
        """Validate user exists and is active."""
        try:
            user = User.objects.get(pk=user_id, is_active=True)
            return user
        except User.DoesNotExist:
            raise TokenValidationError("User not found or inactive")


class TokenBlacklistManager:
    """Manages token blacklisting for security."""
    
    @staticmethod
    def blacklist_token(jti: str, exp_timestamp: int) -> None:
        """Add token to blacklist until expiration."""
        cache_key = TokenConfiguration.get_blacklist_key(jti)
        exp_datetime = datetime.fromtimestamp(exp_timestamp, tz=timezone.get_current_timezone())
        ttl = max(int((exp_datetime - timezone.now()).total_seconds()), 1)
        
        cache.set(cache_key, True, timeout=ttl)
        logger.info(f"Token {jti} blacklisted until {exp_datetime}")
    
    @staticmethod
    def blacklist_user_tokens(user_id: int) -> int:
        """Blacklist all active tokens for a user."""
        cache_key = TokenConfiguration.get_user_tokens_key(user_id)
        active_tokens = cache.get(cache_key, [])
        
        blacklisted_count = 0
        for token_info in active_tokens:
            TokenBlacklistManager.blacklist_token(
                token_info['jti'], 
                token_info['exp']
            )
            blacklisted_count += 1
        
        # Clear user's active tokens cache
        cache.delete(cache_key)
        
        logger.info(f"Blacklisted {blacklisted_count} tokens for user {user_id}")
        return blacklisted_count


class TokenManager:
    """Main token management interface."""
    
    def __init__(self):
        self.config = TokenConfiguration()
        self.payload_generator = TokenPayloadGenerator()
        self.validator = TokenValidator()
        self.blacklist_manager = TokenBlacklistManager()
    
    def generate_token_pair(self, user: User) -> Dict[str, str]:
        """
        Generate access and refresh token pair.
        
        Args:
            user: User instance
            
        Returns:
            Dictionary containing access and refresh tokens
        """
        try:
            access_payload = self.payload_generator.generate_access_payload(user)
            refresh_payload = self.payload_generator.generate_refresh_payload(user)
            
            access_token = jwt.encode(
                access_payload,
                self.config.SECRET_KEY,
                algorithm=self.config.ALGORITHM
            )
            
            refresh_token = jwt.encode(
                refresh_payload,
                self.config.SECRET_KEY,
                algorithm=self.config.ALGORITHM
            )
            
            # Store active tokens for user (for blacklisting purposes)
            self._store_user_tokens(user.pk, [
                {
                    'jti': access_payload['jti'],
                    'exp': access_payload['exp'],
                    'type': 'access'
                },
                {
                    'jti': refresh_payload['jti'],
                    'exp': refresh_payload['exp'],
                    'type': 'refresh'
                }
            ])
            
            logger.info(f"Generated token pair for user {user.pk}")
            
            return {
                'access': access_token,
                'refresh': refresh_token,
                'access_expires_at': datetime.fromtimestamp(
                    access_payload['exp']
                ).isoformat(),
                'refresh_expires_at': datetime.fromtimestamp(
                    refresh_payload['exp']
                ).isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Failed to generate tokens for user {user.pk}: {str(e)}")
            raise TokenValidationError("Failed to generate tokens")
    
    def validate_access_token(self, token: str) -> Tuple[User, Dict[str, Any]]:
        """
        Validate access token and return user.
        
        Args:
            token: Access token string
            
        Returns:
            Tuple of (User instance, token payload)
            
        Raises:
            TokenValidationError: If token is invalid
        """
        payload = self.validator.decode_token(token)
        self.validator.validate_token_type(payload, 'access')
        
        if self.validator.is_token_blacklisted(payload['jti']):
            raise TokenValidationError("Token has been revoked")
        
        user = self.validator.validate_user_exists(payload['user_id'])
        
        return user, payload
    
    def refresh_access_token(self, refresh_token: str) -> Dict[str, str]:
        """
        Generate new access token using refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            Dictionary containing new access token
            
        Raises:
            TokenValidationError: If refresh token is invalid
        """
        payload = self.validator.decode_token(refresh_token)
        self.validator.validate_token_type(payload, 'refresh')
        
        if self.validator.is_token_blacklisted(payload['jti']):
            raise TokenValidationError("Refresh token has been revoked")
        
        user = self.validator.validate_user_exists(payload['user_id'])
        
        # Generate new access token
        access_payload = self.payload_generator.generate_access_payload(user)
        access_token = jwt.encode(
            access_payload,
            self.config.SECRET_KEY,
            algorithm=self.config.ALGORITHM
        )
        
        # Store new access token info
        self._store_user_tokens(user.pk, [{
            'jti': access_payload['jti'],
            'exp': access_payload['exp'],
            'type': 'access'
        }], append=True)
        
        logger.info(f"Refreshed access token for user {user.pk}")
        
        return {
            'access': access_token,
            'access_expires_at': datetime.fromtimestamp(
                access_payload['exp']
            ).isoformat(),
        }
    
    def revoke_token(self, token: str) -> None:
        """
        Revoke (blacklist) a specific token.
        
        Args:
            token: Token to revoke
        """
        try:
            payload = self.validator.decode_token(token, verify_exp=False)
            self.blacklist_manager.blacklist_token(payload['jti'], payload['exp'])
            logger.info(f"Revoked token {payload['jti']}")
        except Exception as e:
            logger.error(f"Failed to revoke token: {str(e)}")
            raise TokenValidationError("Failed to revoke token")
    
    def revoke_user_tokens(self, user_id: int) -> int:
        """
        Revoke all tokens for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Number of tokens revoked
        """
        return self.blacklist_manager.blacklist_user_tokens(user_id)
    
    def _store_user_tokens(
        self, 
        user_id: int, 
        tokens: list, 
        append: bool = False
    ) -> None:
        """Store user's active tokens in cache."""
        cache_key = self.config.get_user_tokens_key(user_id)
        
        if append:
            existing_tokens = cache.get(cache_key, [])
            tokens = existing_tokens + tokens
        
        # Keep only non-expired tokens
        now = timezone.now().timestamp()
        active_tokens = [t for t in tokens if t['exp'] > now]
        
        if active_tokens:
            # Set TTL to longest token expiration
            max_exp = max(t['exp'] for t in active_tokens)
            ttl = max(int(max_exp - now), 1)
            cache.set(cache_key, active_tokens, timeout=ttl)


# Singleton instance for easy access
token_manager = TokenManager()


def generate_tokens_for_user(user: User) -> Dict[str, str]:
    """Convenience function to generate tokens for a user."""
    return token_manager.generate_token_pair(user)


def validate_access_token(token: str) -> Tuple[User, Dict[str, Any]]:
    """Convenience function to validate access token."""
    return token_manager.validate_access_token(token)


def refresh_token(refresh_token: str) -> Dict[str, str]:
    """Convenience function to refresh access token."""
    return token_manager.refresh_access_token(refresh_token)


def revoke_token(token: str) -> None:
    """Convenience function to revoke a token."""
    return token_manager.revoke_token(token)


def revoke_all_user_tokens(user_id: int) -> int:
    """Convenience function to revoke all user tokens."""
    return token_manager.revoke_user_tokens(user_id)
