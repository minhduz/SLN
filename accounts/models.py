from django.contrib.auth.models import BaseUserManager, AbstractBaseUser, PermissionsMixin
from django.db import models
import uuid
import pytz

# Create your models here.
class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError('Users must have username')
        if not email:
            raise ValueError('Users must have email')
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=50, unique=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, unique=True, blank=True, null=True)
    password = models.CharField(max_length=255)
    full_name = models.CharField(max_length=255, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio = models.TextField(blank=True)
    dob = models.DateTimeField(blank=True, null=True)
    role = models.CharField(max_length=20, choices=[
        ("student", "Student"),
        ("pupil", "Pupil"),
        ("teacher", "Teacher")
    ])
    points = models.IntegerField(default=0)
    daily_ai_usage = models.IntegerField(default=0)

    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        choices=[(tz, tz) for tz in pytz.common_timezones],
        help_text="User's timezone for mission resets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    objects = UserManager()

    def __str__(self):
        return self.username

    # ✅ Helper method to get timezone object
    def get_timezone(self):
        """Get user's timezone as pytz timezone object"""
        try:
            return pytz.timezone(self.timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            return pytz.UTC



class UserVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verifications')
    method = models.CharField(max_length=20, choices=[
        ("otp","OTP"),
        ("student_id","Student ID"),
        ("personal_id","Personal ID"),
        ("face","Face"),
    ])
    document_url = models.URLField(blank=True, null=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='refresh_tokens')
    token_hash = models.CharField(max_length=255)
    device_info = models.CharField(max_length=255, blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
