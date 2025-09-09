from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .serializers import (
    CustomTokenObtainPairSerializer,
    UserRegistrationSerializer,
    UserDetailSerializer,
    UserListSerializer,
    ChangePasswordSerializer
)

User = get_user_model()


class LoginView(TokenObtainPairView):
    """
    Custom login view using JWT tokens
    """
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        """
        Authenticate user and return JWT tokens
        """
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        return Response(
            {
                'status': 'success',
                'message': 'Login successful',
                'data': serializer.validated_data
            },
            status=status.HTTP_200_OK
        )


class RegisterView(generics.CreateAPIView):
    """
    User registration view
    """
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def create(self, request, *args, **kwargs):
        """
        Create new user account
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            user = serializer.save()

            # Generate JWT tokens for the new user
            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    'status': 'success',
                    'message': 'User registered successfully',
                    'data': {
                        'user': UserDetailSerializer(user).data,
                        'refresh': str(refresh),
                        'access': str(refresh.access_token),
                    }
                },
                status=status.HTTP_201_CREATED
            )


class LogoutView(APIView):
    """
    Logout view that blacklists refresh token
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Blacklist refresh token to logout user
        """
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response(
                    {
                        'status': 'error',
                        'message': 'Refresh token is required'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response(
                {
                    'status': 'success',
                    'message': 'Successfully logged out'
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {
                    'status': 'error',
                    'message': 'Invalid token or token already blacklisted'
                },
                status=status.HTTP_400_BAD_REQUEST
            )


class TokenRefreshView(TokenRefreshView):
    """
    Custom token refresh view
    """

    def post(self, request, *args, **kwargs):
        """
        Refresh access token
        """
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        return Response(
            {
                'status': 'success',
                'message': 'Token refreshed successfully',
                'data': serializer.validated_data
            },
            status=status.HTTP_200_OK
        )


class UserMeView(generics.RetrieveUpdateAPIView):
    """
    View for current user profile
    """
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """
        Return current authenticated user
        """
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        """
        Get current user details
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return Response(
            {
                'status': 'success',
                'data': serializer.data
            },
            status=status.HTTP_200_OK
        )

    def update(self, request, *args, **kwargs):
        """
        Update current user details
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(
            {
                'status': 'success',
                'message': 'Profile updated successfully',
                'data': serializer.data
            },
            status=status.HTTP_200_OK
        )


class ChangePasswordView(APIView):
    """
    Change password view
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Change user password
        """
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    'status': 'success',
                    'message': 'Password changed successfully'
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                'status': 'error',
                'message': 'Validation failed',
                'errors': serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )


class UserListView(generics.ListAPIView):
    """
    List all users (for task assignment, etc.)
    """
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        """
        List all active users
        """
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response({
                'status': 'success',
                'data': serializer.data
            })

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                'status': 'success',
                'data': serializer.data
            },
            status=status.HTTP_200_OK
        )


class UserDetailView(generics.RetrieveAPIView):
    """
    Retrieve specific user details
    """
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        """
        Get specific user details
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return Response(
            {
                'status': 'success',
                'data': serializer.data
            },
            status=status.HTTP_200_OK
        )
