# economy/models.py
from django.conf import settings
from django.db import models
import uuid


class Currency(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Add this method to display name instead of UUID
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Currencies"


class UserCurrency(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='currencies')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='user_balances')
    balance = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        user_str = getattr(self.user, 'username', str(self.user))
        return f"{user_str} - {self.currency.name}: {self.balance}"

    class Meta:
        verbose_name_plural = "User Currencies"
        unique_together = ('user', 'currency')


class Package(models.Model):
    PURCHASE_TYPE_CHOICES = [
        ('real_money', 'Real Money (VND)'),
        ('currency', 'In-Game Currency'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='packages',null=True, help_text="Currency provided by this package (e.g., Diamond, Gold)")
    purchase_type = models.CharField(max_length=20, choices=PURCHASE_TYPE_CHOICES, help_text="How this package is purchased",null=True)
    purchase_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='purchasable_packages', null=True, blank=True, help_text="Currency needed to purchase (e.g., VND for real money, Diamond for gold packages)")
    amount = models.IntegerField(help_text="Amount of currency provided by this package",default=0)
    price = models.IntegerField(help_text="Cost to purchase this package")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.amount} {self.currency.name})"

    class Meta:
        verbose_name_plural = "Packages"


class UserPackage(models.Model):
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('pending', 'Pending Review'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions')
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='user_subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_active = models.BooleanField(default=True)
    admin_notes = models.TextField(blank=True, null=True, help_text="Notes from admin review")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        user_str = getattr(self.user, 'username', str(self.user))
        return f"{user_str} - {self.package.name} ({self.get_status_display()})"

    class Meta:
        verbose_name_plural = "User Packages"
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]