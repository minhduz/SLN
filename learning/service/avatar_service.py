from ..models import Quiz
from django.core.files.storage import default_storage
from django.db import transaction
from accounts.tasks import delete_avatar_task
import logging,os,uuid

logger = logging.getLogger(__name__)

class QuizAvatarService:
    """
    Service class to manage quiz avatar operations:
    - Saving (with unique rename)
    - Deleting (async)
    """

    @staticmethod
    def rename_and_save_quiz_avatar(quiz: Quiz, avatar):
        """
        Save quiz avatar with a unique filename based on quiz.id + random UUID,
        ensuring unique URLs for cache-busting.
        """
        ext = os.path.splitext(avatar.name)[1].lower()
        # ✅ Add random UUID to make filename unique
        unique_id = uuid.uuid4().hex[:8]  # Use first 8 chars of UUID
        avatar_filename = f"quiz_avatars/{quiz.id}_{unique_id}{ext}"

        saved_path = default_storage.save(avatar_filename, avatar)
        logger.info(f"New quiz avatar saved: {saved_path}")
        return saved_path

    @transaction.atomic
    def delete_quiz_avatar(avatar_path):
        """
        Async delete quiz avatar from storage
        """
        if avatar_path:
            delete_avatar_task.delay(avatar_path)
            logger.info(f"Scheduled deletion of quiz avatar: {avatar_path}")
