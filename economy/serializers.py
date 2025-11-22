# economy/serializers.py
from rest_framework import serializers
from django.db import transaction
from .models import Currency, Package, UserPackage, UserCurrency

import logging

logger = logging.getLogger(__name__)


class CurrencySerializer(serializers.ModelSerializer):
    """Serializer for Currency model"""
    class Meta:
        model = Currency
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class UserCurrencySerializer(serializers.ModelSerializer):
    """Serializer for UserCurrency with nested currency info"""
    currency = CurrencySerializer(read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)
    currency_id = serializers.CharField(source='currency.id', read_only=True)

    class Meta:
        model = UserCurrency
        fields = ['id', 'currency', 'currency_id', 'currency_name', 'balance', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class PackageSerializer(serializers.ModelSerializer):
    """Serializer for Package model with currency details"""
    currency = CurrencySerializer(read_only=True)
    currency_id = serializers.CharField(source='currency.id', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)
    purchase_currency = CurrencySerializer(read_only=True)
    purchase_currency_id = serializers.CharField(source='purchase_currency.id', read_only=True, allow_null=True)
    purchase_currency_name = serializers.CharField(source='purchase_currency.name', read_only=True, allow_null=True)
    purchase_type_display = serializers.CharField(source='get_purchase_type_display', read_only=True)

    class Meta:
        model = Package
        fields = [
            'id', 'name', 'description', 'currency', 'currency_id', 'currency_name',
            'purchase_type', 'purchase_type_display', 'purchase_currency', 'purchase_currency_id',
            'purchase_currency_name', 'amount', 'price', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PackageListSerializer(serializers.ModelSerializer):
    """Simplified serializer for package list view"""
    currency_name = serializers.CharField(source='currency.name', read_only=True)
    purchase_currency_name = serializers.CharField(source='purchase_currency.name', read_only=True, allow_null=True)
    purchase_type_display = serializers.CharField(source='get_purchase_type_display', read_only=True)

    class Meta:
        model = Package
        fields = [
            'id', 'name', 'currency_name', 'amount', 'purchase_type',
            'purchase_type_display', 'purchase_currency_name', 'price', 'is_active'
        ]
        read_only_fields = ['id']


class UserPackageSerializer(serializers.ModelSerializer):
    """Serializer for UserPackage with nested package info"""
    package = PackageSerializer(read_only=True)
    package_id = serializers.CharField(source='package.id', read_only=True)
    package_name = serializers.CharField(source='package.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    currency_name = serializers.CharField(source='package.currency.name', read_only=True)
    amount = serializers.IntegerField(source='package.amount', read_only=True)

    class Meta:
        model = UserPackage
        fields = [
            'id', 'package', 'package_id', 'package_name', 'amount', 'currency_name',
            'status', 'status_display', 'is_active', 'admin_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'package', 'package_id', 'package_name', 'amount', 'currency_name',
                           'created_at', 'updated_at']


class BuyPackageSerializer(serializers.Serializer):
    """
    Serializer for buying a package
    Handles validation and business logic for package purchases
    """
    package_id = serializers.UUIDField(required=True)

    def validate_package_id(self, value):
        """Validate that package exists and is active"""
        try:
            package = Package.objects.get(id=value, is_active=True)
        except Package.DoesNotExist:
            raise serializers.ValidationError("Package not found or is inactive.")
        return value

    def validate(self, data):
        """Validate purchase based on package type and user balance"""
        user = self.context['request'].user
        package = Package.objects.get(id=data['package_id'])

        # Get user's purchase currency balance
        if package.purchase_type == 'currency':
            try:
                user_purchase_balance = UserCurrency.objects.get(
                    user=user,
                    currency=package.purchase_currency
                ).balance
            except UserCurrency.DoesNotExist:
                user_purchase_balance = 0

            # Check if user has enough currency
            if user_purchase_balance < package.price:
                raise serializers.ValidationError(
                    f"Insufficient {package.purchase_currency.name}. "
                    f"You have {user_purchase_balance} but need {package.price}."
                )

        data['package'] = package
        data['user'] = user
        return data

    @transaction.atomic
    def create(self, validated_data):
        """
        Create UserPackage and handle currency transactions
        - For gold packages (currency purchase): Auto-complete and deduct balance
        - For diamond packages (real money): Create pending status
        """
        user = validated_data['user']
        package = validated_data['package']

        if package.purchase_type == 'currency':
            # In-game currency purchase (Gold packages)
            # 1. Deduct purchase currency from user
            user_purchase_currency = UserCurrency.objects.get(
                user=user,
                currency=package.purchase_currency
            )
            user_purchase_currency.balance -= package.price
            user_purchase_currency.save(update_fields=['balance'])

            # 2. Create UserPackage with 'completed' status
            user_package = UserPackage.objects.create(
                user=user,
                package=package,
                status='completed'
            )

            # 3. Signal will handle adding the currency to user balance
            logger.info(
                f"✅ User {user.username} purchased {package.name} "
                f"(spent {package.price} {package.purchase_currency.name})"
            )

        else:
            # Real money purchase (Diamond packages)
            # Create UserPackage with 'pending' status for admin review
            user_package = UserPackage.objects.create(
                user=user,
                package=package,
                status='pending'
            )

            logger.info(
                f"🔔 User {user.username} requested purchase of {package.name} "
                f"(pending admin review)"
            )

        return user_package


class UpdatePackageStatusSerializer(serializers.ModelSerializer):
    """
    Serializer for admin to update package purchase status
    Only for real money purchases
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = UserPackage
        fields = ['id', 'status', 'status_display', 'admin_notes', 'updated_at']
        read_only_fields = ['id', 'status_display', 'updated_at']

    def validate_status(self, value):
        """Validate status transition"""
        instance = self.instance
        if instance.package.purchase_type == 'currency':
            raise serializers.ValidationError(
                "Cannot manually change status of in-game currency purchases. "
                "They are auto-completed."
            )
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Update status and handle currency balance changes
        - 'done': Add currency to user balance
        - 'failed': Optionally refund (for in-game purchases only)
        """
        old_status = instance.status
        new_status = validated_data.get('status', old_status)

        if new_status == 'done' and old_status != 'done':
            # Add currency to user balance
            user_currency, created = UserCurrency.objects.get_or_create(
                user=instance.user,
                currency=instance.package.currency,
                defaults={'balance': 0}
            )
            user_currency.balance += instance.package.amount
            user_currency.save(update_fields=['balance'])

            logger.info(
                f"✅ Admin approved purchase: {instance.user.username} "
                f"received {instance.package.amount} {instance.package.currency.name}"
            )

        elif new_status == 'failed' and old_status != 'failed':
            logger.info(
                f"❌ Admin rejected purchase: {instance.user.username} - {instance.package.name}"
            )

        return super().update(instance, validated_data)