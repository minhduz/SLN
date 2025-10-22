from django.conf import settings
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken

from .models import User

from .services.user_service import create_user, update_user
from .services.auth_service import generate_and_store_tokens, refresh_tokens, revoke_refresh_token

PURPOSES = ("signup", "password_reset", "phone_change", "verification")

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ["password"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    avatar = serializers.ImageField(required=False)

    class Meta:
        model = User
        fields = ["username", "email", "phone", "password", "full_name", "role", "dob", "avatar"]

    def create(self, validated_data):
        return create_user(validated_data)

class UpdateUserSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(required=False)

    class Meta:
        model = User
        fields = ["full_name", "avatar", "bio"]

    def update(self, instance, validated_data):
        return update_user(instance, validated_data)

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # ✅ First, manually authenticate to check if user exists (even if inactive)
        username = attrs.get('username')
        password = attrs.get('password')

        if not username or not password:
            raise serializers.ValidationError("Username and password are required")

        # Try to find the user regardless of is_active status
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")

        # Check if password is correct
        if not user.check_password(password):
            raise serializers.ValidationError("Invalid credentials")

        # ✅ Now check if account is active (our custom verification logic)
        if not user.is_active:
            return{
                "error_code": "account_not_verified",
                "message": "Account not verified. Please complete phone verification first.",
                "redirect": "otp_verification",
                "user_data": {
                    "phone": user.phone,
                    "username": user.username,
                    "email": user.email
                }
            }

        # ✅ If user is active, proceed with normal JWT token generation
        # We need to temporarily set the user for the parent class
        self.user = user

        # Call parent validate with modified behavior
        # We'll bypass the parent's authenticate call since we already did it
        data = {}

        access_token, refresh_token = generate_and_store_tokens(
            self.user, self.context.get("request")
        )

        data["access"] = access_token
        data["refresh"] = refresh_token
        return data

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh_token = attrs["refresh"]

        access_token, new_refresh_token = refresh_tokens(
            refresh_token, self.context.get("request")
        )

        return {"access": access_token, "refresh": new_refresh_token}

class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=True)

    def save(self, **kwargs):
        refresh_token = self.validated_data["refresh_token"]

        try:
            revoke_refresh_token(refresh_token)
        except InvalidToken as e:
            raise serializers.ValidationError({"refresh_token": str(e)})

        return {"message": "Logged out"}


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id","username", "email", "phone", "full_name", "avatar","bio","dob","role","points"]


class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField()
    purpose = serializers.ChoiceField(choices=[(p, p) for p in PURPOSES])

class VerifyOTPSerializer(serializers.Serializer):
    phone = serializers.CharField()
    purpose = serializers.ChoiceField(choices=[(p, p) for p in PURPOSES])
    code = serializers.CharField()

