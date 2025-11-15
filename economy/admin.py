# economy/admin.py
from django.contrib import admin
from .models import Currency, UserCurrency, Package, UserPackage


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        ('Currency Information', {
            'fields': ('name', 'description')
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserCurrency)
class UserCurrencyAdmin(admin.ModelAdmin):
    list_display = ('user', 'currency', 'balance', 'updated_at')
    list_filter = ('currency', 'created_at')
    search_fields = ('user__username', 'currency__name')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        ('User Balance', {
            'fields': ('user', 'currency', 'balance')
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'ai_question_limit_per_day', 'duration', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        ('Package Information', {
            'fields': ('name', 'description', 'price')
        }),
        ('Package Features', {
            'fields': ('ai_question_limit_per_day', 'duration')
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserPackage)
class UserPackageAdmin(admin.ModelAdmin):
    list_display = ('user', 'package', 'is_active', 'start_date', 'end_date')
    list_filter = ('is_active', 'package', 'start_date', 'end_date')
    search_fields = ('user__username', 'package__name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    date_hierarchy = 'start_date'

    fieldsets = (
        ('Subscription Information', {
            'fields': ('user', 'package', 'is_active')
        }),
        ('Subscription Period', {
            'fields': ('start_date', 'end_date')
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )