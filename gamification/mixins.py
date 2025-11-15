# gamification/mixins.py
from gamification.services.tracking_services import MissionService
import logging

logger = logging.getLogger(__name__)


class MissionTrackingMixin:
    """
    Mixin to automatically track missions after successful API actions

    Usage:
        class MyAPIView(MissionTrackingMixin, APIView):
            mission_type = 'answer_question'

            def post(self, request):
                # Your logic here
                response_data = {...}

                # Set context for mission tracking
                self.mission_context = {
                    'question_id': str(question_id),
                    'question_owner_id': str(question.user.id)
                }

                return Response(response_data)
    """

    mission_type = None
    mission_context = None

    def finalize_response(self, request, response, *args, **kwargs):
        """
        Called after the response is created but before it's returned
        Perfect place to track missions
        """
        response = super().finalize_response(request, response, *args, **kwargs)

        # Only track on successful responses
        if (
                self.mission_type and
                hasattr(request, 'user') and
                request.user.is_authenticated and
                200 <= response.status_code < 300
        ):
            try:
                context = getattr(self, 'mission_context', {}) or {}
                MissionService.track_mission_progress(
                    user=request.user,
                    mission_type=self.mission_type,
                    context_data=context
                )
            except Exception as e:
                logger.error(f"Error tracking mission {self.mission_type}: {str(e)}")

        return response