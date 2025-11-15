# economy/views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction

from .models import Currency, UserCurrency
from .serializers import UserCurrencySerializer

import logging

logger = logging.getLogger(__name__)


class UserCurrenciesView(APIView):
    """
    GET /api/economy/currencies/
    Get all currency balances for the current user

    Automatically initializes all currencies with 0 balance if user doesn't have them yet.

    Example Response:
    {
        "success": true,
        "count": 2,
        "currencies": [
            {
                "id": "uuid",
                "currency": {
                    "id": "uuid",
                    "name": "Gold",
                    "description": "Primary currency for completing missions",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z"
                },
                "currency_id": "uuid",
                "currency_name": "Gold",
                "balance": 1500,
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T12:00:00Z"
            },
            {
                "id": "uuid",
                "currency": {
                    "id": "uuid",
                    "name": "Diamond",
                    "description": "Premium currency for special rewards",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z"
                },
                "currency_id": "uuid",
                "currency_name": "Diamond",
                "balance": 25,
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T11:00:00Z"
            }
        ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get user's currency balances, initialize if needed"""
        try:
            user = request.user

            # Initialize user currencies if they don't exist
            self._initialize_user_currencies(user)

            # Get all user currencies
            user_currencies = UserCurrency.objects.filter(
                user=user
            ).select_related('currency').order_by('currency__name')

            serializer = UserCurrencySerializer(user_currencies, many=True)

            return Response({
                'success': True,
                'count': user_currencies.count(),
                'currencies': serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching user currencies: {str(e)}")
            return Response(
                {'success': False, 'error': 'Failed to fetch currencies'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @transaction.atomic
    def _initialize_user_currencies(self, user):
        """
        Initialize all currencies for user with 0 balance if they don't exist.
        This ensures every user has entries for all available currencies.
        """
        # Get all available currencies
        all_currencies = Currency.objects.all()

        # Get currencies user already has
        existing_currency_ids = UserCurrency.objects.filter(
            user=user
        ).values_list('currency_id', flat=True)

        # Create missing currencies with 0 balance
        currencies_to_create = []
        for currency in all_currencies:
            if currency.id not in existing_currency_ids:
                currencies_to_create.append(
                    UserCurrency(
                        user=user,
                        currency=currency,
                        balance=0
                    )
                )

        # Bulk create missing currencies
        if currencies_to_create:
            UserCurrency.objects.bulk_create(currencies_to_create)
            logger.info(
                f"Initialized {len(currencies_to_create)} currencies for user {user.username}"
            )