# gamification/management/commands/setup_missions.py
from django.core.management.base import BaseCommand
from gamification.models import Mission, MissionReward
from economy.models import Currency


class Command(BaseCommand):
    help = 'Setup initial missions and currencies'

    def handle(self, *args, **options):
        # Create currencies
        gold, _ = Currency.objects.get_or_create(
            name='Gold',
            defaults={
                'description': 'Primary currency for completing missions'
            }
        )

        diamond, _ = Currency.objects.get_or_create(
            name='Diamond',
            defaults={
                'description': 'Premium currency for special rewards'
            }
        )

        self.stdout.write(self.style.SUCCESS('✓ Created currencies'))

        # Create daily missions (random pool)
        daily_missions = [
            {
                'title': 'Quiz Master',
                'description': 'Complete 3 quizzes with at least 80% score',
                'type': 'complete_quiz',
                'target_count': 3,
                'conditions': {'min_score': 80},
            },
            {
                'title': 'Bookmark Collector',
                'description': 'Save 1 question to your collection',
                'type': 'save_question',
                'target_count': 1,
                'conditions': {},
            },
            {
                'title': 'Community Helper',
                'description': 'Answer 1 question from the community',
                'type': 'answer_question',
                'target_count': 1,
                'conditions': {'exclude_own_questions': True, 'only_public_questions': True},
            },
            {
                'title': 'Quiz Reviewer',
                'description': 'Rate 1 quiz',
                'type': 'rate_quiz',
                'target_count': 1,
                'conditions': {},
            },
            {
                'title': 'Quality Checker',
                'description': 'Verify 1 answer as correct',
                'type': 'verify_answer',
                'target_count': 1,
                'conditions': {},
            },
            {
                'title': 'Knowledge Seeker',
                'description': 'View 10 different questions',
                'type': 'view_question',
                'target_count': 10,
                'conditions': {},
            },
        ]

        for mission_data in daily_missions:
            mission, created = Mission.objects.get_or_create(
                title=mission_data['title'],
                defaults={
                    'description': mission_data['description'],
                    'type': mission_data['type'],
                    'cycle': 'daily',
                    'target_count': mission_data['target_count'],
                    'conditions': mission_data['conditions'],
                    'is_active': True,
                    'is_random_pool': True,
                    'pool_size': 3,
                }
            )

            if created:
                # Add rewards
                MissionReward.objects.create(mission=mission, currency=gold, amount=1000)
                MissionReward.objects.create(mission=mission, currency=diamond, amount=10)
                self.stdout.write(self.style.SUCCESS(f'✓ Created daily mission: {mission.title}'))

        # Create weekly missions
        weekly_missions = [
            {
                'title': 'Weekly Quiz Champion',
                'description': 'Complete 20 quizzes with at least 80% score',
                'type': 'complete_quiz',
                'target_count': 20,
                'conditions': {'min_score': 80},
            },
            {
                'title': 'Weekly Curator',
                'description': 'Save 15 questions to your collection',
                'type': 'save_question',
                'target_count': 15,
                'conditions': {},
            },
            {
                'title': 'Expert Recognition',
                'description': 'Get your answers verified 2 times by others',
                'type': 'get_verified',
                'target_count': 2,
                'conditions': {'unique_verifiers': True},
            },
            {
                'title': 'Quiz Creator Pro',
                'description': 'Create 3 quizzes that receive 4+ star ratings',
                'type': 'create_quiz',
                'target_count': 3,
                'conditions': {'min_rating': 4.0},
            },
        ]

        for mission_data in weekly_missions:
            mission, created = Mission.objects.get_or_create(
                title=mission_data['title'],
                defaults={
                    'description': mission_data['description'],
                    'type': mission_data['type'],
                    'cycle': 'weekly',
                    'target_count': mission_data['target_count'],
                    'conditions': mission_data['conditions'],
                    'is_active': True,
                    'is_random_pool': False,
                }
            )

            if created:
                # Add rewards
                MissionReward.objects.create(mission=mission, currency=gold, amount=5000)
                MissionReward.objects.create(mission=mission, currency=diamond, amount=25)
                self.stdout.write(self.style.SUCCESS(f'✓ Created weekly mission: {mission.title}'))

        # Create squad missions (require all members to complete)
        squad_missions = [
            {
                'title': 'Squad Daily Challenge',
                'description': 'All squad members complete their daily missions',
                'type': 'other',
                'cycle': 'daily',
                'target_count': 1,
                'conditions': {},
                'access_type': 'squad',
                'require_all_members': True,
            },
            {
                'title': 'Squad Weekly Goal',
                'description': 'All squad members complete their weekly missions',
                'type': 'other',
                'cycle': 'weekly',
                'target_count': 1,
                'conditions': {},
                'access_type': 'squad',
                'require_all_members': True,
            },
        ]

        squad_mission_rewards = [
            {
                'title': 'Squad Daily Challenge',
                'rewards': [
                    {'currency': gold, 'amount': 3000},
                    {'currency': diamond, 'amount': 25},
                ]
            },
            {
                'title': 'Squad Weekly Goal',
                'rewards': [
                    {'currency': gold, 'amount': 10000},
                    {'currency': diamond, 'amount': 75},
                ]
            },
        ]

        for mission_data in squad_missions:
            mission, created = Mission.objects.get_or_create(
                title=mission_data['title'],
                defaults={
                    'description': mission_data['description'],
                    'type': mission_data['type'],
                    'cycle': mission_data['cycle'],
                    'target_count': mission_data['target_count'],
                    'conditions': mission_data['conditions'],
                    'access_type': mission_data['access_type'],
                    'require_all_members': mission_data['require_all_members'],
                    'is_active': True,
                }
            )

            if created:
                # Add rewards
                reward_config = next(
                    (r for r in squad_mission_rewards if r['title'] == mission_data['title']),
                    None
                )

                if reward_config:
                    for reward in reward_config['rewards']:
                        MissionReward.objects.create(
                            mission=mission,
                            currency=reward['currency'],
                            amount=reward['amount']
                        )

                self.stdout.write(self.style.SUCCESS(f'✓ Created squad mission: {mission.title}'))

        self.stdout.write(self.style.SUCCESS('\n✅ All missions created successfully!'))