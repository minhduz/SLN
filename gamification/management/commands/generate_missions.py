# gamification/management/commands/generate_missions.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from gamification.models import Mission, UserMission, SquadMissionProgress
from gamification.utils import get_user_current_date, get_user_timezone
from django.contrib.auth import get_user_model
from datetime import timedelta
import random

User = get_user_model()


class Command(BaseCommand):
    help = 'Generate missions for all users (for testing) - Uses user timezone'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=str,
            help='Generate missions for specific user ID only',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force regenerate missions even if they already exist for today/this week',
        )
        parser.add_argument(
            '--daily-only',
            action='store_true',
            help='Generate only daily missions',
        )
        parser.add_argument(
            '--weekly-only',
            action='store_true',
            help='Generate only weekly missions',
        )

    def handle(self, *args, **options):
        # Get current UTC time
        now_utc = timezone.now()
        self.stdout.write(f'\n🌍 Current UTC time: {now_utc.strftime("%Y-%m-%d %H:%M:%S %Z")}\n')

        # Get users to generate missions for
        if options['user_id']:
            users = User.objects.filter(id=options['user_id'])
            if not users.exists():
                self.stdout.write(self.style.ERROR(f'User with ID {options["user_id"]} not found'))
                return
        else:
            users = User.objects.filter(is_active=True)

        if not users.exists():
            self.stdout.write(self.style.ERROR('No active users found'))
            return

        daily_count = 0
        weekly_count = 0
        daily_skipped = 0
        weekly_skipped = 0

        # Determine what to generate
        generate_daily = not options['weekly_only']
        generate_weekly = not options['daily_only']

        for user in users:
            # ✅ Get user's current date in THEIR timezone
            user_today = get_user_current_date(user)
            user_tz = get_user_timezone(user)
            user_now = now_utc.astimezone(user_tz)

            self.stdout.write(
                f'\n👤 User: {user.username} (Timezone: {user.timezone})'
            )
            self.stdout.write(
                f'   Local time: {user_now.strftime("%Y-%m-%d %H:%M:%S %Z")}'
            )
            self.stdout.write(
                f'   Local date: {user_today}'
            )

            # ==================== DAILY MISSIONS ====================
            if generate_daily:
                # Check if user already has daily missions for today (in their timezone)
                existing_daily = UserMission.objects.filter(
                    user=user,
                    cycle_date=user_today,
                    mission__cycle='daily'
                )

                if existing_daily.exists() and not options['force']:
                    daily_skipped += existing_daily.count()
                    self.stdout.write(
                        self.style.WARNING(
                            f'   ⚠️  User {user.username} already has {existing_daily.count()} daily missions for {user_today}. Use --force to regenerate.'
                        )
                    )
                else:
                    # Delete existing if force is enabled
                    if options['force'] and existing_daily.exists():
                        deleted_count = existing_daily.count()
                        existing_daily.delete()
                        self.stdout.write(
                            self.style.WARNING(
                                f'   🗑️  Deleted {deleted_count} existing daily missions for {user.username}'
                            )
                        )

                    # ✅ Use MissionResetService for consistency
                    daily_missions = Mission.objects.filter(
                        cycle='daily',
                        is_active=True,
                        is_random_pool=True
                    )

                    if daily_missions.exists():
                        pool_size = daily_missions.first().pool_size
                        selected_missions = random.sample(
                            list(daily_missions),
                            min(pool_size, daily_missions.count())
                        )

                        for mission in selected_missions:
                            UserMission.objects.create(
                                mission=mission,
                                user=user,
                                cycle_date=user_today,  # ✅ Use user's timezone date
                                progress=0,
                                metadata={}
                            )
                            daily_count += 1

                        self.stdout.write(
                            self.style.SUCCESS(
                                f'   ✅ Created {len(selected_missions)} daily missions for {user.username} on {user_today}'
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING('   ⚠️  No active daily missions found in random pool')
                        )

            # ==================== WEEKLY MISSIONS ====================
            if generate_weekly:
                # ✅ Get Monday of this week in user's timezone
                monday = user_today - timedelta(days=user_today.weekday())

                # Check if user already has weekly missions for this week
                existing_weekly = UserMission.objects.filter(
                    user=user,
                    cycle_date=monday,
                    mission__cycle='weekly'
                )

                if existing_weekly.exists() and not options['force']:
                    weekly_skipped += existing_weekly.count()
                    self.stdout.write(
                        self.style.WARNING(
                            f'   ⚠️  User {user.username} already has {existing_weekly.count()} weekly missions for week of {monday}. Use --force to regenerate.'
                        )
                    )
                else:
                    # Delete existing if force is enabled
                    if options['force'] and existing_weekly.exists():
                        deleted_count = existing_weekly.count()
                        existing_weekly.delete()
                        self.stdout.write(
                            self.style.WARNING(
                                f'   🗑️  Deleted {deleted_count} existing weekly missions for {user.username}'
                            )
                        )

                    # Get all active weekly missions
                    weekly_missions = Mission.objects.filter(
                        cycle='weekly',
                        is_active=True
                    )

                    if weekly_missions.exists():
                        for mission in weekly_missions:
                            UserMission.objects.create(
                                mission=mission,
                                user=user,
                                cycle_date=monday,  # ✅ Use user's timezone Monday
                                progress=0,
                                metadata={}
                            )
                            weekly_count += 1

                        self.stdout.write(
                            self.style.SUCCESS(
                                f'   ✅ Created {weekly_missions.count()} weekly missions for {user.username} for week of {monday}'
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING('   ⚠️  No active weekly missions found')
                        )

        # ==================== SQUAD MISSIONS ====================
        from squads.models import Squad
        from gamification.services.squad_mission_services import SquadMissionService

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('GENERATING SQUAD MISSIONS')
        self.stdout.write('=' * 70)

        squads = Squad.objects.all()
        squad_missions_created = 0

        for squad in squads:
            # Get a sample member to determine their timezone
            sample_membership = squad.memberships.select_related('user').first()

            if not sample_membership:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  Squad {squad.name} has no members, skipping')
                )
                continue

            user_today = get_user_current_date(sample_membership.user)
            user_tz = get_user_timezone(sample_membership.user)

            self.stdout.write(f'\n🏆 Squad: {squad.name} ({squad.memberships.count()} members)')
            self.stdout.write(f'   Using timezone from member: {sample_membership.user.username} ({user_tz})')

            # Daily squad missions
            if generate_daily:
                SquadMissionService.ensure_squad_has_missions(
                    squad=squad,
                    cycle_date=user_today,
                    cycle_type='daily'
                )
                daily_created = SquadMissionProgress.objects.filter(
                    squad=squad,
                    cycle_date=user_today,
                    mission__cycle='daily'
                ).count()
                squad_missions_created += daily_created
                self.stdout.write(f'   ✅ Daily squad missions: {daily_created}')

            # Weekly squad missions
            if generate_weekly:
                monday = user_today - timedelta(days=user_today.weekday())
                SquadMissionService.ensure_squad_has_missions(
                    squad=squad,
                    cycle_date=monday,
                    cycle_type='weekly'
                )
                weekly_created = SquadMissionProgress.objects.filter(
                    squad=squad,
                    cycle_date=monday,
                    mission__cycle='weekly'
                ).count()
                squad_missions_created += weekly_created
                self.stdout.write(f'   ✅ Weekly squad missions: {weekly_created}')


        # Final summary
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('SUMMARY'))
        self.stdout.write('=' * 70)
        self.stdout.write(f'Users processed: {users.count()}')

        if generate_daily:
            self.stdout.write(f'Daily missions created: {daily_count}')
            if daily_skipped > 0:
                self.stdout.write(self.style.WARNING(f'Daily missions skipped: {daily_skipped}'))

        if generate_weekly:
            self.stdout.write(f'Weekly missions created: {weekly_count}')
            if weekly_skipped > 0:
                self.stdout.write(self.style.WARNING(f'Weekly missions skipped: {weekly_skipped}'))

        self.stdout.write('=' * 70)

        # ✅ Show next reset times for each user (or first user if multiple)
        if users.count() == 1:
            user = users.first()
            user_tz = get_user_timezone(user)

            if generate_daily:
                from ...utils import get_time_until_daily_reset
                seconds_until_reset = get_time_until_daily_reset(user)
                hours = seconds_until_reset // 3600
                minutes = (seconds_until_reset % 3600) // 60

                next_daily_reset_utc = now_utc + timedelta(seconds=seconds_until_reset)
                next_daily_reset_local = next_daily_reset_utc.astimezone(user_tz)

                self.stdout.write(
                    f'\n📅 Next daily reset for {user.username}:'
                )
                self.stdout.write(
                    f'   Local time ({user.timezone}): {next_daily_reset_local.strftime("%Y-%m-%d %H:%M:%S %Z")}'
                )
                self.stdout.write(
                    f'   UTC time: {next_daily_reset_utc.strftime("%Y-%m-%d %H:%M:%S %Z")}'
                )
                self.stdout.write(
                    f'   Time until reset: {hours}h {minutes}m'
                )

            if generate_weekly:
                from ...utils import get_time_until_weekly_reset
                seconds_until_reset = get_time_until_weekly_reset(user)
                days = seconds_until_reset // 86400
                hours = (seconds_until_reset % 86400) // 3600

                next_weekly_reset_utc = now_utc + timedelta(seconds=seconds_until_reset)
                next_weekly_reset_local = next_weekly_reset_utc.astimezone(user_tz)

                self.stdout.write(
                    f'\n📅 Next weekly reset for {user.username}:'
                )
                self.stdout.write(
                    f'   Local time ({user.timezone}): {next_weekly_reset_local.strftime("%Y-%m-%d %H:%M:%S %Z")}'
                )
                self.stdout.write(
                    f'   UTC time: {next_weekly_reset_utc.strftime("%Y-%m-%d %H:%M:%S %Z")}'
                )
                self.stdout.write(
                    f'   Time until reset: {days}d {hours}h'
                )
        else:
            self.stdout.write(
                f'\n💡 Tip: Run with --user-id to see detailed reset times for a specific user'
            )

        self.stdout.write('')  # Empty line at end