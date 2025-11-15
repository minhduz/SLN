# gamification/admin.py
from django.contrib import admin
from django import forms
from .models import Mission, UserMission, MissionReward, Reward, RewardRedemption
import json


class MissionRewardInline(admin.TabularInline):
    model = MissionReward
    extra = 2
    fields = ('currency', 'amount')
    verbose_name = "Mission Reward"
    verbose_name_plural = "Mission Rewards"

    # Add this to show currency name in dropdown
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "currency":
            kwargs["queryset"] = db_field.related_model.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class MissionAdminForm(forms.ModelForm):
    """Custom form with helper fields for building conditions"""

    # Quiz conditions
    min_score = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        help_text="Minimum score percentage (for quiz missions)"
    )

    # Question conditions
    exclude_own_questions = forms.BooleanField(
        required=False,
        help_text="User cannot answer/interact with their own questions"
    )
    only_public_questions = forms.BooleanField(
        required=False,
        help_text="Only count public questions"
    )

    # Quiz creation conditions
    min_rating = forms.FloatField(
        required=False,
        min_value=0,
        max_value=5,
        help_text="Minimum rating required (for create quiz missions)"
    )

    # Verification conditions
    unique_verifiers = forms.BooleanField(
        required=False,
        help_text="Must be verified by different users"
    )

    class Meta:
        model = Mission
        fields = '__all__'
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'cols': 60}),
            'conditions': forms.Textarea(attrs={'rows': 4, 'cols': 60}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Pre-populate helper fields from existing conditions
        if self.instance and self.instance.pk:
            conditions = self.instance.get_conditions()
            self.fields['min_score'].initial = conditions.get('min_score')
            self.fields['exclude_own_questions'].initial = conditions.get('exclude_own_questions', False)
            self.fields['only_public_questions'].initial = conditions.get('only_public_questions', False)
            self.fields['min_rating'].initial = conditions.get('min_rating')
            self.fields['unique_verifiers'].initial = conditions.get('unique_verifiers', False)

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Build conditions JSON from helper fields
        conditions = {}

        if self.cleaned_data.get('min_score') is not None:
            conditions['min_score'] = self.cleaned_data['min_score']

        if self.cleaned_data.get('exclude_own_questions'):
            conditions['exclude_own_questions'] = True

        if self.cleaned_data.get('only_public_questions'):
            conditions['only_public_questions'] = True

        if self.cleaned_data.get('min_rating') is not None:
            conditions['min_rating'] = self.cleaned_data['min_rating']

        if self.cleaned_data.get('unique_verifiers'):
            conditions['unique_verifiers'] = True

        # Merge with any manually entered JSON conditions
        try:
            if self.cleaned_data.get('conditions'):
                manual_conditions = self.cleaned_data.get('conditions')
                if isinstance(manual_conditions, str):
                    manual_conditions = json.loads(manual_conditions)
                conditions.update(manual_conditions)
        except:
            pass

        instance.conditions = conditions

        if commit:
            instance.save()
        return instance


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    form = MissionAdminForm
    inlines = [MissionRewardInline]
    list_display = ('title', 'type', 'cycle', 'target_count', 'is_active', 'is_random_pool', 'created_at')
    list_filter = ('cycle', 'type', 'is_active', 'is_random_pool')
    search_fields = ('title', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'type', 'is_active')
        }),
        ('Mission Cycle & Access', {
            'fields': ('cycle', 'access_type')
        }),
        ('Mission Goal', {
            'fields': ('target_count',)
        }),
        ('Random Pool Settings (Daily Missions Only)', {
            'fields': ('is_random_pool', 'pool_size'),
            'description': 'For daily missions, enable random pool to select X missions per user per day'
        }),
        ('Quiz Conditions', {
            'fields': ('min_score',),
            'classes': ('collapse',)
        }),
        ('Question Conditions', {
            'fields': ('exclude_own_questions', 'only_public_questions'),
            'classes': ('collapse',)
        }),
        ('Quiz Creation Conditions', {
            'fields': ('min_rating',),
            'classes': ('collapse',)
        }),
        ('Verification Conditions', {
            'fields': ('unique_verifiers',),
            'classes': ('collapse',)
        }),
        ('Advanced: Raw JSON Conditions', {
            'fields': ('conditions',),
            'classes': ('collapse',),
            'description': 'Advanced: Add custom conditions in JSON format'
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserMission)
class UserMissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'mission_title', 'cycle_date', 'progress', 'target_count', 'is_completed', 'completed_at')
    list_filter = ('is_completed', 'mission__cycle', 'mission__type', 'cycle_date')
    search_fields = ('user__username', 'mission__title')
    readonly_fields = ('id', 'created_at', 'updated_at', 'completed_at', 'metadata', 'cycle_date')
    date_hierarchy = 'cycle_date'

    def mission_title(self, obj):
        return obj.mission.title

    mission_title.short_description = 'Mission'

    def target_count(self, obj):
        return obj.mission.target_count

    target_count.short_description = 'Target'

    fieldsets = (
        ('Mission Info', {
            'fields': ('mission', 'user', 'squad', 'cycle_date')
        }),
        ('Progress', {
            'fields': ('progress', 'is_completed', 'completed_at')
        }),
        ('Tracking Data', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'currency', 'amount_required', 'is_active', 'created_at')
    list_filter = ('type', 'currency', 'is_active')
    search_fields = ('name', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'type', 'is_active')
        }),
        ('Cost', {
            'fields': ('currency', 'amount_required')
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RewardRedemption)
class RewardRedemptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'reward', 'status', 'created_at')
    list_filter = ('status', 'created_at', 'reward__type')
    search_fields = ('user__username', 'reward__name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    actions = ['approve_redemption', 'reject_redemption']

    def approve_redemption(self, request, queryset):
        updated = queryset.update(status='approved')
        self.message_user(request, f"{updated} redemption(s) approved.")

    approve_redemption.short_description = "Approve selected redemptions"

    def reject_redemption(self, request, queryset):
        updated = queryset.update(status='rejected')
        self.message_user(request, f"{updated} redemption(s) rejected.")

    reject_redemption.short_description = "Reject selected redemptions"

    fieldsets = (
        ('Redemption Info', {
            'fields': ('user', 'reward', 'status')
        }),
        ('System Fields', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )