# economy/services.py
from django.core.exceptions import ValidationError
from ..models import UserCurrency, Currency
import logging

logger = logging.getLogger(__name__)


class PricingService:
    """Service to handle currency checks and deductions"""

    @staticmethod
    def has_sufficient_currency(user, currency_name: str, amount: int) -> bool:
        """
        Check if user has enough currency balance

        Args:
            user: The user object
            currency_name: "diamond" or "gold"
            amount: Amount required

        Returns:
            bool: True if user has sufficient balance
        """
        try:
            currency = Currency.objects.get(name__iexact=currency_name)
            user_currency = UserCurrency.objects.get(user=user, currency=currency)
            return user_currency.balance >= amount
        except (Currency.DoesNotExist, UserCurrency.DoesNotExist):
            return False

    @staticmethod
    def deduct_currency(user, currency_name: str, amount: int) -> dict:
        """
        Deduct currency from user balance

        Args:
            user: The user object
            currency_name: "diamond" or "gold"
            amount: Amount to deduct

        Returns:
            dict: {"success": bool, "message": str, "remaining_balance": int}
        """
        try:
            currency = Currency.objects.get(name__iexact=currency_name)
            user_currency = UserCurrency.objects.get(user=user, currency=currency)

            if user_currency.balance < amount:
                return {
                    "success": False,
                    "message": f"Insufficient {currency_name}. Required: {amount}, Available: {user_currency.balance}",
                    "remaining_balance": user_currency.balance
                }

            user_currency.balance -= amount
            user_currency.save()

            logger.info(f"Deducted {amount} {currency_name} from user {user.id}")

            return {
                "success": True,
                "message": f"Successfully deducted {amount} {currency_name}",
                "remaining_balance": user_currency.balance
            }

        except (Currency.DoesNotExist, UserCurrency.DoesNotExist) as e:
            logger.error(f"Currency or UserCurrency not found: {str(e)}")
            return {
                "success": False,
                "message": f"Currency '{currency_name}' not found",
                "remaining_balance": 0
            }

    @staticmethod
    def add_currency(user, currency_name: str, amount: int) -> dict:
        """
        Add currency to user balance

        Args:
            user: The user object
            currency_name: "diamond" or "gold"
            amount: Amount to add

        Returns:
            dict: {"success": bool, "message": str, "new_balance": int}
        """
        try:
            currency = Currency.objects.get(name__iexact=currency_name)
            user_currency, created = UserCurrency.objects.get_or_create(
                user=user,
                currency=currency,
                defaults={"balance": 0}
            )

            user_currency.balance += amount
            user_currency.save()

            logger.info(f"Added {amount} {currency_name} to user {user.id}")

            return {
                "success": True,
                "message": f"Successfully added {amount} {currency_name}",
                "new_balance": user_currency.balance
            }

        except Currency.DoesNotExist:
            return {
                "success": False,
                "message": f"Currency '{currency_name}' not found",
                "new_balance": 0
            }

    @staticmethod
    def get_user_balance(user, currency_name: str) -> int:
        """
        Get current user currency balance

        Args:
            user: The user object
            currency_name: "diamond" or "gold"

        Returns:
            int: Current balance (0 if not found)
        """
        try:
            currency = Currency.objects.get(name__iexact=currency_name)
            user_currency = UserCurrency.objects.get(user=user, currency=currency)
            return user_currency.balance
        except (Currency.DoesNotExist, UserCurrency.DoesNotExist):
            return 0