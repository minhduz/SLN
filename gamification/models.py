from django.db import models
from django.conf import settings
import uuid

from economy.models import Currency
from squads.models import Squad


class Mission(models.Model):
    TYPE_CHOICES = (
        ('login','Login'),
        ('ask_question','Ask Question'),
        ('answer_question','Answer Question'),
        ('get_an_approval','Get And Approval'),
        ('quizzes','Quizzes'),
        ('other','Other'),
    )

    ACCESS_TYPE_CHOICES = (
        ('individual','Individual'),
        ('squad','Squad'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPE_CHOICES, default='individual')
    target_count = models.IntegerField(default=0)
    deadline = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class MissionParticipation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='missions', null=True, blank=True)
    squad = models.ForeignKey(Squad, on_delete=models.CASCADE, related_name='missions', null=True, blank=True)
    progress = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('mission', 'user'),)

class MissionRewards(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name='rewards')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='mission_reward_currencies')
    amount = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.amount} {self.currency} for {self.mission}"

class Reward(models.Model):
    TYPE_CHOICES = (
        ('premium_access','Premium Access'),
        ('gift_card','Gift Card'),
        ('tutoring','Tutoring'),
        ('other','Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='reward_currencies')
    amount_required = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class RewardRedemption(models.Model):
    STATUS_CHOICES = (
        ('pending','Pending'),
        ('approved','Approved'),
        ('rejected','Rejected'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reward = models.ForeignKey(Reward, on_delete=models.CASCADE, related_name='redemptions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='redeemed_rewards')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} redeemed {self.reward}"
