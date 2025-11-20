# gamification/serializers.py
from rest_framework import serializers
from .models import Mission, UserMission, MissionReward, SquadMissionProgress
from economy.models import Currency
from .utils import get_time_until_daily_reset, get_time_until_weekly_reset


class CurrencySerializer(serializers.ModelSerializer):
    """Serializer for Currency"""

    class Meta:
        model = Currency
        fields = ['id', 'name', 'description']


class MissionRewardSerializer(serializers.ModelSerializer):
    """Serializer for mission rewards"""
    currency = CurrencySerializer(read_only=True)

    class Meta:
        model = MissionReward
        fields = ['id', 'currency', 'amount']


class MissionSerializer(serializers.ModelSerializer):
    """Serializer for Mission template"""
    rewards = MissionRewardSerializer(many=True, read_only=True)
    cycle_display = serializers.CharField(source='get_cycle_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Mission
        fields = [
            'id', 'title', 'description', 'type', 'type_display',
            'cycle', 'cycle_display', 'target_count', 'rewards',
            'conditions', 'created_at'
        ]


class UserMissionSerializer(serializers.ModelSerializer):
    """Serializer for user's mission instance"""
    mission = MissionSerializer(read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    is_new = serializers.SerializerMethodField()
    time_remaining = serializers.SerializerMethodField()

    class Meta:
        model = UserMission
        fields = [
            'id', 'mission', 'progress', 'is_completed', 'completed_at',
            'progress_percentage', 'cycle_date', 'is_new', 'time_remaining',
            'created_at'
        ]

    def get_progress_percentage(self, obj):
        """Calculate progress percentage"""
        if obj.mission.target_count == 0:
            return 0
        percentage = (obj.progress / obj.mission.target_count) * 100
        return min(round(percentage, 1), 100)

    def get_is_new(self, obj):
        """Check if mission was assigned today in user's timezone"""
        from .utils import get_user_current_date
        user_today = get_user_current_date(obj.user)
        return obj.cycle_date == user_today

    def get_time_remaining(self, obj):
        """Calculate time remaining until next reset (2:00 AM in user's timezone)"""
        # ✅ Pass the user object to the utility functions
        if obj.mission.cycle == 'daily':
            return get_time_until_daily_reset(obj.user)
        elif obj.mission.cycle == 'weekly':
            return get_time_until_weekly_reset(obj.user)
        return None


class SquadMissionProgressSerializer(serializers.ModelSerializer):
    """Serializer for squad mission progress"""
    mission = MissionSerializer(read_only=True)
    completed_members_count = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    time_remaining = serializers.SerializerMethodField()
    member_progress = serializers.SerializerMethodField()

    class Meta:
        model = SquadMissionProgress
        fields = [
            'id', 'mission',
            'completed_members_count', 'progress_percentage',
            'is_completed', 'completed_at', 'rewards_distributed',
            'cycle_date', 'time_remaining', 'member_progress',
            'created_at'
        ]

    def get_completed_members_count(self, obj):
        """Get number of members who completed their individual missions"""
        completed_members = obj.completed_members
        if isinstance(completed_members, list):
            return len(completed_members)
        return 0

    def get_progress_percentage(self, obj):
        """Calculate squad mission progress percentage"""
        return round(obj.get_completion_percentage(), 1)

    def get_time_remaining(self, obj):
        """Calculate time remaining until next reset"""
        from .utils import get_time_until_daily_reset, get_time_until_weekly_reset

        # Get any member to determine timezone (they should all be in same timezone ideally)
        sample_membership = obj.squad.memberships.select_related('user').first()
        if not sample_membership:
            return None

        user = sample_membership.user

        if obj.mission.cycle == 'daily':
            return get_time_until_daily_reset(user)
        elif obj.mission.cycle == 'weekly':
            return get_time_until_weekly_reset(user)
        return None

    def get_member_progress(self, obj):
        """Get detailed member progress (who completed, who hasn't)"""
        completed_member_ids = set(obj.completed_members) if isinstance(obj.completed_members, list) else set()

        members = []
        for membership in obj.squad.memberships.select_related('user').all():
            user = membership.user
            members.append({
                'user_id': str(user.id),
                'username': user.username,
                'role': membership.role,
                'has_completed': str(user.id) in completed_member_ids
            })

        return members