# gamification/services.py
from django.utils import timezone
from datetime import timedelta
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
    def _create_daily_missions(user, cycle_date):
        """Create daily missions for user"""
        daily_missions = Mission.objects.filter(
            cycle='daily',
            is_active=True
        )

        if not daily_missions.exists():
            logger.warning("No active daily missions found")
            return

        # Get missions that are in random pool
        pool_missions = daily_missions.filter(is_random_pool=True)

        if pool_missions.exists():
            pool_size = pool_missions.first().pool_size
            selected_missions = random.sample(
                list(pool_missions),
                min(pool_size, pool_missions.count())
            )
        else:
            # If no pool, assign all daily missions
            selected_missions = list(daily_missions)

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
            f"Created {len(created_missions)} daily missions for user {user.username} "
            f"for date {cycle_date}"
        )

        return created_missions

    @staticmethod
    def _create_weekly_missions(user, cycle_date):
        """Create weekly missions for user"""
        weekly_missions = Mission.objects.filter(
            cycle='weekly',
            is_active=True
        )

        if not weekly_missions.exists():
            logger.warning("No active weekly missions found")
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
            f"Created {len(created_missions)} weekly missions for user {user.username} "
            f"for week of {cycle_date}"
        )

        return created_missions