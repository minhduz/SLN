import os
import uuid
from django.core.files.storage import default_storage
from ..models import Squad, SquadMember
from django.db import transaction
from accounts.tasks import delete_avatar_task
import logging
from accounts.models import User

logger = logging.getLogger(__name__)


def rename_and_save_squad_avatar(squad: Squad, avatar):
    """
    Save squad avatar with a unique filename based on squad.id + random UUID,
    ensuring unique URLs for cache-busting.
    """
    ext = os.path.splitext(avatar.name)[1].lower()
    # ✅ Add random UUID to make filename unique
    unique_id = uuid.uuid4().hex[:8]  # Use first 8 chars of UUID
    avatar_filename = f"squad_avatars/{squad.id}_{unique_id}{ext}"

    saved_path = default_storage.save(avatar_filename, avatar)
    logger.info(f"New avatar saved: {saved_path}")
    return saved_path


@transaction.atomic
def create_squad(user, validated_data):
    """
    Create a new squad and automatically add the creator as the leader.
    Enforces one squad per user rule.
    """
    # Double check user is not in any squad
    if SquadMember.objects.filter(user=user).exists():
        raise ValueError("You are already a member of a squad")

    avatar = validated_data.pop("avatar", None)

    # Create the squad
    squad = Squad(
        create_by=user,
        **validated_data
    )
    squad.save()

    # Handle avatar if provided
    if avatar:
        saved_path = rename_and_save_squad_avatar(squad, avatar)
        squad.avatar.name = saved_path
        squad.save()

    # Automatically add creator as leader
    SquadMember.objects.create(
        squad=squad,
        user=user,
        role='leader'
    )

    logger.info(f"Squad created: {squad.id} by user {user.id}")
    return squad


@transaction.atomic
def update_squad(squad, validated_data):
    """
    Update squad information and handle avatar changes.
    """

    avatar = validated_data.pop("avatar", None)

    # Fetch old avatar from DB if avatar is being updated
    old_avatar = None
    if avatar and squad.pk:
        old_avatar_obj = Squad.objects.only("avatar").get(pk=squad.pk)
        old_avatar = old_avatar_obj.avatar
        logger.info(f"Old avatar: {old_avatar.name if old_avatar else 'None'}")

    # Update squad fields
    for attr, value in validated_data.items():
        setattr(squad, attr, value)

    # Handle new avatar
    if avatar:

        # ✅ Save new avatar with unique filename
        saved_path = rename_and_save_squad_avatar(squad, avatar)
        logger.info(f"  - Saved to: {saved_path}")

        squad.avatar.name = saved_path

        # ✅ Schedule async deletion of old avatar AFTER saving new one
        if old_avatar:
            logger.info(f"Scheduling deletion of old avatar: {old_avatar.name}")
            delete_avatar_task.delay(old_avatar.name)

    squad.save()
    logger.info(f"Squad saved - avatar field: {squad.avatar.name if squad.avatar else 'None'}")
    return squad


@transaction.atomic
def delete_squad(squad):
    """
    Delete a squad and clean up its avatar.
    """
    squad_id = squad.id

    # Get avatar path before deletion
    avatar_path = squad.avatar.name if squad.avatar else None

    # Delete the squad (memberships will be cascade deleted)
    squad.delete()

    # Async cleanup avatar
    if avatar_path:
        delete_avatar_task.delay(avatar_path)

    logger.info(f"Squad deleted: {squad_id}")
    return True


@transaction.atomic
def add_members_to_squad(squad, user_ids, default_role='member'):
    """
    Add multiple members to a squad at once.
    Returns dict with successful and failed additions.
    """
    results = {
        'successful': [],
        'failed': [],
        'total_added': 0,
        'total_failed': 0
    }

    for user_id in user_ids:
        try:
            # Get user
            user = User.objects.get(id=user_id)

            # Check if user is already in any squad
            if SquadMember.objects.filter(user=user).exists():
                results['failed'].append({
                    'user_id': str(user_id),
                    'username': user.username,
                    'reason': 'User is already a member of another squad'
                })
                continue

            # Check if squad is full
            current_member_count = squad.memberships.count()
            if current_member_count >= squad.max_members:
                results['failed'].append({
                    'user_id': str(user_id),
                    'username': user.username,
                    'reason': f'Squad is full. Maximum members: {squad.max_members}'
                })
                continue

            # Add member
            membership = SquadMember.objects.create(
                squad=squad,
                user=user,
                role=default_role
            )

            results['successful'].append({
                'user_id': str(user.id),
                'username': user.username,
                'full_name': user.full_name,
                'role': membership.role,
                'membership_id': str(membership.id)
            })
            results['total_added'] += 1

            logger.info(f"User {user.id} added to squad {squad.id} as {default_role}")

        except User.DoesNotExist:
            results['failed'].append({
                'user_id': str(user_id),
                'username': None,
                'reason': 'User does not exist'
            })
        except Exception as e:
            logger.error(f"Error adding user {user_id} to squad: {str(e)}")
            results['failed'].append({
                'user_id': str(user_id),
                'username': None,
                'reason': str(e)
            })

    results['total_failed'] = len(results['failed'])

    logger.info(f"Bulk add complete: {results['total_added']} added, {results['total_failed']} failed")
    return results


@transaction.atomic
def remove_member_from_squad(squad, user):
    """
    Remove a member from a squad with validation.
    If a leader leaves and there are other members, promote the oldest member to leader.
    """
    try:
        membership = SquadMember.objects.get(squad=squad, user=user)

        # Check if this is a leader leaving
        is_leader_leaving = membership.role == 'leader'

        if is_leader_leaving:
            leader_count = squad.memberships.filter(role='leader').count()

            # If this is the last leader
            if leader_count <= 1:
                # Get other members (excluding the one leaving)
                other_members = squad.memberships.exclude(user=user).order_by('created_at')

                if other_members.exists():
                    # Promote the oldest member to leader
                    oldest_member = other_members.first()
                    oldest_member.role = 'leader'
                    oldest_member.save()
                    logger.info(
                        f"User {oldest_member.user.id} automatically promoted to leader "
                        f"after leader {user.id} left squad {squad.id}"
                    )

        # Delete the membership
        membership.delete()
        logger.info(f"User {user.id} removed from squad {squad.id}")

        # If squad is now empty, delete it
        if squad.memberships.count() == 0:
            delete_squad(squad)
            logger.info(f"Squad {squad.id} deleted (no members remaining)")

        # Return the promoted member info if applicable
        result = {
            'removed': True,
            'promoted_member': None
        }

        if is_leader_leaving and leader_count <= 1:
            other_members = squad.memberships.filter(role='leader').exclude(user=user)
            if other_members.exists():
                promoted = other_members.first()
                result['promoted_member'] = {
                    'user_id': str(promoted.user.id),
                    'username': promoted.user.username,
                    'full_name': promoted.user.full_name
                }

        return result

    except SquadMember.DoesNotExist:
        raise ValueError("User is not a member of this squad")


@transaction.atomic
def update_member_role(squad, user, new_role):
    """
    Update a member's role in the squad.
    If promoting to leader, demote all existing leaders to members.
    """
    try:
        membership = SquadMember.objects.get(squad=squad, user=user)
        old_role = membership.role

        # If promoting to leader, demote all current leaders to members
        if new_role == 'leader' and old_role != 'leader':
            # Get all current leaders
            current_leaders = squad.memberships.filter(role='leader')
            demoted_leaders = []

            for leader in current_leaders:
                leader.role = 'member'
                leader.save()
                demoted_leaders.append({
                    'user_id': str(leader.user.id),
                    'username': leader.user.username,
                    'full_name': leader.user.full_name
                })
                logger.info(f"User {leader.user.id} demoted from leader to member in squad {squad.id}")

        # Update the target member's role
        membership.role = new_role
        membership.save()

        logger.info(f"User {user.id} role updated to {new_role} in squad {squad.id}")

        # Return membership with demoted leaders info
        result = {
            'membership': membership,
            'demoted_leaders': demoted_leaders if new_role == 'leader' else []
        }

        return result

    except SquadMember.DoesNotExist:
        raise ValueError("User is not a member of this squad")