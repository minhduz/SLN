import os
from typing import List  # Add this import
from django.db.models import Q  # Add this import

from django.conf import settings
from ..models import User, UserVerification

from django.core.files.storage import default_storage
from ..tasks import delete_avatar_task
from .otp_service import issue_otp, verify_otp, normalize_phone_to_e164

def rename_and_save_avatar(user: User, avatar):
    """
    Save avatar with a deterministic filename based on user.id,
    ensuring consistency across create and update.
    """
    ext = os.path.splitext(avatar.name)[1].lower()
    avatar_filename = f"avatars/{user.id}{ext}"
    saved_path = default_storage.save(avatar_filename, avatar)
    return saved_path

def create_user(validated_data):
    avatar = validated_data.pop("avatar", None)
    password = validated_data.pop("password")
    user = User(**validated_data)
    user.set_password(password)
    user.save()

    if avatar:
        saved_path = rename_and_save_avatar(user, avatar)
        user.avatar.name = saved_path
        user.save()

    return user

def update_user(user, data):
    avatar = data.pop("avatar", None)

    # Always fetch from DB, not from the in-memory user
    old_avatar = None
    if avatar and user.pk:
        old_avatar = User.objects.only("avatar").get(pk=user.pk).avatar

    for attr, value in data.items():
        setattr(user, attr, value)

    if avatar:
        saved_path = rename_and_save_avatar(user, avatar)
        user.avatar.name = saved_path

        # async cleanup old avatar
        if old_avatar:
            delete_avatar_task.delay(old_avatar.name)

    user.save()
    return user

class UserService:
    @staticmethod
    def get_my_profile(user: User):
        """
        Return current user profile.
        """
        return user

    @staticmethod
    def send_otp(phone: str, purpose: str):
        try:
            phone_e164 = issue_otp(phone, purpose)
        except ValueError:
            raise ValueError("Invalid phone")

        return {"message": f"OTP sent to {phone_e164}"}

    @staticmethod
    def verify_otp(phone: str, code: str):
        ok = verify_otp(phone, code)
        if not ok:
            return False

        try:
            phone_e164 = normalize_phone_to_e164(phone)
            user = User.objects.filter(phone=phone_e164).first()

            if user and not user.is_active:
                # Activate the user account after successful OTP verification
                user.is_active = True
                user.save(update_fields=["is_active"])

        except Exception as e:
            print(f"Error in verify_otp: {e}")
            return False

        return True

    @staticmethod
    def search_users(query: str, exclude_user_id=None, exclude_admin=True, limit: int = 20) -> List[User]:
        if not query or len(query.strip()) < 2:
            return []

        query = query.strip()

        # Search across username, email, and full_name
        # Using Q objects for complex queries
        search_filter = (
                Q(username__icontains=query) |
                Q(email__icontains=query) |
                Q(full_name__icontains=query)
        )

        # Only return active users
        queryset = User.objects.filter(search_filter, is_active=True)

        # Exclude specific user if provided (e.g., don't show current user in search)
        if exclude_user_id:
            queryset = queryset.exclude(id=exclude_user_id)

        # Exclude admin and staff users
        if exclude_admin:
            queryset = queryset.filter(is_staff=False, is_superuser=False)

        # Order by relevance: exact matches first, then partial matches
        # Prioritize username matches over email/full_name
        queryset = queryset.order_by('username')[:limit]

        return list(queryset)