# economy/signals.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.db import transaction
from .models import UserPackage, UserCurrency
import logging

logger = logging.getLogger(__name__)

# Store original values before save
_original_values = {}

@receiver(pre_save, sender=UserPackage)
def track_original_status(sender, instance, **kwargs):
    """
    Track the original status BEFORE the save happens
    This runs before the database update
    """
    try:
        # Only if this is an existing object (not new)
        if instance.pk:
            original = UserPackage.objects.get(pk=instance.pk)
            _original_values[instance.pk] = original.status
            logger.info(f"📌 Tracking original status for {instance.pk}: {original.status}")
    except UserPackage.DoesNotExist:
        pass

@receiver(post_save, sender=UserPackage)
def handle_package_purchase_completion(sender, instance, created, **kwargs):
    """
    Signal handler to:
    1. Auto-complete in-game currency purchases
    2. Add currency to user balance when purchase is approved (status='done')
    3. Refund currency when purchase fails (status='failed')
    """

    if created:

        # New purchase created - auto-complete if it's an in-game currency purchase
        if instance.package.purchase_type == 'currency':

            instance.status = 'completed'
            instance.save(update_fields=['status'])

            # Add the currency to user balance
            _add_currency_to_user(
                instance.user,
                instance.package.currency,
                instance.package.amount,
                reason="Auto-completed in-game purchase"
            )
        else:
            logger.info(f"💰 Real money purchase detected (Diamond) - waiting for admin approval")
    else:

        # Get the ORIGINAL status from our tracking dictionary
        original_status = _original_values.get(instance.pk)

        # If status changed to 'done', add currency to user
        if instance.status == 'done' and original_status != 'done':
            _add_currency_to_user(
                instance.user,
                instance.package.currency,
                instance.package.amount,
                reason="Admin approved real money purchase"
            )

        # If status changed to 'failed', refund purchase currency
        elif instance.status == 'failed' and original_status not in ['failed', 'done']:

            if instance.package.purchase_type == 'currency':
                # Refund the purchase currency for in-game purchases
                _add_currency_to_user(
                    instance.user,
                    instance.package.purchase_currency,
                    instance.package.price,
                    reason="Refund for rejected in-game purchase"
                )
            else:
                # Real money refunds handled manually through payment gateway
                logger.info(f"   Real money purchase - refund handled through payment gateway")

        else:
            logger.info(f"ℹ️  No status change detected (was: {original_status}, now: {instance.status}) - no action needed")

        # Clean up the tracking dictionary
        if instance.pk in _original_values:
            del _original_values[instance.pk]

@transaction.atomic
def _add_currency_to_user(user, currency, amount, reason=""):
    """Helper function to add currency to user balance"""
    try:
        user_currency, created = UserCurrency.objects.get_or_create(
            user=user,
            currency=currency,
            defaults={'balance': 0}
        )

        old_balance = user_currency.balance

        user_currency.balance += amount

        user_currency.save(update_fields=['balance', 'updated_at'])

        return user_currency

    except Exception as e:
        logger.error(f"   Exception type: {type(e).__name__}")
        raise

# Apps configuration to register signals
def ready():
    """Called when app is ready - signals are imported here"""
    logger.info("✨ Economy signals loaded and registered")