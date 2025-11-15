"""
Signals for mission tracking in Learning app
These signals automatically track mission progress when quizzes are completed
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from gamification.services.tracking_services import MissionService
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# COMPLETE_QUIZ MISSION
# ============================================================================

@receiver(post_save, sender='learning.QuizAttempt')
def track_complete_quiz_mission(sender, instance, created, **kwargs):
    """
    Signal handler: Track 'complete_quiz' mission when a user completes a quiz attempt.

    We track on UPDATE (not creation) because:
    - QuizAttempt is created with score=0
    - Answers are processed and score is calculated
    - QuizAttempt is updated with final score

    This ensures we capture the correct score for mission tracking.
    """
    # 🔍 DEBUG: Log that signal was called
    logger.info(
        f"🔔 Signal FIRED: post_save for QuizAttempt {instance.id} | "
        f"created={created} | score={instance.score}% | user={instance.user.id}"
    )

    # ✅ CHANGED: Track on UPDATE, not creation
    # Skip if this is the initial creation (score will be 0)
    if created:
        logger.info(f"⏭️ Skipping: QuizAttempt {instance.id} was just created (score not finalized yet)")
        return

    # Only track if score has been finalized (greater than 0 or all answers processed)
    # This prevents tracking multiple times on subsequent updates
    if not hasattr(instance, '_mission_tracked'):
        try:
            user = instance.user

            if not user:
                logger.warning(f"⚠️ No user found for QuizAttempt {instance.id}")
                return

            if not user.is_authenticated:
                logger.warning(f"⚠️ User {user.id} is not authenticated")
                return

            quiz = instance.quiz
            logger.info(f"📊 Processing quiz attempt: quiz_id={quiz.id}, user_id={user.id}")

            # Get the finalized score
            score_percentage = instance.score if instance.score is not None else 0
            logger.info(f"📈 Final score: {score_percentage}%")

            # Prepare context data
            context_data = {
                'quiz_id': str(quiz.id),
                'score': score_percentage,
                'passing_score': getattr(quiz, 'passing_score', 50)
            }

            logger.info(f"📦 Context data prepared: {context_data}")

            # Track the mission
            logger.info(f"🎯 Calling MissionService.track_mission_progress...")
            MissionService.track_mission_progress(
                user=user,
                mission_type='complete_quiz',
                context_data=context_data
            )

            # Mark as tracked to prevent duplicate tracking on subsequent updates
            instance._mission_tracked = True

            logger.info(
                f"✅ Successfully tracked 'complete_quiz' mission for user {user.id} "
                f"on quiz {quiz.id} with score {score_percentage}%"
            )

        except Exception as e:
            logger.error(
                f"❌ Error tracking complete_quiz mission for attempt {instance.id}: {str(e)}",
                exc_info=True
            )

# ============================================================================
# RATE_QUIZ MISSION (Rate quiz attempts)
# ============================================================================

@receiver(post_save, sender='learning.QuizAttempt')
def track_rate_quiz_mission(sender, instance, created, updated_fields=None, **kwargs):
    """
    Signal handler: Track 'rate_quiz' mission when a user rates a quiz attempt.

    This is triggered whenever a QuizAttempt instance is updated.
    We track when the rating field is set (goes from None to a value).

    The mission tracks when users rate their quiz attempts, providing feedback
    on their learning experience.

    Args:
        sender: The model class (learning.QuizAttempt)
        instance: The QuizAttempt instance being saved
        created: Boolean - True if this is a new instance
        updated_fields: Set of field names that were updated
        **kwargs: Additional signal arguments
    """
    # Skip on creation - only track on rating update
    if created:
        return

    # Check if rating field was updated
    if updated_fields and 'rating' not in updated_fields:
        return

    # Verify that rating is now set (not None)
    if not hasattr(instance, 'rating') or instance.rating is None:
        return

    try:
        # Get the user who rated the attempt
        user = instance.user

        if not user or not user.is_authenticated:
            return

        # Get the quiz that was attempted
        quiz = instance.quiz

        # Prepare mission tracking context
        context_data = {
            'quiz_id': str(quiz.id),
            'attempt_id': str(instance.id),
            'rating': instance.rating
        }

        # Track the mission
        MissionService.track_mission_progress(
            user=user,
            mission_type='rate_quiz',
            context_data=context_data
        )

        logger.info(
            f"✅ Tracked 'rate_quiz' mission for user {user.id} "
            f"on attempt {instance.id} with rating {instance.rating}"
        )

    except Exception as e:
        logger.error(
            f"❌ Error tracking rate_quiz mission for attempt {instance.id}: {str(e)}",
            exc_info=True
        )

