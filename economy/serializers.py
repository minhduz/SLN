# economy/serializers.py
from rest_framework import serializers
from .models import Currency, UserCurrency


class CurrencySerializer(serializers.ModelSerializer):
    """Serializer for Currency"""

    class Meta:
        model = Currency
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']


class UserCurrencySerializer(serializers.ModelSerializer):
    """Serializer for user's currency balance"""
    currency = CurrencySerializer(read_only=True)
    currency_id = serializers.UUIDField(source='currency.id', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)

    class Meta:
        model = UserCurrency
        fields = [
            'id',
            'currency',
            'currency_id',
            'currency_name',
            'balance',
            'created_at',
            'updated_at'
        ]