# gamification/services/squad_mission_services.py

from django.db import transaction
from django.utils import timezone
from gamification.models import Mission, UserMission, SquadMissionProgress, MissionReward
from economy.models import UserCurrency
import logging

logger = logging.getLogger(__name__)


class SquadMissionService:
    """
    Service for managing squad missions where all members must complete individual missions
    """

    @staticmethod
    def ensure_squad_has_missions(squad, cycle_date, cycle_type='daily'):
        """
        Ensure squad has squad mission progress tracking for the given cycle

        Args:
            squad: Squad instance
            cycle_date: Date for the mission cycle
            cycle_type: 'daily' or 'weekly'
        """
        squad_missions = Mission.objects.filter(
            cycle=cycle_type,
            access_type='squad',
            is_active=True,
            require_all_members=True
        )

        for mission in squad_missions:
            SquadMissionProgress.objects.get_or_create(
                squad=squad,
                mission=mission,
                cycle_date=cycle_date,
                defaults={
                    'completed_members': []
                }
            )

        logger.info(
            f"Ensured squad {squad.name} has {squad_missions.count()} "
            f"{cycle_type} squad missions for {cycle_date}"
        )

    @staticmethod
    @transaction.atomic
    def check_member_completion(user, squad, cycle_date, cycle_type='daily'):
        """
        Check if a user has completed all their individual missions for a cycle,
        and update squad mission progress accordingly.

        This should be called whenever a user completes a mission.

        Args:
            user: User instance
            squad: Squad instance
            cycle_date: Date for the mission cycle
            cycle_type: 'daily' or 'weekly'
        """
        logger.info(
            f"🔍 check_member_completion | user={user.username} | squad={squad.name} | "
            f"cycle={cycle_type} | date={cycle_date}"
        )

        # ✅ FIXED: Check user's actual assigned missions, not all possible missions
        user_missions = UserMission.objects.filter(
            user=user,
            cycle_date=cycle_date,
            mission__cycle=cycle_type,
            mission__access_type='individual',
            mission__is_active=True
        ).select_related('mission')

        total_missions = user_missions.count()
        logger.info(f"  Found {total_missions} {cycle_type} individual missions assigned to user")

        if total_missions == 0:
            logger.warning(f"  ⚠️  No missions assigned to user for this cycle")
            return

        # Check if user has completed ALL their assigned missions for this cycle
        user_completed_all = True
        completed_count = 0

        for user_mission in user_missions:
            if user_mission.is_completed:
                completed_count += 1
                logger.info(f"  ✓ {user_mission.mission.title} completed")
            else:
                logger.info(f"  ✗ {user_mission.mission.title} NOT completed")
                user_completed_all = False

        logger.info(
            f"  Summary: {completed_count}/{total_missions} missions completed"
        )

        if not user_completed_all:
            logger.info(
                f"⏸️  User {user.username} has not completed all {cycle_type} missions yet"
            )
            return

        logger.info(
            f"✅ User {user.username} completed ALL {cycle_type} individual missions!"
        )

        # User completed all individual missions - update squad progress
        SquadMissionService._update_squad_progress(user, squad, cycle_date, cycle_type)

    @staticmethod
    @transaction.atomic
    def _update_squad_progress(user, squad, cycle_date, cycle_type):
        """
        Update squad mission progress when a member completes all individual missions
        """
        logger.info(
            f"📊 _update_squad_progress | user={user.username} | squad={squad.name}"
        )

        # Get squad missions for this cycle
        squad_missions = SquadMissionProgress.objects.filter(
            squad=squad,
            mission__cycle=cycle_type,
            cycle_date=cycle_date,
            is_completed=False  # Only update incomplete squad missions
        ).select_for_update()

        logger.info(f"  Found {squad_missions.count()} squad missions to update")

        user_id_str = str(user.id)

        for squad_progress in squad_missions:
            logger.info(f"  Updating: {squad_progress.mission.title}")

            # Add user to completed members if not already there
            completed_members = squad_progress.completed_members
            if not isinstance(completed_members, list):
                completed_members = []

            if user_id_str not in completed_members:
                completed_members.append(user_id_str)
                squad_progress.completed_members = completed_members
                squad_progress.save()

                total_members = squad.memberships.count()

                logger.info(
                    f"  ➕ Added {user.username} | {len(completed_members)}/{total_members} members done"
                )

            # Check if ALL squad members have now completed
            if squad_progress.check_all_members_completed():
                logger.info(f"  🎉 All members completed! Completing squad mission...")
                SquadMissionService._complete_squad_mission(squad_progress)

    @staticmethod
    @transaction.atomic
    def _complete_squad_mission(squad_progress):
        """
        Mark squad mission as complete and distribute rewards to all members
        """
        if squad_progress.is_completed:
            logger.warning(f"Squad mission {squad_progress.id} already completed")
            return

        # Mark as completed
        squad_progress.is_completed = True
        squad_progress.completed_at = timezone.now()
        squad_progress.save()

        logger.info(
            f"🏆 Squad {squad_progress.squad.name} completed: {squad_progress.mission.title}"
        )

        # Distribute rewards to all squad members
        SquadMissionService._distribute_rewards(squad_progress)

    @staticmethod
    @transaction.atomic
    def _distribute_rewards(squad_progress):
        """
        Distribute mission rewards to all squad members
        """
        if squad_progress.rewards_distributed:
            logger.warning(f"Rewards already distributed for squad mission {squad_progress.id}")
            return

        squad = squad_progress.squad
        mission = squad_progress.mission

        # Get all rewards for this mission
        rewards = MissionReward.objects.filter(mission=mission).select_related('currency')

        if not rewards.exists():
            logger.warning(f"No rewards configured for squad mission {mission.title}")
            return

        logger.info(
            f"💸 Distributing rewards to {squad.memberships.count()} squad members"
        )

        # ✅ Changed: Get all squad members through memberships
        squad_memberships = squad.memberships.select_related('user').all()

        for membership in squad_memberships:
            user = membership.user

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
                    f"  💰 {user.username} +{reward.amount} {reward.currency.name} | "
                    f"{old_balance}→{user_currency.balance}"
                )

        # Mark rewards as distributed
        squad_progress.rewards_distributed = True
        squad_progress.save()

        logger.info(
            f"✅ Rewards distributed to all {squad_memberships.count()} members"
        )