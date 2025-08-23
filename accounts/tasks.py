# users/tasks.py
from celery import shared_task
from django.core.files.storage import default_storage

@shared_task
def delete_avatar_task(old_avatar_url):
    try:
        default_storage.delete(old_avatar_url)
        print(f"Deleted old avatar: {old_avatar_url}")
    except Exception as e:
        print(f"Failed to delete {old_avatar_url}: {e}")
