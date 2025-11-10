from django.db import models
from django.conf import settings
import uuid

from qa.models import Subject


class Quiz(models.Model):
    QUIZ_TYPE_CHOICES = [
        ('human', 'Human Created'),
        ('ai', 'AI Generated'),
    ]

    LANGUAGE_CHOICES = [
        ('English', 'English'),
        ('Simplified Chinese', 'Simplified Chinese'),
        ('Traditional Chinese', 'Traditional Chinese'),
        ('Japanese', 'Japanese'),
        ('Korean', 'Korean'),
        ('Indonesian', 'Indonesian'),
        ('Thai', 'Thai'),
        ('Vietnamese', 'Vietnamese'),
        ('German', 'German'),
        ('French', 'French'),
        ('Spanish', 'Spanish'),
        ('Portuguese', 'Portuguese'),
        ('Russian', 'Russian'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='quizzes')
    quiz_type = models.CharField(max_length=10, choices=QUIZ_TYPE_CHOICES, default='human')
    language = models.CharField(max_length=50, choices=LANGUAGE_CHOICES, default='English')

    # Average rating calculated from all attempts
    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00,
        help_text="Average rating from all user attempts (0.00-5.00)"
    )

    # Total number of ratings (for calculating average)
    rating_count = models.IntegerField(
        default=0,
        help_text="Total number of ratings received"
    )

    # NEW: Track who created this quiz
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_quizzes',
        null=True,  # Set to null for existing records during migration
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['rating', '-created_at']),
            models.Index(fields=['subject', 'rating']),
        ]

    def __str__(self):
        return self.title

    def get_attempt_count(self, user):
        """Get the number of attempts a user has made on this quiz"""
        return self.attempts.filter(user=user).count()

    def can_user_attempt(self, user, max_attempts=3):
        """Check if user can attempt this quiz (max 3 attempts)"""
        return self.get_attempt_count(user) < max_attempts

    def get_user_remaining_attempts(self, user, max_attempts=3):
        """Get remaining attempts for a user"""
        current_attempts = self.get_attempt_count(user)
        return max(0, max_attempts - current_attempts)


class QuizQuestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Question: {self.question_text}"


class QuizAnswerOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='answer_options')
    option_text = models.TextField()
    is_correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']  # Maintains consistent order

    def __str__(self):
        return f"{self.option_text} - {'Correct' if self.is_correct else 'Incorrect'}"


class QuizAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='quiz_attempts')
    score = models.IntegerField(default=0)
    duration_seconds = models.IntegerField(null=True, blank=True, help_text="Duration in seconds")

    # Rating field: User can rate the quiz from 0-5 after each attempt
    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="User rating for this quiz attempt (0-5)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Track attempt count per user per quiz
        indexes = [
            models.Index(fields=['user', 'quiz', 'created_at']),
            models.Index(fields=['quiz', 'rating']),
        ]
        # Ensure we can efficiently query attempts per user per quiz
        ordering = ['-created_at']

    def get_attempt_number(self):
        """Get the attempt number for this user on this quiz"""
        return QuizAttempt.objects.filter(
            user=self.user,
            quiz=self.quiz,
            created_at__lte=self.created_at
        ).count()

    def can_rate(self):
        """Check if this attempt can be rated (rating is None)"""
        return self.rating is None

    def can_user_attempt_again(self, max_attempts=3):
        """Check if user can attempt this quiz again"""
        total_attempts = QuizAttempt.objects.filter(
            user=self.user,
            quiz=self.quiz
        ).count()
        return total_attempts < max_attempts


class QuizAttemptAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(QuizAnswerOption, on_delete=models.SET_NULL, null=True)
    is_correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attempt {self.attempt.id} - Question {self.question.question_text}"


class LearningHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='learning_history')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='learning_subject')
    topic = models.CharField(max_length=255)
    weakness_score = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class LearningPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='learning_plans')
    content = models.TextField(blank=True, null=True)
    strengths = models.JSONField(blank=True, null=True)
    weakness = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)