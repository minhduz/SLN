from ..models import User
from .storage_service import upload_avatar_to_s3
from ..tasks import delete_avatar_task

def create_user(validated_data):
    avatar = validated_data.pop("avatar", None)
    password = validated_data.pop("password")
    user = User(**validated_data)
    user.set_password(password)

    if avatar:
        user.avatar_url = upload_avatar_to_s3(avatar)

    user.save()
    return user

def update_user(user, data):
    avatar = data.pop("avatar", None)
    old_avatar_url = user.avatar_url

    for attr, value in data.items():
        setattr(user, attr, value)

    if avatar:
        user.avatar_url = upload_avatar_to_s3(avatar)

    user.save()

    # enqueue async task
    if avatar and old_avatar_url:
        delete_avatar_task.delay(old_avatar_url)
    return user

class UserService:
    @staticmethod
    def get_my_profile(user: User):
        """
        Return current user profile.
        """
        return user
