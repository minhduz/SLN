from ..models import User
import os
import uuid
from django.core.files.storage import default_storage
from ..tasks import delete_avatar_task

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
