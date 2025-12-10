from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User
from economy.models import Currency, UserCurrency


@receiver(post_save, sender=User)
def allocate_initial_currency_on_user_create(sender, instance, created, **kwargs):
    '''
    Signal handler to allocate initial currency when a new user is created.
    '''
    if created:  # Only on creation, not on update
        try:
            # Get or create currencies
            diamond_currency, _ = Currency.objects.get_or_create(
                name="Diamond",
                defaults={"description": "Premium currency for special rewards"}
            )

            gold_currency, _ = Currency.objects.get_or_create(
                name="Gold",
                defaults={"description": "Primary currency for completing missions"}
            )

            # Allocate 100 Diamonds
            UserCurrency.objects.create(
                user=instance,
                currency=diamond_currency,
                balance=100
            )

            # Allocate 10,000 Gold
            UserCurrency.objects.create(
                user=instance,
                currency=gold_currency,
                balance=10000
            )

            print(f"✅ Initial currency allocated to user: {instance.username}")

        except Exception as e:
            print(f"❌ Error allocating initial currency: {str(e)}")