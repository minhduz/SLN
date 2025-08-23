from django.db import models
from django.conf import settings
import uuid

class RestrictedWord(models.Model):
    SEVERITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    word = models.CharField(max_length=255)
    severity = models.CharField(max_length=255, choices=SEVERITY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.word} ({self.severity})"

class ModerationQueue(models.Model):
    CONTENT_TYPE_CHOICES = [
        ("question", "Question"),
        ("answer", "Answer"),
    ]

    FLAGGED_BY_CHOICES = [
        ("ai", "AI"),
        ("human", "Human"),
        ("auto_filter", "Auto Filter"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_id = models.UUIDField()
    content_type=models.CharField(max_length=255,choices=CONTENT_TYPE_CHOICES)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submitted_moderation_items')
    flagged_by = models.CharField(max_length=20, choices=FLAGGED_BY_CHOICES)
    reason = models.TextField()
    original_content = models.TextField()
    status = models.CharField(max_length=255, choices=STATUS_CHOICES)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='reviewing_moderation_items', null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.content_type} flagged by {self.flagged_by} - {self.status}"


class Report(models.Model):
    CONTENT_TYPES = [
        ("question", "Question"),
        ("answer", "Answer"),
        ("user", "User"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("reviewed", "Reviewed"),
        ("dismissed", "Dismissed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reported')
    content_id = models.UUIDField()
    content_type=models.CharField(max_length=255,choices=CONTENT_TYPES)
    reason = models.TextField()
    status = models.CharField(max_length=255, choices=STATUS_CHOICES)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='reviewed_reports', null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Report on {self.content_type} ({self.status})"
