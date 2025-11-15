# learning/tasks.py
from celery import shared_task
from django.db.models import Avg, Count
from decimal import Decimal
import logging
from .models import Quiz, QuizAttempt
from gamification.services.tracking_services import MissionService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def recalculate_quiz_rating(self, quiz_id):
    """
    Celery task to recalculate the average rating for a quiz
    AND track 'create_quiz' mission if rating reaches 4+ stars

    This task is triggered whenever a user rates a quiz attempt.
    It calculates the average rating from all rated attempts and
    tracks the create_quiz mission if the quiz reaches 4+ stars.

    Args:
        quiz_id (str): UUID of the quiz

    Returns:
        dict: Result with updated rating info
    """
    try:
        # Get the quiz
        quiz = Quiz.objects.get(id=quiz_id)

        # Store old rating to detect if it crossed the 4.0 threshold
        old_rating = quiz.rating if quiz.rating else Decimal('0.00')

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
            new_rating = Decimal(str(round(float(avg_rating), 2)))
            quiz.rating = new_rating
            quiz.rating_count = rating_count
        else:
            new_rating = Decimal('0.00')
            quiz.rating = new_rating
            quiz.rating_count = 0

        quiz.save(update_fields=['rating', 'rating_count', 'updated_at'])

        logger.info(
            f"📊 Quiz {quiz_id} rating recalculated: "
            f"{old_rating} → {quiz.rating} (from {rating_count} ratings)"
        )

        # ============================================================
        # MISSION TRACKING: create_quiz (4+ stars)
        # ============================================================
        # Check if quiz just reached 4.0+ stars (crossed threshold)
        if quiz.rating >= Decimal('4.0') > old_rating:
            try:
                quiz_creator = quiz.created_by

                if quiz_creator and quiz_creator.is_authenticated:
                    # Prepare mission tracking context
                    context_data = {
                        'quiz_id': str(quiz.id),
                        'rating': float(quiz.rating),
                        'min_rating': 4.0,
                        'rating_count': rating_count
                    }

                    # Track the mission for the quiz creator
                    MissionService.track_mission_progress(
                        user=quiz_creator,
                        mission_type='create_quiz',
                        context_data=context_data
                    )

                    logger.info(
                        f"✅ Tracked 'create_quiz' mission for user {quiz_creator.id} "
                        f"on quiz {quiz.id} with rating {quiz.rating} stars "
                        f"(crossed 4.0 threshold from {old_rating})"
                    )
                else:
                    logger.warning(f"⚠️ Quiz creator not authenticated for create_quiz mission")

            except Exception as mission_error:
                # Don't fail the entire task if mission tracking fails
                logger.error(
                    f"❌ Error tracking create_quiz mission for quiz {quiz_id}: {str(mission_error)}",
                    exc_info=True
                )

        return {
            'success': True,
            'quiz_id': str(quiz_id),
            'old_rating': float(old_rating),
            'new_rating': float(quiz.rating),
            'rating_count': rating_count,
            'mission_tracked': quiz.rating >= Decimal('4.0') > old_rating
        }

    except Exception as e:
        logger.error(f"Error recalculating rating for quiz {quiz_id}: {str(e)}")
        # Retry the task
        raise self.retry(exc=e, countdown=60)