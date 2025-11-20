from django.db import models
from django.conf import settings
import uuid

class Squad(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True,null=True)
    max_members = models.IntegerField(default=5)
    min_members = models.IntegerField(default=3)
    avatar = models.ImageField(upload_to='squad_avatars/', blank=True, null=True)
    create_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_squads')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class SquadMember(models.Model):
    ROLE_CHOICES = (
        ("leader", "Leader"),
        ("member", "Member"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    squad = models.ForeignKey(Squad, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='squads_members')
    role = models.CharField(max_length=255,choices=ROLE_CHOICES,default='member')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('squad', 'user'),)

    def __str__(self):
        return f"{self.user} in {self.squad} ({self.role})"