# gamification/views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta

from .models import UserMission
from .serializers import UserMissionSerializer
from .services.reset_services import MissionResetService  # ✅ Import the service
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