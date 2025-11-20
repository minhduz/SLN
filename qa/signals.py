"""
Signals for mission tracking and popularity score calculation in QA app
These signals automatically track mission progress and update question popularity
when questions are created, answered, and viewed
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import F
from gamification.services.tracking_services import MissionService
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender='qa.Question')
def track_question_save_mission(sender, instance, created, **kwargs):
    """
    Signal handler: Track 'save_question' mission when a question is created

    This is triggered whenever a Question instance is saved to the database.
    We only track on creation (not updates) and only for questions that were
    created via the conversation save feature (is_ai_generated = True for answers).
    """
    try:
        # Get the user who created the question
        user = instance.user

        if not user or not user.is_authenticated:
            return

        # Prepare mission tracking context
        context_data = {
            'question_id': str(instance.id),
            'question_owner_id': str(user.id),
            'is_public': instance.is_public
        }

        # Track the mission
        MissionService.track_mission_progress(
            user=user,
            mission_type='save_question',
            context_data=context_data
        )

        logger.info(
            f"Tracked 'save_question' mission for user {user.id} "
            f"on question {instance.id}"
        )

    except Exception as e:
        logger.error(
            f"Error tracking save_question mission for question {instance.id}: {str(e)}",
            exc_info=True
        )


# ============================================================================
# ANSWER_QUESTION MISSION (NEW)
# ============================================================================

@receiver(post_save, sender='qa.Answer')
def track_answer_question_mission(sender, instance, created, **kwargs):
    """
    Signal handler: Track 'answer_question' mission when an answer is created
    by a community member AND update the question's popularity score.

    This is triggered whenever an Answer instance is saved to the database.
    We only track on creation (not updates) and only for non-AI-generated answers
    (skip AI answers from conversation saves).

    The mission tracks when users create answers to questions, contributing
    to the community knowledge base.

    Popularity Score: +2 points for each answer to the question
    """
    if not created:
        return

    try:
        # Skip AI-generated answers (these come from conversation saves)
        # We only track community-created answers
        if instance.is_ai_generated:
            logger.debug(
                f"Skipping AI-generated answer {instance.id} for mission tracking"
            )
            return

        # Get the user who created the answer
        user = instance.user

        if not user or not user.is_authenticated:
            return

        # Get the question this answer belongs to
        question = instance.question

        # ============================================================
        # TRACK MISSION
        # ============================================================
        # Prepare mission tracking context
        context_data = {
            'question_id': str(question.id),
            'question_owner_id': str(question.user.id),
            'is_public': getattr(question, 'is_public', True)
        }

        # Track the mission
        MissionService.track_mission_progress(
            user=user,
            mission_type='answer_question',
            context_data=context_data
        )

        logger.info(
            f"Tracked 'answer_question' mission for user {user.id} "
            f"on answer {instance.id} to question {question.id}"
        )

    except Exception as e:
        logger.error(
            f"Error tracking answer_question mission for answer {instance.id}: {str(e)}",
            exc_info=True
        )


# ============================================================================
# VERIFY_ANSWER & GET_VERIFIED MISSIONS (Combined - both trigger on same event)
# ============================================================================

@receiver(post_save, sender='qa.Question')
def track_verification_missions(sender, instance, created, **kwargs):
    """
    Signal handler: Track BOTH 'verify_answer' and 'get_verified' missions when
    a question owner marks an answer as verified.

    This single event triggers TWO missions:
    1. 'verify_answer' - Tracked for the question owner (person verifying)
    2. 'get_verified' - Tracked for the answer author (person getting verified)

    This is triggered whenever a Question instance is updated with a verified_answer.

    Args:
        sender: The model class (qa.Question)
        instance: The Question instance being saved
        created: Boolean - True if this is a new instance
        **kwargs: Additional signal arguments
    """
    # Skip on creation - only track on verified_answer update
    if created:
        return

    # Check if there's a verified answer set
    if not instance.verified_answer_id:
        logger.debug(f"No verified answer set for question {instance.id}")
        return

    try:
        # Get the question owner (person who verified)
        question_owner = instance.user

        if not question_owner or not question_owner.is_authenticated:
            logger.warning(f"Question owner not authenticated for verification missions")
            return

        # Get the verified answer and its author
        verified_answer = instance.verified_answer
        answer_author = verified_answer.user

        if not answer_author or not answer_author.is_authenticated:
            logger.warning(f"Answer author not authenticated for verification missions")
            return

        logger.info(
            f"Verification event detected: "
            f"question_owner={question_owner.id}, "
            f"answer_author={answer_author.id}, "
            f"question={instance.id}, "
            f"answer={verified_answer.id}"
        )

        # ============================================================
        # MISSION 1: Track 'verify_answer' for the question owner
        # ============================================================
        verify_context = {
            'question_id': str(instance.id),
            'answer_id': str(verified_answer.id),
            'answer_owner_id': str(answer_author.id)
        }

        MissionService.track_mission_progress(
            user=question_owner,  # Question owner gets credit
            mission_type='verify_answer',
            context_data=verify_context
        )

        logger.info(
            f"Tracked 'verify_answer' mission for question owner {question_owner.id} "
            f"on question {instance.id}"
        )

        # ============================================================
        # MISSION 2: Track 'get_verified' for the answer author
        # ============================================================
        get_verified_context = {
            'answer_id': str(verified_answer.id),
            'question_id': str(instance.id),
            'verifier_id': str(question_owner.id)  # Who verified it
        }

        MissionService.track_mission_progress(
            user=answer_author,  # Answer author gets credit
            mission_type='get_verified',
            context_data=get_verified_context
        )

        logger.info(
            f"Tracked 'get_verified' mission for answer author {answer_author.id} "
            f"on answer {verified_answer.id}"
        )

    except Exception as e:
        logger.error(
            f"Error tracking verification missions for question {instance.id}: {str(e)}",
            exc_info=True
        )


@receiver(post_save, sender='qa.UserQuestionView')
def track_view_question_mission(sender, instance, created, **kwargs):
    """
    Signal handler: Track 'view_question' mission when a user views a question
    AND update the question's popularity score.

    This is triggered whenever a UserQuestionView instance is created.
    We only track on creation (not updates) and only for questions viewed by
    users other than the question owner.

    Popularity Score: +1 point for each unique view of the question

    Args:
        sender: The model class (qa.UserQuestionView)
        instance: The UserQuestionView instance being saved
        created: Boolean - True if this is a new instance
        **kwargs: Additional signal arguments
    """
    # Only track on creation (first view)
    if not created:
        logger.debug(f"Skipping existing view record for mission tracking")
        return

    try:
        user = instance.user
        question = instance.question

        logger.info(f"View signal triggered: user={user.id}, question={question.id}, created={created}")

        if not user or not user.is_authenticated:
            logger.warning(f"User not authenticated for view mission tracking")
            return

        # ============================================================
        # TRACK MISSION
        # ============================================================
        # Optional: Skip mission tracking if user is viewing their own question
        if question.user_id == user.id:
            logger.info(f"Skipping view mission - user viewing own question (but score was updated)")
            return

        # Prepare mission tracking context
        context_data = {
            'question_id': str(question.id),
            'question_owner_id': str(question.user.id),
            'is_public': question.is_public
        }

        # Track the mission
        MissionService.track_mission_progress(
            user=user,
            mission_type='view_question',
            context_data=context_data
        )

        logger.info(
            f"Tracked 'view_question' mission for user {user.id} "
            f"on question {question.id}"
        )

    except Exception as e:
        logger.error(
            f"Error tracking view_question mission for view record: {str(e)}",
            exc_info=True
        )