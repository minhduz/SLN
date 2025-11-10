# learning/tasks.py
from celery import shared_task
from django.db.models import Avg, Count
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def recalculate_quiz_rating(self, quiz_id):
    """
    Celery task to recalculate the average rating for a quiz

    This task is triggered whenever a user rates a quiz attempt.
    It calculates the average rating from all rated attempts.

    Args:
        quiz_id (str): UUID of the quiz

    Returns:
        dict: Result with updated rating info
    """
    try:
        from .models import Quiz, QuizAttempt

        # Get the quiz
        quiz = Quiz.objects.get(id=quiz_id)

        # Calculate average rating from all rated attempts
        rating_stats = QuizAttempt.objects.filter(
            quiz=quiz,
            rating__isnull=False
        ).aggregate(
            avg_rating=Avg('rating'),
            rating_count=Count('id')
        )

        avg_rating = rating_stats['avg_rating']
        rating_count = rating_stats['rating_count']

        # Update quiz rating
        if avg_rating is not None:
            quiz.rating = Decimal(str(round(float(avg_rating), 2)))
            quiz.rating_count = rating_count
        else:
            quiz.rating = Decimal('0.00')
            quiz.rating_count = 0

        quiz.save(update_fields=['rating', 'rating_count', 'updated_at'])

        logger.info(
            f"Quiz {quiz_id} rating recalculated: "
            f"{quiz.rating} (from {rating_count} ratings)"
        )

        return {
            'success': True,
            'quiz_id': str(quiz_id),
            'average_rating': float(quiz.rating),
            'rating_count': rating_count
        }

    except Exception as e:
        logger.error(f"Error recalculating rating for quiz {quiz_id}: {str(e)}")
        # Retry the task
        raise self.retry(exc=e, countdown=60)


@shared_task
def recalculate_all_quiz_ratings():
    """
    Celery task to recalculate ratings for ALL quizzes

    This is useful for:
    - Initial migration when adding the rating system
    - Periodic maintenance
    - Fixing any data inconsistencies

    Can be run manually or scheduled in CELERY_BEAT_SCHEDULE
    """
    try:
        from .models import Quiz

        quizzes = Quiz.objects.all()
        total_quizzes = quizzes.count()
        updated_count = 0

        logger.info(f"Starting recalculation of ratings for {total_quizzes} quizzes")

        for quiz in quizzes:
            try:
                # Trigger individual recalculation task
                recalculate_quiz_rating.delay(str(quiz.id))
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to queue rating recalculation for quiz {quiz.id}: {str(e)}")

        logger.info(
            f"Queued rating recalculation for {updated_count}/{total_quizzes} quizzes"
        )

        return {
            'success': True,
            'total_quizzes': total_quizzes,
            'queued_count': updated_count
        }

    except Exception as e:
        logger.error(f"Error in recalculate_all_quiz_ratings: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def cleanup_unrated_old_attempts():
    """
    Celery task to send reminders or cleanup unrated attempts older than X days

    This can be used to:
    - Remind users to rate their attempts
    - Auto-expire old attempts without ratings
    - Generate analytics on rating participation
    """
    try:
        from .models import QuizAttempt
        from django.utils import timezone
        from datetime import timedelta

        # Get attempts older than 7 days without ratings
        cutoff_date = timezone.now() - timedelta(days=7)

        unrated_attempts = QuizAttempt.objects.filter(
            rating__isnull=True,
            created_at__lt=cutoff_date
        ).select_related('user', 'quiz')

        count = unrated_attempts.count()

        logger.info(f"Found {count} unrated attempts older than 7 days")

        # You could:
        # 1. Send reminder emails/notifications
        # 2. Auto-expire these attempts
        # 3. Just log for analytics

        return {
            'success': True,
            'unrated_attempts_count': count,
            'cutoff_date': cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"Error in cleanup_unrated_old_attempts: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }