from rest_framework import serializers
from .models import Squad, SquadMember
from django.contrib.auth import get_user_model
from .services.squad_service import (
    create_squad,
    update_squad,
    add_members_to_squad,
    delete_squad,
    remove_member_from_squad,
    update_member_role
)

User = get_user_model()


class SquadMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    full_name = serializers.CharField(source='user.full_name', read_only=True)
    avatar = serializers.ImageField(source='user.avatar', read_only=True)

    class Meta:
        model = SquadMember
        fields = ['id', 'user_id', 'username', 'full_name', 'avatar', 'role', 'created_at']
        read_only_fields = ['id', 'created_at']


class SquadSerializer(serializers.ModelSerializer):
    memberships = SquadMemberSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='create_by.username', read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Squad
        fields = [
            'id', 'name', 'description', 'max_members', 'min_members',
            'avatar', 'create_by', 'created_by_username', 'member_count',
            'memberships', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'create_by', 'created_at', 'updated_at']

    def get_member_count(self, obj):
        return obj.memberships.count()


class CreateSquadSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(required=False)

    class Meta:
        model = Squad
        fields = ['name', 'description', 'max_members', 'min_members', 'avatar']

    def validate(self, data):
        if data.get('min_members', 3) > data.get('max_members', 5):
            raise serializers.ValidationError(
                "min_members cannot be greater than max_members"
            )

        # Check if user is already in a squad
        user = self.context['request'].user
        if SquadMember.objects.filter(user=user).exists():
            raise serializers.ValidationError(
                "You are already a member of a squad. Leave your current squad first."
            )

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        return create_squad(user, validated_data)


class UpdateSquadSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(required=False)

    class Meta:
        model = Squad
        fields = ['name', 'description', 'max_members', 'min_members', 'avatar']

    def validate(self, data):
        if 'min_members' in data or 'max_members' in data:
            min_members = data.get('min_members', self.instance.min_members)
            max_members = data.get('max_members', self.instance.max_members)
            if min_members > max_members:
                raise serializers.ValidationError(
                    "min_members cannot be greater than max_members"
                )

            # Check if current member count exceeds new max_members
            current_count = self.instance.memberships.count()
            if 'max_members' in data and current_count > data['max_members']:
                raise serializers.ValidationError(
                    f"Cannot set max_members to {data['max_members']}. Current member count is {current_count}."
                )

        return data

    def update(self, instance, validated_data):
        return update_squad(instance, validated_data)


class DeleteSquadSerializer(serializers.Serializer):
    """
    Serializer for deleting a squad.
    No input fields needed - deletion is based on the squad instance.
    """

    def save(self):
        squad = self.context['squad']
        delete_squad(squad)
        return {'message': f"Squad '{squad.name}' has been deleted successfully"}


class AddMembersSerializer(serializers.Serializer):
    """
    Serializer for adding multiple members to a squad at once.
    """
    user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=50,
        help_text="List of user IDs to add to the squad"
    )
    role = serializers.ChoiceField(
        choices=SquadMember.ROLE_CHOICES,
        default='member',
        required=False,
        help_text="Role to assign to all added members (default: member)"
    )

    def validate_user_ids(self, value):
        # Remove duplicates
        unique_ids = list(set(value))
        if len(unique_ids) != len(value):
            raise serializers.ValidationError("Duplicate user IDs are not allowed")
        return unique_ids

    def create(self, validated_data):
        squad = self.context['squad']
        user_ids = validated_data['user_ids']
        role = validated_data.get('role', 'member')

        return add_members_to_squad(squad, user_ids, role)


class RemoveMemberSerializer(serializers.Serializer):
    """
    Serializer for removing a member from a squad.
    No input fields needed - removal is based on context.
    """

    def save(self):
        squad = self.context['squad']
        user = self.context['user']
        remove_member_from_squad(squad, user)
        return {'message': 'Member removed successfully'}


class UpdateMemberRoleSerializer(serializers.Serializer):
    """
    Serializer for updating a member's role in a squad.
    When promoting to leader, all existing leaders are automatically demoted to members.
    """
    role = serializers.ChoiceField(
        choices=SquadMember.ROLE_CHOICES,
        help_text="New role for the member (leader or member)"
    )

    def validate_role(self, value):
        if not value:
            raise serializers.ValidationError("Role is required")
        return value

    def save(self):
        squad = self.context['squad']
        user = self.context['user']
        role = self.validated_data['role']

        result = update_member_role(squad, user, role)
        return result