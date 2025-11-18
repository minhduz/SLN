# gamification/tracking_services.py
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from gamification.models import Mission, UserMission, MissionReward
from economy.models import UserCurrency
from .reset_services import MissionResetService
import logging

logger = logging.getLogger(__name__)


class MissionService:
    """
    Centralized service for tracking mission progress
    """

    @staticmethod
    def track_mission_progress(user, mission_type, context_data=None):
        """
        Universal mission tracker

        Args:
            user: User instance
            mission_type: Mission type from TYPE_CHOICES
            context_data: Dict with action context

        Example:
            MissionService.track_mission_progress(
                user=request.user,
                mission_type='answer_question',
                context_data={
                    'question_id': str(question_id),
                    'question_owner_id': str(question.user.id),
                    'is_public': question.is_public
                }
            )
        """
        if not user or not user.is_authenticated:
            return

        # ✅ LAZY RESET: Ensure user has current missions before tracking
        MissionResetService.ensure_user_has_todays_missions(user)
        MissionResetService.ensure_user_has_weekly_missions(user)

        context_data = context_data or {}
        today = timezone.now().date()

        try:
            # Get user's active missions for today/this week
            user_missions = UserMission.objects.filter(
                user=user,
                mission__type=mission_type,
                mission__is_active=True,
                is_completed=False,
                cycle_date=today  # For daily missions
            ).select_related('mission')

            # Also check for weekly missions (cycle_date is Monday of current week)
            monday = today - timedelta(days=today.weekday())

            weekly_missions = UserMission.objects.filter(
                user=user,
                mission__type=mission_type,
                mission__is_active=True,
                mission__cycle='weekly',
                is_completed=False,
                cycle_date=monday
            ).select_related('mission')

            all_missions = list(user_missions) + list(weekly_missions)

            logger.info(
                f"track_mission_progress | "
                f"user={user.username} | "
                f"mission_type={mission_type} | "
                f"found_missions={len(all_missions)} | "
                f"context={context_data}"
            )

            for user_mission in all_missions:
                if MissionService._validate_conditions(user_mission.mission, user_mission, context_data):
                    MissionService._increment_progress(user_mission, context_data)
                else:
                    logger.info(
                        f"Validation failed | "
                        f"mission={user_mission.mission.title} | "
                        f"conditions={user_mission.mission.get_conditions()}"
                    )

        except Exception as e:
            logger.error(f"Error tracking mission progress for user {user.id}: {str(e)}", exc_info=True)

    @staticmethod
    def _validate_conditions(mission, user_mission, context_data):
        """
        Generic condition validator
        """
        conditions = mission.get_conditions()

        logger.info(
            f"_validate_conditions | "
            f"mission={mission.title} | "
            f"type={mission.type} | "
            f"conditions={conditions}"
        )

        if not conditions:
            logger.info("No conditions to validate, returning True")
            return True

        # Question-related validations
        if mission.type in ['answer_question', 'save_question', 'view_question']:
            # Check exclude_own_questions
            if conditions.get('exclude_own_questions', False):
                question_owner_id = context_data.get('question_owner_id')
                if question_owner_id and str(question_owner_id) == str(user_mission.user.id):
                    logger.info(f"Own question excluded | owner={question_owner_id}")
                    return False

            # Check only_public_questions
            if conditions.get('only_public_questions', False):
                is_public = context_data.get('is_public', True)
                if not is_public:
                    logger.info(f"Private question excluded")
                    return False

        # Quiz-related validations
        if mission.type == 'complete_quiz':
            # Check minimum score
            if 'min_score' in conditions:
                score = context_data.get('score', 0)
                logger.info(f"Score check | required={conditions['min_score']} | actual={score}")
                if score < conditions['min_score']:
                    logger.info(f"Score too low")
                    return False

            # Check unique quizzes
            if conditions.get('unique_quizzes', False):
                quiz_id = context_data.get('quiz_id')
                if quiz_id:
                    metadata = user_mission.get_metadata()
                    completed_quiz_ids = metadata.get('completed_quiz_ids', [])
                    logger.info(
                        f"Unique quiz check | "
                        f"quiz_id={quiz_id} | "
                        f"completed_ids={completed_quiz_ids} | "
                        f"is_duplicate={str(quiz_id) in completed_quiz_ids}"
                    )
                    if str(quiz_id) in completed_quiz_ids:
                        logger.warning(f"DUPLICATE QUIZ in validation | {quiz_id} already completed")
                        return False

        # Verification validations
        if mission.type == 'get_verified':
            # Check unique verifiers
            if conditions.get('unique_verifiers', False):
                verifier_id = context_data.get('verifier_id')
                if verifier_id:
                    metadata = user_mission.get_metadata()
                    verifier_ids = metadata.get('verifier_ids', [])
                    logger.info(
                        f"✓ Unique verifier check | "
                        f"verifier_id={verifier_id} | "
                        f"previous_verifiers={verifier_ids}"
                    )
                    if str(verifier_id) in verifier_ids:
                        logger.warning(f" DUPLICATE VERIFIER | {verifier_id} already verified")
                        return False

        # Quiz creation validations (Create 3 quizzes with 4+ stars)
        if mission.type == 'create_quiz':
            # Check minimum rating
            if 'min_rating' in conditions:
                rating = context_data.get('rating', 0)
                logger.info(f"Rating check | required={conditions['min_rating']} | actual={rating}")
                if rating < conditions['min_rating']:
                    logger.info(f"Rating too low")
                    return False

            # Check if this quiz was already counted
            quiz_id = context_data.get('quiz_id')
            if quiz_id:
                metadata = user_mission.get_metadata()
                counted_quiz_ids = metadata.get('counted_quiz_ids', [])
                logger.info(
                    f"Quiz creation check | "
                    f"quiz_id={quiz_id} | "
                    f"counted_ids={counted_quiz_ids}"
                )
                if str(quiz_id) in counted_quiz_ids:
                    logger.warning(f"DUPLICATE QUIZ CREATION | {quiz_id} already counted")
                    return False

        logger.info("All conditions passed")
        return True

    @staticmethod
    @transaction.atomic
    def _increment_progress(user_mission, context_data):
        """
        Increment progress and update metadata
        """
        user_mission = UserMission.objects.select_for_update().get(id=user_mission.id)

        # Update metadata for tracking
        metadata = user_mission.get_metadata()

        logger.info(
            f"_increment_progress | "
            f"mission={user_mission.mission.title} | "
            f"type={user_mission.mission.type} | "
            f"user={user_mission.user.username} | "
            f"current_progress={user_mission.progress}/{user_mission.mission.target_count} | "
            f"metadata={metadata}"
        )

        # Track unique quiz IDs for complete_quiz mission
        if user_mission.mission.type == 'complete_quiz' and context_data.get('quiz_id'):
            completed_quiz_ids = metadata.get('completed_quiz_ids', [])
            quiz_id = str(context_data['quiz_id'])

            logger.info(
                f"QUIZ COMPLETION TRACKING | "
                f"quiz_id={quiz_id} | "
                f"already_completed={completed_quiz_ids} | "
                f"is_duplicate={quiz_id in completed_quiz_ids}"
            )

            if quiz_id not in completed_quiz_ids:
                completed_quiz_ids.append(quiz_id)
                metadata['completed_quiz_ids'] = completed_quiz_ids
                logger.info(f"NEW quiz added to tracking | updated_list={completed_quiz_ids}")
            else:
                # ⚠️ CRITICAL: This should never happen because _validate_conditions should catch it
                # But adding as safety net
                logger.error(
                    f"DUPLICATE QUIZ BYPASSED VALIDATION! | "
                    f"quiz_id={quiz_id} already in {completed_quiz_ids} | "
                    f"This should have been caught in _validate_conditions!"
                )
                return

        # Track unique verifier IDs
        if user_mission.mission.type == 'get_verified' and context_data.get('verifier_id'):
            verifier_ids = metadata.get('verifier_ids', [])
            verifier_id = str(context_data['verifier_id'])

            logger.info(
                f"✓ VERIFICATION TRACKING | "
                f"verifier_id={verifier_id} | "
                f"already_verified_by={verifier_ids} | "
                f"is_duplicate={verifier_id in verifier_ids}"
            )

            if verifier_id not in verifier_ids:
                verifier_ids.append(verifier_id)
                metadata['verifier_ids'] = verifier_ids
                logger.info(f"NEW verifier added | updated_list={verifier_ids}")
            else:
                logger.error(
                    f"DUPLICATE VERIFIER BYPASSED VALIDATION! | "
                    f"verifier_id={verifier_id} already in {verifier_ids}"
                )
                return

        # Track unique question IDs for view_question
        if user_mission.mission.type == 'view_question' and context_data.get('question_id'):
            viewed_question_ids = metadata.get('viewed_question_ids', [])
            question_id = str(context_data['question_id'])

            logger.info(
                f"VIEW TRACKING | "
                f"question_id={question_id} | "
                f"already_viewed={viewed_question_ids} | "
                f"is_duplicate={question_id in viewed_question_ids}"
            )

            if question_id not in viewed_question_ids:
                viewed_question_ids.append(question_id)
                metadata['viewed_question_ids'] = viewed_question_ids
                logger.info(f"NEW question view | updated_list={viewed_question_ids}")
            else:
                # Don't increment if already viewed this question
                logger.info(f"Skipping duplicate view | question already viewed")
                return

        # Track unique saved question IDs
        if user_mission.mission.type == 'save_question' and context_data.get('question_id'):
            saved_question_ids = metadata.get('saved_question_ids', [])
            question_id = str(context_data['question_id'])

            logger.info(
                f"SAVE TRACKING | "
                f"question_id={question_id} | "
                f"already_saved={saved_question_ids} | "
                f"is_duplicate={question_id in saved_question_ids}"
            )

            if question_id not in saved_question_ids:
                saved_question_ids.append(question_id)
                metadata['saved_question_ids'] = saved_question_ids
                logger.info(f"NEW save | updated_list={saved_question_ids}")
            else:
                # Don't increment if already saved this question
                logger.info(f"Skipping duplicate save | question already saved")
                return

        # Track quiz IDs that achieved required rating for create_quiz mission
        if user_mission.mission.type == 'create_quiz' and context_data.get('quiz_id'):
            counted_quiz_ids = metadata.get('counted_quiz_ids', [])
            quiz_id = str(context_data['quiz_id'])

            logger.info(
                f"CREATE QUIZ TRACKING | "
                f"quiz_id={quiz_id} | "
                f"rating={context_data.get('rating', 'N/A')} | "
                f"already_counted={counted_quiz_ids} | "
                f"is_duplicate={quiz_id in counted_quiz_ids}"
            )

            if quiz_id not in counted_quiz_ids:
                counted_quiz_ids.append(quiz_id)
                metadata['counted_quiz_ids'] = counted_quiz_ids
                logger.info(f"NEW quiz creation | updated_list={counted_quiz_ids}")
            else:
                logger.error(
                    f"DUPLICATE QUIZ CREATION BYPASSED VALIDATION! | "
                    f"quiz_id={quiz_id} already in {counted_quiz_ids}"
                )
                return

        # Save metadata updates
        user_mission.metadata = metadata

        # Increment progress
        old_progress = user_mission.progress
        user_mission.progress += 1

        logger.info(
            f"PROGRESS INCREMENTED | "
            f"mission={user_mission.mission.title} | "
            f"progress: {old_progress} → {user_mission.progress} | "
            f"target={user_mission.mission.target_count}"
        )

        # Check completion
        if user_mission.progress >= user_mission.mission.target_count:
            user_mission.is_completed = True
            user_mission.completed_at = timezone.now()

            logger.info(
                f"MISSION COMPLETED! | "
                f"mission={user_mission.mission.title} | "
                f"user={user_mission.user.username} | "
                f"final_progress={user_mission.progress}/{user_mission.mission.target_count}"
            )

            # Award rewards
            MissionService._award_rewards(user_mission.mission, user_mission.user)
        else:
            logger.info(
                f"Mission in progress | "
                f"{user_mission.progress}/{user_mission.mission.target_count} completed"
            )

        user_mission.save()
        logger.info(f"UserMission saved | id={user_mission.id} | metadata={user_mission.metadata}")

    @staticmethod
    @transaction.atomic
    def _award_rewards(mission, user):
        """
        Award currency rewards to user
        """
        rewards = MissionReward.objects.filter(mission=mission).select_related('currency')

        for reward in rewards:
            user_currency, created = UserCurrency.objects.get_or_create(
                user=user,
                currency=reward.currency,
                defaults={'balance': 0}
            )

            old_balance = user_currency.balance
            user_currency.balance += reward.amount
            user_currency.save()

            logger.info(
                f"Reward awarded | "
                f"user={user.username} | "
                f"currency={reward.currency.name} | "
                f"amount=+{reward.amount} | "
                f"balance: {old_balance} → {user_currency.balance} | "
                f"mission={mission.title}"
            )