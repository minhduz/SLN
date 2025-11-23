from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import User
from .serializers import (RegisterSerializer, UserSerializer,
                          CustomTokenObtainPairSerializer, CustomTokenRefreshSerializer,
                          LogoutSerializer, UserProfileSerializer
                          ,UpdateUserSerializer, SendOTPSerializer, VerifyOTPSerializer,
                          UserSearchSerializer, ChangePasswordSerializer)

from .services.user_service import UserService


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)

class UserProfileView(generics.RetrieveAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return UserService.get_my_profile(self.request.user)

class UpdateUserView(generics.UpdateAPIView):
    serializer_class = UpdateUserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

class ChangePasswordView(APIView):
    """
    API endpoint for changing user password.
    Requires authentication and validation of old password.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']

        try:
            result = UserService.change_password(
                request.user,
                old_password,
                new_password
            )
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = SendOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data["phone"]
        purpose = ser.validated_data["purpose"]

        try:
            result = UserService.send_otp(phone, purpose)
        except ValueError:
            return Response({"detail": "Invalid phone"}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = VerifyOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data["phone"]
        code = ser.validated_data["code"]

        if not UserService.verify_otp(phone, code):
            return Response({"detail": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "OTP verified"}, status=status.HTTP_200_OK)


class UserSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Search users by username, email, or full name
        Query params:
            - q: search query (required, min 2 characters)
            - limit: max results (optional, default 20, max 50)
            - exclude_self: exclude current user from results (optional, default true)
            - exclude_admin: exclude admin users from results (optional, default true)
        """
        query = request.query_params.get('q', '').strip()

        if not query:
            return Response(
                {"detail": "Search query parameter 'q' is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(query) < 2:
            return Response(
                {"detail": "Search query must be at least 2 characters"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get limit parameter (default 20, max 50)
        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(max(1, limit), 50)  # Clamp between 1 and 50
        except ValueError:
            limit = 20

        # Check if current user should be excluded
        exclude_self = request.query_params.get('exclude_self', 'true').lower() == 'true'
        exclude_user_id = request.user.id if exclude_self else None

        # Check if admin users should be excluded (default true)
        exclude_admin = request.query_params.get('exclude_admin', 'true').lower() == 'true'

        try:
            users = UserService.search_users(
                query=query,
                exclude_user_id=exclude_user_id,
                exclude_admin=exclude_admin,
                limit=limit
            )

            serializer = UserSearchSerializer(users, many=True)

            return Response({
                "count": len(users),
                "results": serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            # Log the error in production
            return Response(
                {"detail": "An error occurred while searching users"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


