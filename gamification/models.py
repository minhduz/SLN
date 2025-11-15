# gamification/models.py
from django.db import models
from django.conf import settings
import uuid
from economy.models import Currency
from squads.models import Squad


class Mission(models.Model):
    """
    Mission template that defines the mission requirements.
    This is created by admins and used to generate user missions.
    """
    TYPE_CHOICES = (
        ('complete_quiz', 'Complete Quiz'),
        ('save_question', 'Save Question'),
        ('answer_question', 'Answer Question'),
        ('rate_quiz', 'Rate Quiz'),
        ('verify_answer', 'Verify Answer'),
        ('view_question', 'View Question'),
        ('get_verified', 'Get Verified'),
        ('create_quiz', 'Create Quiz'),
        ('other', 'Other'),
    )

    CYCLE_CHOICES = (
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('permanent', 'Permanent'),
    )

    ACCESS_TYPE_CHOICES = (
        ('individual', 'Individual'),
        ('squad', 'Squad'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(null=True, blank=True)
    type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='other')
    cycle = models.CharField(
        max_length=20,
        choices=CYCLE_CHOICES,
        default='daily',
        help_text="Mission reset cycle: Daily (2 AM), Weekly (2 AM Monday), or Permanent"
    )
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPE_CHOICES, default='individual')
    target_count = models.IntegerField(
        default=1,
        help_text="Number of times the action must be completed"
    )

    # Condition fields for dynamic validation
    conditions = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON conditions: {'min_score': 80, 'exclude_own_questions': true, 'min_rating': 4}"
    )

    # Mission pool settings
    is_active = models.BooleanField(default=True)
    is_random_pool = models.BooleanField(
        default=False,
        help_text="If true, this mission is part of a random selection pool"
    )
    pool_size = models.IntegerField(
        default=3,
        help_text="Number of missions to randomly assign from pool (only for daily missions)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['cycle', 'type']

    def __str__(self):
        return f"[{self.get_cycle_display()}] {self.title}"

    def get_conditions(self):
        """Parse and return conditions as dict"""
        if isinstance(self.conditions, str):
            try:
                import json
                return json.loads(self.conditions)
            except:
                return {}
        return self.conditions or {}


class UserMission(models.Model):
    """
    Instance of a mission assigned to a specific user.
    This is auto-generated based on Mission templates and resets daily/weekly.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name='user_instances')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='missions')
    squad = models.ForeignKey(Squad, on_delete=models.CASCADE, related_name='missions', null=True, blank=True)

    progress = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Track metadata for complex validations
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Store tracking data: completed_quiz_ids, verifier_ids, etc."
    )

    # Cycle tracking
    cycle_date = models.DateField(
        help_text="The date/week this mission instance is for"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('mission', 'user', 'cycle_date'),)
        ordering = ['-cycle_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'cycle_date', 'is_completed']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.mission.title} ({self.cycle_date})"

    def get_metadata(self):
        """Parse and return metadata as dict"""
        if isinstance(self.metadata, str):
            try:
                import json
                return json.loads(self.metadata)
            except:
                return {}
        return self.metadata or {}


class MissionReward(models.Model):
    """
    Rewards attached to missions
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name='rewards')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='mission_reward_currencies')
    amount = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.amount} {self.currency.name} for {self.mission.title}"


class Reward(models.Model):
    """
    Rewards that users can redeem with their currency
    """
    TYPE_CHOICES = (
        ('premium_access', 'Premium Access'),
        ('gift_card', 'Gift Card'),
        ('tutoring', 'Tutoring'),
        ('other', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='reward_currencies')
    amount_required = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class RewardRedemption(models.Model):
    """
    Track reward redemptions
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reward = models.ForeignKey(Reward, on_delete=models.CASCADE, related_name='redemptions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='redeemed_rewards')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} redeemed {self.reward.name}"