from django.conf import settings
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken

from .models import User

from .services.user_service import create_user, update_user
from .services.auth_service import generate_and_store_tokens, refresh_tokens, revoke_refresh_token

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ["password"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    avatar = serializers.ImageField(required=False)

    class Meta:
        model = User
        fields = ["username", "email", "password", "full_name", "role", "avatar"]

    def create(self, validated_data):
        return create_user(validated_data)

class UpdateUserSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["full_name", "avatar", "bio"]

    def update(self, instance, validated_data):
        return update_user(instance, validated_data)

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

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
        fields = ["username", "email", "full_name", "avatar","bio","role","points"]