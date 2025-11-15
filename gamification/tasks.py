# gamification/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import UserMission
import logging

logger = logging.getLogger(__name__)


@shared_task
def cleanup_old_missions():
    """
    Clean up old completed missions
    Keep last 30 days only
    Run this daily to keep database clean

    This is the ONLY scheduled task needed with lazy reset strategy
    """
    cutoff_date = timezone.now().date() - timedelta(days=30)

    deleted_count, _ = UserMission.objects.filter(
        cycle_date__lt=cutoff_date,
        is_completed=True
    ).delete()

    logger.info(f"Cleaned up {deleted_count} old completed missions")
    return f"Cleaned up {deleted_count} old missions"