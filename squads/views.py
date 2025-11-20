from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model

from .models import Squad, SquadMember
from .serializers import (
    SquadSerializer,
    CreateSquadSerializer,
    UpdateSquadSerializer,
    DeleteSquadSerializer,
    AddMembersSerializer,
    RemoveMemberSerializer,
    UpdateMemberRoleSerializer,
    SquadMemberSerializer
)

import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class CreateSquadView(generics.CreateAPIView):
    """
    Create a new squad. The creator is automatically added as the leader.
    User can only be in one squad at a time.
    """
    queryset = Squad.objects.all()
    serializer_class = CreateSquadSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            squad = serializer.save()

            output_serializer = SquadSerializer(squad)
            return Response(
                output_serializer.data,
                status=status.HTTP_201_CREATED
            )
        except ValidationError as e:
            return Response(
                {"error": e.detail},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error creating squad: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class UpdateSquadView(generics.UpdateAPIView):
    """
    Update squad information. Only leaders can update the squad.
    Supports both PUT and PATCH methods.
    """
    queryset = Squad.objects.all()
    serializer_class = UpdateSquadSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_object(self):
        squad = super().get_object()

        is_leader = squad.memberships.filter(
            user=self.request.user,
            role='leader'
        ).exists()

        if not is_leader:
            raise PermissionDenied("Only squad leaders can update squad information")

        return squad

    def update(self, request, *args, **kwargs):
        try:
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            squad = serializer.save()

            output_serializer = SquadSerializer(squad)
            return Response(output_serializer.data)
        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except ValidationError as e:
            return Response(
                {"error": e.detail},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error updating squad: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class DeleteSquadView(generics.DestroyAPIView):
    """
    Delete a squad. Only leaders can delete the squad.
    This will remove all members and delete the squad avatar.
    """
    queryset = Squad.objects.all()
    serializer_class = DeleteSquadSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_object(self):
        squad = super().get_object()

        is_leader = squad.memberships.filter(
            user=self.request.user,
            role='leader'
        ).exists()

        if not is_leader:
            raise PermissionDenied("Only squad leaders can delete the squad")

        return squad

    def destroy(self, request, *args, **kwargs):
        try:
            squad = self.get_object()
            serializer = self.get_serializer(context={'squad': squad})
            result = serializer.save()

            return Response(
                result,
                status=status.HTTP_200_OK
            )
        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            logger.error(f"Error deleting squad: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class RetrieveSquadView(generics.RetrieveAPIView):
    """
    Get squad details including all members.
    """
    queryset = Squad.objects.prefetch_related('memberships__user').all()
    serializer_class = SquadSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'


class GetMySquadView(generics.RetrieveAPIView):
    """
    Get the current user's squad. Returns 404 if user is not in any squad.
    """
    serializer_class = SquadSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        user = self.request.user
        try:
            membership = SquadMember.objects.select_related('squad').get(user=user)
            return Squad.objects.prefetch_related('memberships__user').get(id=membership.squad.id)
        except SquadMember.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("You are not a member of any squad")


class AddMemberView(generics.CreateAPIView):
    """
    Add multiple members to a squad at once. Only leaders can add members.
    """
    serializer_class = AddMembersSerializer
    permission_classes = [IsAuthenticated]

    def get_squad(self):
        squad_id = self.kwargs.get('squad_id')
        squad = get_object_or_404(Squad, id=squad_id)

        is_leader = squad.memberships.filter(
            user=self.request.user,
            role='leader'
        ).exists()

        if not is_leader:
            raise PermissionDenied("Only squad leaders can add members")

        return squad

    def create(self, request, *args, **kwargs):
        try:
            squad = self.get_squad()
            serializer = self.get_serializer(
                data=request.data,
                context={'squad': squad}
            )
            serializer.is_valid(raise_exception=True)
            result = serializer.save()

            return Response(
                {
                    'message': f'Successfully added {result["total_added"]} member(s)',
                    'total_added': result['total_added'],
                    'total_failed': result['total_failed'],
                    'successful': result['successful'],
                    'failed': result['failed']
                },
                status=status.HTTP_201_CREATED if result['total_added'] > 0 else status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except ValidationError as e:
            return Response(
                {"error": e.detail},
                status=status.HTTP_400_BAD_REQUEST
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error adding members: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class RemoveMemberView(generics.DestroyAPIView):
    """
    Remove a member from a squad. Leaders can remove members, or users can remove themselves.
    If a leader leaves and there are other members, the oldest member is automatically promoted to leader.
    If the squad becomes empty, it will be automatically deleted.
    """
    serializer_class = RemoveMemberSerializer
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        try:
            squad_id = kwargs.get('squad_id')
            user_id = kwargs.get('user_id')

            squad = get_object_or_404(Squad, id=squad_id)
            user = get_object_or_404(User, id=user_id)

            # Check permissions: must be leader or removing self
            is_leader = squad.memberships.filter(
                user=request.user,
                role='leader'
            ).exists()
            is_self = str(request.user.id) == str(user_id)

            if not (is_leader or is_self):
                raise PermissionDenied(
                    "Only squad leaders can remove members, or you can remove yourself"
                )

            serializer = self.get_serializer(context={'squad': squad, 'user': user})
            result = serializer.save()

            response_data = {"message": "Member removed successfully"}

            # Add promoted member info if applicable
            if result.get('promoted_member'):
                promoted = result['promoted_member']
                response_data['promoted_member'] = promoted
                response_data['message'] = (
                    f"Member removed successfully. "
                    f"{promoted['full_name'] or promoted['username']} has been promoted to leader."
                )

            return Response(
                response_data,
                status=status.HTTP_200_OK
            )
        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error removing member: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class UpdateMemberRoleView(generics.UpdateAPIView):
    """
    Update a member's role in the squad. Only leaders can change roles.
    When promoting a member to leader, all existing leaders are automatically demoted to members.
    """
    serializer_class = UpdateMemberRoleSerializer
    permission_classes = [IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        try:
            squad_id = kwargs.get('squad_id')
            user_id = kwargs.get('user_id')

            squad = get_object_or_404(Squad, id=squad_id)
            user = get_object_or_404(User, id=user_id)

            # Check if user is a leader
            is_leader = squad.memberships.filter(
                user=request.user,
                role='leader'
            ).exists()

            if not is_leader:
                raise PermissionDenied("Only squad leaders can update member roles")

            serializer = self.get_serializer(
                data=request.data,
                context={'squad': squad, 'user': user}
            )
            serializer.is_valid(raise_exception=True)
            result = serializer.save()

            membership = result['membership']
            demoted_leaders = result.get('demoted_leaders', [])

            output_serializer = SquadMemberSerializer(membership)
            response_data = output_serializer.data

            # Add demoted leaders info
            if demoted_leaders:
                response_data['demoted_leaders'] = demoted_leaders

            return Response(response_data)

        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except ValidationError as e:
            return Response(
                {"error": e.detail},
                status=status.HTTP_400_BAD_REQUEST
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error updating member role: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )