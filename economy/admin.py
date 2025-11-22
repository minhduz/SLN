# economy/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages
from .models import Currency, UserCurrency, Package, UserPackage


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ('name', 'description_preview', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        (_('Currency Information'), {
            'fields': ('name', 'description')
        }),
        (_('System Fields'), {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def description_preview(self, obj):
        return obj.description[:50] + "..." if obj.description and len(obj.description) > 50 else obj.description

    description_preview.short_description = "Description"


@admin.register(UserCurrency)
class UserCurrencyAdmin(admin.ModelAdmin):
    list_display = ('user', 'currency', 'balance_display', 'updated_at')
    list_filter = ('currency', 'updated_at')
    search_fields = ('user__username', 'user__email', 'currency__name')
    readonly_fields = ('id', 'updated_at')

    fieldsets = (
        (_('User Balance'), {
            'fields': ('user', 'currency', 'balance')
        }),
        (_('System Fields'), {
            'fields': ('id', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def balance_display(self, obj):
        return format_html('<strong>{}</strong>', obj.balance)

    balance_display.short_description = "Balance"

    def has_add_permission(self, request):
        # Prevent manual creation, should be created programmatically
        return False


class PackageFilter(admin.SimpleListFilter):
    """Custom filter for package purchase type"""
    title = _('Purchase Type')
    parameter_name = 'purchase_type'

    def lookups(self, request, model_admin):
        return [
            ('real_money', _('Real Money (VND)')),
            ('currency', _('In-Game Currency')),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(purchase_type=self.value())
        return queryset


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = (
    'name', 'package_type_badge', 'amount_display', 'price_display', 'purchase_info', 'is_active_badge', 'created_at')
    list_filter = (PackageFilter, 'currency', 'is_active', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at', 'package_preview')
    ordering = ('-created_at',)

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'description', 'package_preview')
        }),
        (_('Currency Configuration'), {
            'fields': ('currency', 'amount'),
            'description': 'Select the currency type this package provides (e.g., Diamond, Gold)'
        }),
        (_('Purchase Configuration'), {
            'fields': ('purchase_type', 'purchase_currency', 'price'),
            'description': 'Configure how users purchase this package'
        }),

        (_('Status'), {
            'fields': ('is_active',)
        }),
        (_('System Fields'), {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def package_type_badge(self, obj):
        if obj.purchase_type == 'real_money':
            badge_color = '#FF6B6B'  # Red for real money
            label = 'Real Money'
        else:
            badge_color = '#4ECDC4'  # Teal for in-game currency
            label = 'In-Game'
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">{}</span>',
            badge_color, label
        )

    package_type_badge.short_description = "Type"

    def amount_display(self, obj):
        return format_html(
            '<strong>{}</strong> {}',
            obj.amount,
            obj.currency.name
        )

    amount_display.short_description = "Amount"

    def price_display(self, obj):
        if obj.purchase_type == 'real_money':
            formatted_price = f"{obj.price:,.0f}"
            return format_html(
                '₫<strong>{}</strong>',
                formatted_price
            )
        else:
            return format_html(
                '<strong>{}</strong> {}',
                obj.price,
                obj.purchase_currency.name if obj.purchase_currency else 'N/A'
            )

    price_display.short_description = "Price"

    def purchase_info(self, obj):
        if obj.purchase_type == 'real_money':
            info = f"₫{obj.price:,.0f} VND"
        else:
            info = f"{obj.price} {obj.purchase_currency.name}" if obj.purchase_currency else "Not Set"
        return info

    purchase_info.short_description = "Purchase Info"

    def is_active_badge(self, obj):
        color = '#28A745' if obj.is_active else '#DC3545'
        label = 'Active' if obj.is_active else 'Inactive'
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color, label
        )

    is_active_badge.short_description = "Status"

    def package_preview(self, obj):
        return format_html(
            '<div style="padding: 10px; border-radius: 4px;">'
            '<p><strong>Provides:</strong> {} {}</p>'
            '<p><strong>Purchase with:</strong> {} @ {}</p>'
            '</div>',
            obj.amount,
            obj.currency.name,
            obj.purchase_type.replace('_', ' ').title(),
            f"₫{obj.price:,.0f}" if obj.purchase_type == 'real_money' else f"{obj.price} {obj.purchase_currency.name}" if obj.purchase_currency else "Not Set"
        )

    package_preview.short_description = "Package Preview"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'purchase_currency':
            kwargs["queryset"] = Currency.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing existing object
            return self.readonly_fields + ('currency', 'purchase_type')
        return self.readonly_fields

    actions = ['activate_packages', 'deactivate_packages']

    def activate_packages(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} package(s) activated.")

    activate_packages.short_description = "Activate selected packages"

    def deactivate_packages(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} package(s) deactivated.")

    deactivate_packages.short_description = "Deactivate selected packages"


class PurchaseStatusFilter(admin.SimpleListFilter):
    """Custom filter for purchase status"""
    title = _('Purchase Status')
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('pending', _('🔔 Pending Review')),
            ('done', _('✅ Done')),
            ('failed', _('❌ Failed')),
            ('completed', _('✨ Auto-Completed')),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


@admin.register(UserPackage)
class UserPackageAdmin(admin.ModelAdmin):
    list_display = ('user_info', 'package_info', 'purchase_status_badge', 'updated_at')
    list_filter = (PurchaseStatusFilter, 'package__currency', 'package__purchase_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'package__name')
    readonly_fields = ('id', 'created_at', 'updated_at', 'subscription_details', 'purchase_workflow_info')
    ordering = ('-created_at',)

    fieldsets = (
        (_('Subscription Information'), {
            'fields': ('user', 'package', 'subscription_details')
        }),
        (_('Purchase Status & Review'), {
            'fields': ('status', 'admin_notes', 'purchase_workflow_info'),
            'description': 'Manage real money purchases here'
        }),

        (_('Status'), {
            'fields': ('is_active',)
        }),
        (_('System Fields'), {
            'fields': ('id', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def user_info(self, obj):
        # Get display name with fallback
        display_name = getattr(obj.user, 'get_full_name', lambda: obj.user.username)()
        if not display_name.strip():
            display_name = obj.user.username

        return format_html(
            '{}<br/><small style="color: gray;">{}</small>',
            display_name,
            obj.user.email
        )

    user_info.short_description = "User"

    def package_info(self, obj):
        purchase_type_label = "VND" if obj.package.purchase_type == 'real_money' else obj.package.purchase_currency.name
        return format_html(
            '{}<br/><small style="color: gray;">{} {} (Cost: {} {})</small>',
            obj.package.name,
            obj.package.amount,
            obj.package.currency.name,
            obj.package.price,
            purchase_type_label
        )

    package_info.short_description = "Package"

    def purchase_status_badge(self, obj):
        status_colors = {
            'pending': '#FFA500',  # Orange
            'done': '#28A745',  # Green
            'failed': '#DC3545',  # Red
            'completed': '#17A2B8',  # Blue (cyan)
        }

        status_icons = {
            'pending': '🔔',
            'done': '✅',
            'failed': '❌',
            'completed': '✨',
        }

        color = status_colors.get(obj.status, '#6C757D')
        icon = status_icons.get(obj.status, '')
        label = obj.get_status_display()

        return format_html(
            '<span style="background-color: {}; color: white; padding: 5px 10px; border-radius: 3px; font-weight: bold;">{} {}</span>',
            color, icon, label
        )

    purchase_status_badge.short_description = "Status"

    def subscription_details(self, obj):
        return format_html(
            '<div style="padding: 10px; border-radius: 4px;">'
            '<p><strong>Currency:</strong> {} {}</p>'
            '<p><strong>Purchase Type:</strong> {}</p>'
            '</div>',
            obj.package.amount,
            obj.package.currency.name,
            obj.package.get_purchase_type_display()
        )

    subscription_details.short_description = "Subscription Details"

    def purchase_workflow_info(self, obj):
        """Display workflow information based on purchase type"""
        purchase_type = obj.package.purchase_type

        if purchase_type == 'currency':
            # In-game currency purchase - auto-completed
            info_html = (
                '<div style="background: #d4edda; padding: 10px; border-radius: 4px; border-left: 4px solid #28A745;">'
                '<p style="margin: 0;"><strong>✨ In-Game Currency Purchase</strong></p>'
                '<p style="margin: 5px 0 0 0; font-size: 12px; color: #155724;">'
                'This purchase is automatically completed. User was charged {} {} and received {} {}.'
                '</p>'
                '</div>'
            ).format(
                obj.package.price,
                obj.package.purchase_currency.name,
                obj.package.amount,
                obj.package.currency.name
            )
        else:
            # Real money purchase - needs review
            if obj.status == 'pending':
                info_html = (
                    '<div style="background: #fff3cd; padding: 10px; border-radius: 4px; border-left: 4px solid #FFC107;">'
                    '<p style="margin: 0;"><strong>🔔 Pending Review (Real Money)</strong></p>'
                    '<p style="margin: 5px 0 0 0; font-size: 12px; color: #856404;">'
                    'This purchase is awaiting admin review. User will receive {} {} once approved.'
                    '</p>'
                    '</div>'
                ).format(obj.package.amount, obj.package.currency.name)
            elif obj.status == 'done':
                info_html = (
                    '<div style="background: #d4edda; padding: 10px; border-radius: 4px; border-left: 4px solid #28A745;">'
                    '<p style="margin: 0;"><strong>✅ Purchase Approved</strong></p>'
                    '<p style="margin: 5px 0 0 0; font-size: 12px; color: #155724;">'
                    'User has received {} {} for this purchase.'
                    '</p>'
                    '</div>'
                ).format(obj.package.amount, obj.package.currency.name)
            elif obj.status == 'failed':
                info_html = (
                    '<div style="background: #f8d7da; padding: 10px; border-radius: 4px; border-left: 4px solid #DC3545;">'
                    '<p style="margin: 0;"><strong>❌ Purchase Rejected</strong></p>'
                    '<p style="margin: 5px 0 0 0; font-size: 12px; color: #721C24;">'
                    'This purchase has been rejected. User will not receive any currency.'
                    '</p>'
                    '</div>'
                )
            else:
                info_html = '<p>Unknown status</p>'

        return format_html(info_html)

    purchase_workflow_info.short_description = "Purchase Workflow"

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))

        # Customize fieldsets based on purchase type
        if obj and obj.package.purchase_type == 'currency':
            # Remove purchase status fieldset for in-game purchases
            fieldsets = [fs for fs in fieldsets if fs[0] != _('Purchase Status & Review')]

        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if obj and obj.package.purchase_type == 'currency':
            # In-game purchases should be read-only
            readonly.extend(['status', 'admin_notes'])
        return readonly

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """Customize status field choices based on purchase type"""
        if db_field.name == 'status':
            # All choices are available, but context is shown in form
            pass
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    actions = ['approve_purchases', 'reject_purchases']

    def approve_purchases(self, request, queryset):
        """Bulk approve pending real money purchases"""
        pending = queryset.filter(status='pending', package__purchase_type='real_money')
        updated = 0
        for obj in pending:
            obj.status = 'done'
            obj.save()
            updated += 1

        if updated > 0:
            self.message_user(
                request,
                f'✅ {updated} purchase(s) approved. Currency has been added to user(s).',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No pending real money purchases to approve.',
                messages.WARNING
            )

    approve_purchases.short_description = "Approve selected purchases"

    def reject_purchases(self, request, queryset):
        """Bulk reject pending real money purchases"""
        pending = queryset.filter(status='pending', package__purchase_type='real_money')
        updated = 0
        for obj in pending:
            obj.status = 'failed'
            obj.save()
            updated += 1

        if updated > 0:
            self.message_user(
                request,
                f'❌ {updated} purchase(s) rejected.',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No pending real money purchases to reject.',
                messages.WARNING
            )

    reject_purchases.short_description = "Reject selected purchases"