from ..models import User
import os
import uuid
from django.core.files.storage import default_storage
from ..tasks import delete_avatar_task

def create_user(validated_data):
    avatar = validated_data.pop("avatar", None)
    password = validated_data.pop("password")
    user = User(**validated_data)
    user.set_password(password)
    user.save()

    if avatar:
        # Get extension (.png, .jpg, etc.)
        ext = os.path.splitext(avatar.name)[1].lower()
        # Build filename based on user.id
        avatar_filename = f"avatars/{user.id}{ext}"
        # Save to storage (S3 if configured)
        saved_path = default_storage.save(avatar_filename, avatar)
        # Store the S3 URL in DB
        user.avatar.name = saved_path
        user.save()

    return user

def update_user(user, data):
    old_avatar = user.avatar  # keep ref for cleanup if needed

    for attr, value in data.items():
        setattr(user, attr, value)

    user.save()

    # enqueue async deletion of old avatar if replaced
    if "avatar" in data and old_avatar:
        delete_avatar_task.delay(old_avatar.name)  # use .name for S3 path
    return user

class UserService:
    @staticmethod
    def get_my_profile(user: User):
        """
        Return current user profile.
        """
        return user
