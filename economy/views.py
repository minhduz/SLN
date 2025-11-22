# economy/views.py
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Currency, UserCurrency, Package, UserPackage
from .serializers import (
    UserCurrencySerializer,
    PackageListSerializer,
    PackageSerializer,
    UserPackageSerializer,
    BuyPackageSerializer,
    UpdatePackageStatusSerializer
)

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
            logger.error(f"❌ Error fetching user currencies: {str(e)}")
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
                f"✨ Initialized {len(currencies_to_create)} currencies for user {user.username}"
            )


class DiamondPackagesView(ListAPIView):
    """
    GET /api/economy/packages/diamonds/
    Get all available diamond packages (real money purchases)

    Example Response:
    {
        "success": true,
        "count": 5,
        "packages": [
            {
                "id": "uuid",
                "name": "20 Diamond Package",
                "currency_name": "Diamond",
                "amount": 20,
                "purchase_type": "real_money",
                "purchase_type_display": "Real Money (VND)",
                "purchase_currency_name": null,
                "price": 20000,
                "is_active": true
            },
            ...
        ]
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PackageListSerializer

    def get_queryset(self):
        """Get only active diamond packages"""
        return Package.objects.filter(
            is_active=True,
            purchase_type='real_money',
            currency__name='Diamond'
        ).select_related('currency', 'purchase_currency').order_by('price')

    def list(self, request, *args, **kwargs):
        """Override list to add custom response format"""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'success': True,
            'count': queryset.count(),
            'packages': serializer.data
        }, status=status.HTTP_200_OK)


class GoldPackagesView(ListAPIView):
    """
    GET /api/economy/packages/gold/
    Get all available gold packages (in-game currency purchases with Diamond)

    Example Response:
    {
        "success": true,
        "count": 6,
        "packages": [
            {
                "id": "uuid",
                "name": "1000 Gold Package",
                "currency_name": "Gold",
                "amount": 1000,
                "purchase_type": "currency",
                "purchase_type_display": "In-Game Currency",
                "purchase_currency_name": "Diamond",
                "price": 10,
                "is_active": true
            },
            ...
        ]
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PackageListSerializer

    def get_queryset(self):
        """Get only active gold packages"""
        return Package.objects.filter(
            is_active=True,
            purchase_type='currency',
            currency__name='Gold'
        ).select_related('currency', 'purchase_currency').order_by('price')

    def list(self, request, *args, **kwargs):
        """Override list to add custom response format"""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'success': True,
            'count': queryset.count(),
            'packages': serializer.data
        }, status=status.HTTP_200_OK)


class BuyPackageView(APIView):
    """
    POST /api/economy/packages/buy/
    Buy a package (diamond or gold)

    Request Body:
    {
        "package_id": "uuid"
    }

    Response (Gold Package - Auto Completed):
    {
        "success": true,
        "message": "Package purchased successfully",
        "status": "completed",
        "data": {
            "id": "uuid",
            "package_id": "uuid",
            "package_name": "1000 Gold Package",
            "amount": 1000,
            "currency_name": "Gold",
            "status": "completed",
            "status_display": "Completed"
        }
    }

    Response (Diamond Package - Pending Review):
    {
        "success": true,
        "message": "Purchase request created. Waiting for admin approval.",
        "status": "pending",
        "data": {
            "id": "uuid",
            "package_id": "uuid",
            "package_name": "100 Diamond Package",
            "amount": 100,
            "currency_name": "Diamond",
            "status": "pending",
            "status_display": "Pending Review"
        }
    }

    Error Response:
    {
        "success": false,
        "error": "Insufficient Diamond. You have 5 but need 10."
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Handle package purchase"""
        serializer = BuyPackageSerializer(
            data=request.data,
            context={'request': request}
        )

        if not serializer.is_valid():
            logger.warning(
                f"❌ Purchase validation failed for user {request.user.username}: {serializer.errors}"
            )
            return Response(
                {
                    'success': False,
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_package = serializer.save()
            package = user_package.package

            # Prepare response based on status
            response_serializer = UserPackageSerializer(user_package)

            if user_package.status == 'completed':
                message = "✅ Package purchased successfully and currency added to your account!"
            else:
                message = "🔔 Purchase request created. Waiting for admin approval."

            return Response(
                {
                    'success': True,
                    'message': message,
                    'status': user_package.status,
                    'data': response_serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"❌ Error processing purchase: {str(e)}")
            return Response(
                {
                    'success': False,
                    'error': 'Failed to process purchase'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserPackagesView(ListAPIView):
    """
    GET /api/economy/user-packages/
    Get all packages purchased by the current user (with filtering options)

    Query Parameters:
    - status: Filter by status (pending, completed, done, failed)
    - purchase_type: Filter by purchase type (currency, real_money)
    - ordering: Order by field (-created_at, created_at, status, etc.)

    Example Response:
    {
        "success": true,
        "count": 5,
        "results": [
            {
                "id": "uuid",
                "package_id": "uuid",
                "package_name": "1000 Gold Package",
                "amount": 1000,
                "currency_name": "Gold",
                "status": "completed",
                "status_display": "Completed",
                "is_active": true,
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:00:00Z"
            },
            ...
        ]
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserPackageSerializer

    def get_queryset(self):
        """Get user's packages with filtering"""
        queryset = UserPackage.objects.filter(
            user=self.request.user
        ).select_related('package__currency', 'package__purchase_currency').order_by('-created_at')

        # Filter by status
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by purchase type
        purchase_type = self.request.query_params.get('purchase_type', None)
        if purchase_type:
            queryset = queryset.filter(package__purchase_type=purchase_type)

        return queryset

    def list(self, request, *args, **kwargs):
        """Override list to add custom response format"""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'success': True,
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)


class AdminUpdatePackageStatusView(RetrieveUpdateAPIView):
    """
    GET /api/economy/admin/packages/{id}/
    PATCH /api/economy/admin/packages/{id}/

    Admin-only endpoint to review and update pending package purchases

    Request Body (PATCH):
    {
        "status": "done",
        "admin_notes": "Payment verified"
    }

    Response:
    {
        "success": true,
        "message": "Purchase approved. Currency added to user.",
        "data": {
            "id": "uuid",
            "status": "done",
            "status_display": "Done",
            "admin_notes": "Payment verified",
            "updated_at": "2025-01-15T11:00:00Z"
        }
    }
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = UserPackage.objects.all()
    serializer_class = UpdatePackageStatusSerializer

    def retrieve(self, request, *args, **kwargs):
        """Get package details"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                'success': True,
                'data': serializer.data
            },
            status=status.HTTP_200_OK
        )

    def update(self, request, *args, **kwargs):
        """Update package status and handle currency"""
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if not serializer.is_valid():
            logger.warning(f"❌ Status update validation failed: {serializer.errors}")
            return Response(
                {
                    'success': False,
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            updated_instance = serializer.save()

            # Determine message based on status
            if updated_instance.status == 'done':
                message = f"✅ Purchase approved. {updated_instance.package.amount} {updated_instance.package.currency.name} added to user."
            elif updated_instance.status == 'failed':
                message = "❌ Purchase rejected."
            else:
                message = f"Updated status to {updated_instance.get_status_display()}"

            return Response(
                {
                    'success': True,
                    'message': message,
                    'data': UpdatePackageStatusSerializer(updated_instance).data
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"❌ Error updating package status: {str(e)}")
            return Response(
                {
                    'success': False,
                    'error': 'Failed to update package status'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminPendingPackagesView(ListAPIView):
    """
    GET /api/economy/admin/packages/pending/
    Admin-only endpoint to view all pending real money purchases

    Example Response:
    {
        "success": true,
        "count": 3,
        "results": [
            {
                "id": "uuid",
                "package_id": "uuid",
                "package_name": "100 Diamond Package",
                "amount": 100,
                "currency_name": "Diamond",
                "status": "pending",
                "status_display": "Pending Review",
                "admin_notes": null,
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:00:00Z"
            },
            ...
        ]
    }
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = UserPackageSerializer

    def get_queryset(self):
        """Get only pending real money purchases"""
        return UserPackage.objects.filter(
            status='pending',
            package__purchase_type='real_money'
        ).select_related('user', 'package__currency', 'package__purchase_currency').order_by('-created_at')

    def list(self, request, *args, **kwargs):
        """Override list to add custom response format"""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'success': True,
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)