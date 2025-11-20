# gamification/services.py
from django.utils import timezone
from datetime import timedelta

from .squad_mission_services import SquadMissionService
from ..models import UserMission, Mission
from ..utils import get_user_current_date
import random
import logging

logger = logging.getLogger(__name__)


class MissionResetService:
    """
    Lazy reset service - checks and resets missions when user interacts with the app
    This is how Duolingo, Habitica, and most apps handle daily resets
    """

    @staticmethod
    def ensure_user_has_todays_missions(user):
        """
        Check if user has today's missions, if not create them
        Called on:
        - User opens missions page
        - User completes any action that tracks missions

        Returns:
            bool: True if new missions were created, False if already existed
        """
        user_today = get_user_current_date(user)

        # Check if user has daily missions for today (in their timezone)
        has_daily_missions = UserMission.objects.filter(
            user=user,
            cycle_date=user_today,
            mission__cycle='daily'
        ).exists()

        if not has_daily_missions:
            # Create today's daily missions
            MissionResetService._create_daily_missions(user, user_today)
            logger.info(f"Created daily missions for user {user.username} for {user_today}")
            return True

        return False

    @staticmethod
    def ensure_user_has_weekly_missions(user):
        """
        Check if user has this week's missions, if not create them

        Returns:
            bool: True if new missions were created, False if already existed
        """
        user_today = get_user_current_date(user)
        monday = user_today - timedelta(days=user_today.weekday())

        # Check if user has weekly missions for this week (in their timezone)
        has_weekly_missions = UserMission.objects.filter(
            user=user,
            cycle_date=monday,
            mission__cycle='weekly'
        ).exists()

        if not has_weekly_missions:
            # Create this week's missions
            MissionResetService._create_weekly_missions(user, monday)
            logger.info(f"Created weekly missions for user {user.username} for week of {monday}")
            return True

        return False

    @staticmethod
    def _ensure_user_squad_missions(user, cycle_date, cycle_type):
        """
        Ensure all squads the user belongs to have squad missions for this cycle
        """
        from squads.models import SquadMember

        # ✅ Changed: Use squads_members instead of squad_members
        user_squad_memberships = SquadMember.objects.filter(
            user=user
        ).select_related('squad')

        for membership in user_squad_memberships:
            try:
                SquadMissionService.ensure_squad_has_missions(
                    squad=membership.squad,
                    cycle_date=cycle_date,
                    cycle_type=cycle_type
                )
            except Exception as e:
                logger.error(
                    f"Error ensuring squad missions for squad {membership.squad.id}: {str(e)}",
                    exc_info=True
                )

    @staticmethod
    def _create_daily_missions(user, cycle_date):
        """Create daily missions for user - only INDIVIDUAL missions with random pool"""
        # ✅ Only get INDIVIDUAL daily missions that are in random pool
        daily_missions = Mission.objects.filter(
            cycle='daily',
            access_type='individual',
            is_active=True,
            is_random_pool=True
        )

        if not daily_missions.exists():
            logger.warning("No active individual daily missions in random pool found")
            return

        # Get pool size from first mission
        pool_size = daily_missions.first().pool_size
        selected_missions = random.sample(
            list(daily_missions),
            min(pool_size, daily_missions.count())
        )

        # Create missions
        created_missions = []
        for mission in selected_missions:
            user_mission = UserMission.objects.create(
                mission=mission,
                user=user,
                cycle_date=cycle_date,
                progress=0,
                metadata={}
            )
            created_missions.append(user_mission)

        logger.info(
            f"Created {len(created_missions)} individual daily missions for user {user.username} "
            f"for date {cycle_date}"
        )

        return created_missions

    @staticmethod
    def _create_weekly_missions(user, cycle_date):
        """Create weekly missions for user - only INDIVIDUAL missions"""
        # ✅ Only get INDIVIDUAL weekly missions (no random pool needed for weekly)
        weekly_missions = Mission.objects.filter(
            cycle='weekly',
            access_type='individual',
            is_active=True
        )

        if not weekly_missions.exists():
            logger.warning("No active individual weekly missions found")
            return

        # Create all weekly missions
        created_missions = []
        for mission in weekly_missions:
            user_mission = UserMission.objects.create(
                mission=mission,
                user=user,
                cycle_date=cycle_date,
                progress=0,
                metadata={}
            )
            created_missions.append(user_mission)

        logger.info(
            f"Created {len(created_missions)} individual weekly missions for user {user.username} "
            f"for week of {cycle_date}"
        )

        return created_missions