from celery import shared_task
from django.core.files.storage import default_storage
import logging

logger = logging.getLogger(__name__)

@shared_task
def delete_avatar_task(file_path):
    if default_storage.exists(file_path):
        default_storage.delete(file_path)

