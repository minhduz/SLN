# gamification/views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta

from .models import UserMission, SquadMissionProgress
from squads.models import SquadMember
from .serializers import UserMissionSerializer, SquadMissionProgressSerializer
from .services.reset_services import MissionResetService  # ✅ Import the service
from .services.squad_mission_services import SquadMissionService  # ✅ Import squad service
from .utils import get_user_current_date  # ✅ Import timezone-aware date getter

import logging

logger = logging.getLogger(__name__)


class UserMissionsView(APIView):
    """
    GET /api/gamification/missions/
    Get all missions for the current user with optional filters

    Query Parameters:
    - cycle: daily/weekly/permanent (optional)
    - status: active/completed/all (default: active)

    Example:
    GET /api/gamification/missions/
    GET /api/gamification/missions/?cycle=daily
    GET /api/gamification/missions/?status=completed
    GET /api/gamification/missions/?cycle=weekly&status=all
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get user's missions with filters"""
        try:
            user = request.user
            cycle = request.query_params.get('cycle')
            status_filter = request.query_params.get('status', 'active')

            # ✅ LAZY RESET: Ensure user has today's missions before fetching
            MissionResetService.ensure_user_has_todays_missions(user)
            MissionResetService.ensure_user_has_weekly_missions(user)

            # ✅ LAZY RESET: Ensure squad missions exist
            today = get_user_current_date(user)
            monday = today - timedelta(days=today.weekday())

            # Get user's squads and ensure they have missions
            user_squad_memberships = SquadMember.objects.filter(
                user=user
            ).select_related('squad')

            for membership in user_squad_memberships:
                SquadMissionService.ensure_squad_has_missions(
                    squad=membership.squad,
                    cycle_date=today,
                    cycle_type='daily'
                )
                SquadMissionService.ensure_squad_has_missions(
                    squad=membership.squad,
                    cycle_date=monday,
                    cycle_type='weekly'
                )

            # Get today's date and Monday of current week IN USER'S TIMEZONE
            today = get_user_current_date(user)  # ✅ Use timezone-aware date
            monday = today - timedelta(days=today.weekday())

            # Base queryset for ALL current cycle missions (for stats)
            base_queryset = UserMission.objects.filter(user=user).filter(
                Q(cycle_date=today) |  # Today's daily missions (in user's timezone)
                Q(cycle_date=monday, mission__cycle='weekly') |  # This week's missions
                Q(mission__cycle='permanent')  # All permanent missions
            )

            # Calculate mission statistics
            stats = base_queryset.aggregate(
                total=Count('id'),
                completed=Count('id', filter=Q(is_completed=True)),
                in_progress=Count('id', filter=Q(is_completed=False))
            )

            # Now apply filters for the actual returned missions
            queryset = base_queryset.select_related(
                'mission'
            ).prefetch_related(
                'mission__rewards__currency'
            )

            # Filter by cycle
            if cycle:
                queryset = queryset.filter(mission__cycle=cycle)

            # Filter by status
            if status_filter == 'active':
                queryset = queryset.filter(is_completed=False)
            elif status_filter == 'completed':
                queryset = queryset.filter(is_completed=True)
            # 'all' returns everything

            # Order: incomplete first, then by creation date
            queryset = queryset.order_by('is_completed', '-created_at')

            serializer = UserMissionSerializer(queryset, many=True)

            return Response({
                'success': True,
                'total_missions': stats['total'],
                'completed_missions': stats['completed'],
                'in_progress_missions': stats['in_progress'],
                'missions': serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching user missions: {str(e)}", exc_info=True)
            return Response(
                {'success': False, 'error': 'Failed to fetch missions'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# gamification/views.py
class UserSquadMissionsView(APIView):
    """
    GET /api/gamification/squad-missions/
    Get squad missions for all squads the user belongs to

    Query Parameters:
    - cycle: daily/weekly (optional)
    - status: active/completed/all (default: all)
    - squad_id: filter by specific squad (optional)

    Example:
    GET /api/gamification/squad-missions/
    GET /api/gamification/squad-missions/?cycle=daily
    GET /api/gamification/squad-missions/?status=completed
    GET /api/gamification/squad-missions/?squad_id=<uuid>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get squad missions for user's squads"""
        try:
            user = request.user
            cycle = request.query_params.get('cycle')
            status_filter = request.query_params.get('status', 'all')  # ✅ Changed default to 'all'
            squad_id = request.query_params.get('squad_id')

            # ✅ LAZY RESET: Ensure user and their squads have missions
            MissionResetService.ensure_user_has_todays_missions(user)
            MissionResetService.ensure_user_has_weekly_missions(user)

            # Get today's date and Monday of current week IN USER'S TIMEZONE
            today = get_user_current_date(user)
            monday = today - timedelta(days=today.weekday())

            # Get user's squads
            user_squads = SquadMember.objects.filter(
                user=user
            ).select_related('squad').values_list('squad_id', flat=True)

            if not user_squads:
                return Response({
                    'success': True,
                    'message': 'User is not a member of any squad',
                    'squads': [],
                    'total_missions': 0,
                    'completed_missions': 0,
                    'in_progress_missions': 0
                }, status=status.HTTP_200_OK)

            # ✅ LAZY RESET: Ensure all squads have missions
            user_squad_memberships = SquadMember.objects.filter(
                user=user
            ).select_related('squad')

            for membership in user_squad_memberships:
                SquadMissionService.ensure_squad_has_missions(
                    squad=membership.squad,
                    cycle_date=today,
                    cycle_type='daily'
                )
                SquadMissionService.ensure_squad_has_missions(
                    squad=membership.squad,
                    cycle_date=monday,
                    cycle_type='weekly'
                )

            # Base queryset for current cycle squad missions (ALL, not just current cycle)
            base_queryset = SquadMissionProgress.objects.filter(
                squad_id__in=user_squads
            ).filter(
                Q(cycle_date=today, mission__cycle='daily') |
                Q(cycle_date=monday, mission__cycle='weekly')
            )

            # Filter by specific squad if provided
            if squad_id:
                base_queryset = base_queryset.filter(squad_id=squad_id)

            # Calculate statistics BEFORE filtering by status
            stats = base_queryset.aggregate(
                total=Count('id'),
                completed=Count('id', filter=Q(is_completed=True)),
                in_progress=Count('id', filter=Q(is_completed=False))
            )

            # Apply filters
            queryset = base_queryset.select_related(
                'mission', 'squad'
            ).prefetch_related(
                'mission__rewards__currency',
                'squad__memberships__user'
            )

            # Filter by cycle
            if cycle:
                queryset = queryset.filter(mission__cycle=cycle)

            # ✅ FIXED: Filter by status - now includes completed by default
            if status_filter == 'active':
                queryset = queryset.filter(is_completed=False)
            elif status_filter == 'completed':
                queryset = queryset.filter(is_completed=True)
            # 'all' returns everything (no filter)

            # ✅ FIXED: Order to show completed missions too
            queryset = queryset.order_by('-is_completed', '-created_at')  # Completed first

            # Group by squad
            squads_data = []
            squads_dict = {}

            for squad_mission in queryset:
                squad_id_str = str(squad_mission.squad.id)

                if squad_id_str not in squads_dict:
                    squads_dict[squad_id_str] = {
                        'squad_id': squad_id_str,
                        'squad_name': squad_mission.squad.name,
                        'squad_avatar': request.build_absolute_uri(
                            squad_mission.squad.avatar.url) if squad_mission.squad.avatar else None,
                        'total_members': squad_mission.squad.memberships.count(),
                        'missions': []
                    }

                squads_dict[squad_id_str]['missions'].append(squad_mission)

            # Serialize missions for each squad
            for squad_data in squads_dict.values():
                serialized_missions = SquadMissionProgressSerializer(
                    squad_data['missions'],
                    many=True,
                    context={'request': request}
                ).data
                squad_data['missions'] = serialized_missions
                squads_data.append(squad_data)

            return Response({
                'success': True,
                'total_missions': stats['total'],
                'completed_missions': stats['completed'],
                'in_progress_missions': stats['in_progress'],
                'squads': squads_data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching squad missions: {str(e)}", exc_info=True)
            return Response(
                {'success': False, 'error': 'Failed to fetch squad missions'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )