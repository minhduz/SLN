from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
import logging
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q

from .models import Subject, Question, Answer, QuestionFileAttachment, UserQuestionView
from .tasks import generate_question_embedding
from economy.services.pricing_service import PricingService

from .services.chatbot_agent import get_chatbot
from .services.chatbot_utils import (
    chat as chatbot_chat,
    save_conversation as chatbot_save_conversation,
    cleanup_conversation as chatbot_cleanup_conversation,
    create_file_attachment
)
from .services.question_service import get_random_questions_for_user, get_random_questions_by_subject
from .services.vector_search_service import VectorSearchService

from .serializers import (
    VectorSearchRequestSerializer,
    VectorSearchResponseSerializer,
    CreateQuestionSerializer,
    ChatWithBotRequestSerializer, ChatWithBotResponseSerializer,
    GetConversationStatusRequestSerializer,
    ClearConversationRequestSerializer, ClearConversationResponseSerializer,
    SaveConversationRequestSerializer, SaveConversationResponseSerializer,
    QuestionSerializer, AnswerSerializer,
    QuestionListSerializer, UserQuestionViewSerializer,
    UserQuestionMinimalSerializer, SubjectSerializer,
)

logger = logging.getLogger(__name__)

class SimilarQuestionsView(APIView):
    """
    API endpoint for Phase 1: Vector similarity search for similar questions

    This implements steps 0.1-0.3 from the flow diagram:
    - 0.1: User asks question
    - 0.2: Search in DB using cosine similarity on embeddings
    - 0.3: Return list of 5-10 most relevant questions

    POST /api/qa/phase1/similar-questions/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Search for similar questions based on vector similarity

        Request Body (JSON):
        - q (required): Question text to search for
        - limit (optional): Max results to return (1-50, default: 10)
        - min_similarity (optional): Min similarity threshold (0.0-1.0, default: 0.7)
        - include_private (optional): Include private questions (default: false)
        """
        # Validate request body
        serializer = VectorSearchRequestSerializer(data=request.data)

        if not serializer.is_valid():
            logger.warning(f"Invalid search request: {serializer.errors}")
            return Response(
                {
                    'success': False,
                    'error': 'Invalid parameters',
                    'details': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data
        query_text = validated_data['q']

        logger.info(f"Vector search request by user {request.user.id}: '{query_text[:50]}...'")

        try:
            # Initialize vector search service
            vector_service = VectorSearchService()

            # Perform the search (cosine similarity only)
            search_result = vector_service.search_similar_questions(
                query_text=query_text,
                limit=validated_data['limit'],
                min_similarity=validated_data['min_similarity'],
                include_private=validated_data['include_private'],
                user_id=request.user.id,
            )

            # Serialize and return response
            response_serializer = VectorSearchResponseSerializer(data=search_result)

            if response_serializer.is_valid():
                logger.info(f"Search completed successfully: {search_result['count']} results")
                return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
            else:
                logger.error(f"Response serialization failed: {response_serializer.errors}")
                return Response(
                    {
                        'success': False,
                        'error': 'Response serialization failed',
                        'details': response_serializer.errors
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            logger.error(f"Vector search failed for user {request.user.id}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'error': 'Search operation failed',
                    'message': str(e) if settings.DEBUG else 'Internal server error'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class VectorSearchStatsView(APIView):
    """
    API endpoint to get statistics about the vector search database

    GET /api/qa/phase1/stats/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get vector search statistics"""
        try:
            from .models import Question

            total_questions = Question.objects.count()
            questions_with_embeddings = Question.objects.filter(
                embedding__isnull=False
            ).count()
            public_questions = Question.objects.filter(
                is_public=True,
                embedding__isnull=False
            ).count()

            user_questions = Question.objects.filter(
                user=request.user,
                embedding__isnull=False
            ).count()

            stats = {
                'total_questions': total_questions,
                'questions_with_embeddings': questions_with_embeddings,
                'public_searchable_questions': public_questions,
                'user_questions_count': user_questions,
                'embedding_coverage': round(
                    (questions_with_embeddings / total_questions * 100) if total_questions > 0 else 0,
                    2
                )
            }

            return Response(stats, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Failed to get vector search stats: {e}")
            return Response(
                {'error': 'Failed to retrieve statistics'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ChatWithBotView(APIView):
    permission_classes = [IsAuthenticated]
    CHAT_COST_CURRENCY = "diamond"
    CHAT_COST_AMOUNT = 2

    def post(self, request):
        try:
            # Check if user has sufficient diamonds
            if not PricingService.has_sufficient_currency(request.user, self.CHAT_COST_CURRENCY, self.CHAT_COST_AMOUNT):
                remaining = PricingService.get_user_balance(request.user, self.CHAT_COST_CURRENCY)
                return Response(
                    {
                        "error": f"Insufficient {self.CHAT_COST_CURRENCY}",
                        "required": self.CHAT_COST_AMOUNT,
                        "available": remaining
                    },
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )

            # Use request.data for form data instead of JSON
            serializer = ChatWithBotRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            message = serializer.validated_data['message'].strip()
            thread_id = serializer.validated_data.get(
                'thread_id',
                f"user_{request.user.id}_default"
            )
            uploaded_files = serializer.validated_data.get('files', [])

            # Process file attachments using the utility function
            file_attachments = []
            if uploaded_files:
                for uploaded_file in uploaded_files:
                    try:
                        # Read file data
                        file_data = uploaded_file.read()

                        # Create file attachment using utility function
                        attachment = create_file_attachment(
                            file_data=file_data,
                            filename=uploaded_file.name,
                            content_type=uploaded_file.content_type
                        )
                        file_attachments.append(attachment)

                    except Exception as e:
                        logger.error(f"Error processing file {uploaded_file.name}: {str(e)}")
                        return Response(
                            {
                                "error": f"Error processing file {uploaded_file.name}",
                                "details": str(e)
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

            # Get chatbot and send message using utility function
            chatbot = get_chatbot()
            result = chatbot_chat(
                chatbot_instance=chatbot,
                message=message,
                user_id=str(request.user.id),
                thread_id=thread_id,
                file_attachments=file_attachments
            )

            # Deduct currency after successful chat
            deduct_result = PricingService.deduct_currency(
                request.user,
                self.CHAT_COST_CURRENCY,
                self.CHAT_COST_AMOUNT
            )

            response_data = {
                "message": message,
                "response": result["response"],
                "thread_id": thread_id,
                "status": result["status"],
                "token_info": result["token_info"],
                "timestamp": timezone.now(),
                "current_subject": result.get("current_subject"),
                "subject_change_detected": result.get("subject_change_detected"),
                "suggested_new_subject": result.get("suggested_new_subject"),
                "attachments": result.get("attachments", []),
            }

            if result["status"] == "conversation_too_long":
                response_data["action_required"] = "start_new_chat"

            response_serializer = ChatWithBotResponseSerializer(response_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in ChatWithBotView: {str(e)}")
            return Response(
                {"error": "An error occurred", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class GetConversationStatusView(APIView):
    """
    GET /api/chat/status/
    Get the current status of a conversation thread
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = GetConversationStatusRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        thread_id = serializer.validated_data["thread_id"]

        try:
            chatbot = get_chatbot()
            result = chatbot.get_conversation_state(thread_id=thread_id)

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in GetConversationStatusView: {str(e)}")
            return Response(
                {"error": "Failed to get conversation state", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SaveConversationView(APIView):
    """
    POST /api/chat/save/
    Save a conversation to the database with all attachments
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SaveConversationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        thread_id = serializer.validated_data["thread_id"]

        try:
            chatbot = get_chatbot()
            # Use the utility function for saving conversation
            result = chatbot_save_conversation(
                chatbot_instance=chatbot,
                thread_id=thread_id,
                user_id=str(request.user.id)
            )

            response_serializer = SaveConversationResponseSerializer(result)

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in SaveConversationView: {str(e)}")
            return Response(
                {"error": "Failed to save conversation", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ClearConversationView(APIView):
    """
    DELETE /api/chat/clear/
    Delete a conversation thread entirely:
    - Cleans up attachments
    - Clears all messages
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        # Validate input
        serializer = ClearConversationRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        thread_id = serializer.validated_data["thread_id"]

        try:
            chatbot = get_chatbot()
            # Use the utility function for cleanup
            result = chatbot_cleanup_conversation(
                chatbot_instance=chatbot,
                thread_id=thread_id
            )

            # Serialize response
            response_serializer = ClearConversationResponseSerializer(result)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in ClearConversationView: {str(e)}")
            return Response(
                {
                    "error": "Failed to cleanup conversation",
                    "details": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

# ============================================================================
# ANSWER CRUD OPERATIONS
# ============================================================================

class AnswerListCreateView(APIView):
    """
    GET /api/qa/answers/?question_id=<uuid> - List answers for a question
    POST /api/qa/answers/ - Create a new answer
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List answers for a specific question"""
        question_id = request.query_params.get('question_id')

        if not question_id:
            return Response(
                {'error': 'question_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            question = get_object_or_404(Question, id=question_id)
            answers = Answer.objects.filter(question=question).order_by('-created_at')
            serializer = AnswerSerializer(answers, many=True, context={'request': request})

            return Response({
                'count': answers.count(),
                'results': serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error listing answers: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve answers'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        """Create a new answer"""
        question_id = request.data.get('question_id')
        content = request.data.get('content')

        if not question_id or not content:
            return Response(
                {'error': 'question_id and content are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            question = get_object_or_404(Question, id=question_id)

            # Validate content length
            if len(content.strip()) < 10:
                return Response(
                    {'error': 'Answer content must be at least 10 characters long'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create answer
            answer = Answer.objects.create(
                question=question,
                user=request.user,
                content=content.strip(),
                is_ai_generated=False
            )

            serializer = AnswerSerializer(answer, context={'request': request})

            logger.info(f"Answer {answer.id} created by user {request.user.id} for question {question_id}")

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating answer: {str(e)}")
            return Response(
                {'error': 'Failed to create answer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class AnswerDetailView(APIView):
    """
    GET /api/qa/answers/<uuid>/ - Retrieve a specific answer
    PUT /api/qa/answers/<uuid>/ - Update an answer
    DELETE /api/qa/answers/<uuid>/ - Delete an answer
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Retrieve a specific answer"""
        try:
            answer_id = request.query_params.get('answer_id')
            answer = get_object_or_404(Answer, id=answer_id)
            serializer = AnswerSerializer(answer, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error retrieving answer: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve answer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def put(self, request):
        """Update an answer (only by owner)"""
        try:
            answer_id = request.query_params.get('answer_id')
            answer = get_object_or_404(Answer, id=answer_id)

            # Only the answer owner can update
            if answer.user != request.user:
                return Response(
                    {'error': 'Permission denied. Only the answer owner can update it.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            content = request.data.get('content')
            if not content:
                return Response(
                    {'error': 'content is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate content length
            if len(content.strip()) < 10:
                return Response(
                    {'error': 'Answer content must be at least 10 characters long'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            answer.content = content.strip()
            answer.save()

            serializer = AnswerSerializer(answer, context={'request': request})

            logger.info(f"Answer {answer_id} updated by user {request.user.id}")

            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error updating answer: {str(e)}")
            return Response(
                {'error': 'Failed to update answer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request):
        """Delete an answer (only by owner or question owner)"""
        try:
            answer_id = request.query_params.get('answer_id')
            answer = get_object_or_404(Answer, id=answer_id)

            # Only the answer owner or question owner can delete
            if answer.user != request.user and answer.question.user != request.user:
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            answer.delete()

            logger.info(f"Answer {answer_id} deleted by user {request.user.id}")

            return Response(
                {'message': 'Answer deleted successfully'},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error deleting answer: {str(e)}")
            return Response(
                {'error': 'Failed to delete answer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class VerifyAnswerView(APIView):
    """
    POST /api/qa/questions/<question_id>/verify-answer/
    Mark an answer as verified (only by question owner)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Verify an answer for a question

        Request body:
        {
            "answer_id": "uuid-of-answer"
        }
        """
        try:
            question_id = request.query_params.get('question_id')
            question = get_object_or_404(Question, id=question_id)

            # Only question owner can verify answers
            if question.user != request.user:
                return Response(
                    {'error': 'Only the question owner can verify answers'},
                    status=status.HTTP_403_FORBIDDEN
                )

            answer_id = request.data.get('answer_id')
            if not answer_id:
                return Response(
                    {'error': 'answer_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            answer = get_object_or_404(Answer, id=answer_id)

            # Verify answer belongs to this question
            if answer.question != question:
                return Response(
                    {'error': 'Answer does not belong to this question'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Set verified answer
            question.verified_answer = answer
            question.save()

            logger.info(f"Answer {answer_id} verified for question {question_id} by user {request.user.id}")

            return Response({
                'success': True,
                'message': 'Answer verified successfully',
                'verified_answer_id': str(answer.id)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error verifying answer: {str(e)}")
            return Response(
                {'error': 'Failed to verify answer', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DisproveAnswerView(APIView):
    """
    DELETE /api/qa/questions/<question_id>/verify-answer/
    Remove verified status from question
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        """Remove verified answer from question"""
        try:
            question_id = request.query_params.get('question_id')
            question = get_object_or_404(Question, id=question_id)

            # Only question owner can disprove
            if question.user != request.user:
                return Response(
                    {'error': 'Only the question owner can disprove answers'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not question.verified_answer:
                return Response(
                    {'error': 'No verified answer to remove'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            question.verified_answer = None
            question.save()

            logger.info(f"Verified answer removed from question {question_id} by user {request.user.id}")

            return Response({
                'success': True,
                'message': 'Verified answer removed successfully'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error disproving answer: {str(e)}")
            return Response(
                {'error': 'Failed to disprove answer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class RandomQuestionsView(APIView):
    """
    GET /api/qa/questions/random/
    Get random public questions with popularity-based distribution

    Query Parameters:
    - page (int): Page number (default: 1)
    - page_size (int): Number of questions per page (default: 10, max: 50)

    Returns paginated random questions with:
    - 30% from high popularity questions
    - 30% from medium popularity questions
    - 40% from low popularity questions
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Get pagination parameters
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 10))

            # Validate pagination parameters
            page = max(page, 1)  # Minimum page 1
            page_size = min(max(page_size, 1), 50)  # Constrain 1-50

            # Get random questions with popularity distribution
            questions = get_random_questions_for_user(
                user_id=request.user.id,
                page=page,
                page_size=page_size
            )

            # Serialize the questions
            serializer = QuestionListSerializer(
                questions, many=True, context={"request": request}
            )

            return Response(
                {
                    "page": page,
                    "page_size": page_size,
                    "count": len(serializer.data),
                    "results": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except ValueError as e:
            logger.error(f"Invalid pagination parameters: {str(e)}")
            return Response(
                {"error": "Invalid pagination parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Error fetching random questions: {str(e)}", exc_info=True)
            return Response(
                {"error": "Failed to fetch random questions"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class QuestionsBySubjectView(APIView):
    """
    GET /api/qa/questions/by-subject/?subject_id=<uuid>&page=1&page_size=10
    Get random public questions by subject with pagination (excluding user's own questions)

    Query Parameters:
    - subject_id (uuid): The subject ID to filter questions
    - page (int): Page number (default: 1)
    - page_size (int): Number of questions per page (default: 10, max: 50)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            subject_id = request.query_params.get('subject_id')
            if not subject_id:
                return Response(
                    {'error': 'subject_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            subject = get_object_or_404(Subject, id=subject_id)

            # Get pagination parameters
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 10))

            # Validate pagination parameters
            page = max(page, 1)  # Minimum page 1
            page_size = min(max(page_size, 1), 50)  # Constrain 1-50

            # Pass authenticated user_id to exclude their own questions
            user_id = request.user.id
            questions = get_random_questions_by_subject(
                subject_id=subject.id,
                user_id=user_id,
                page=page,
                page_size=page_size
            )

            serializer = QuestionListSerializer(
                questions,
                many=True,
                context={'request': request}
            )

            return Response({
                'subject': {
                    'id': str(subject.id),
                    'name': subject.name,
                    'description': subject.description
                },
                'page': page,
                'page_size': page_size,
                'count': len(serializer.data),
                'results': serializer.data
            }, status=status.HTTP_200_OK)

        except ValueError as e:
            logger.error(f"Invalid pagination parameters: {str(e)}")
            return Response(
                {'error': 'Invalid pagination parameters'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error fetching random questions by subject: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to fetch questions by subject'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class QuestionView(APIView):
    """
    GET /api/qa/question/
    Get detailed information about a question
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get question details"""
        try:
            question_id = request.query_params.get('question_id')
            question = get_object_or_404(Question, id=question_id)

            # Check permissions - public or owner
            if not question.is_public and question.user != request.user:
                return Response(
                    {'error': 'Permission denied. This question is private.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            serializer = QuestionSerializer(question, context={'request': request})

            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching question detail: {str(e)}")
            return Response(
                {'error': 'Failed to fetch question details'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    """
    DELETE /api/qa/question/
    Delete question
    """
    def delete(self, request):
        """
        Delete question, answers, and attachments
        Uses django-storages for S3 file cleanup
        """
        try:
            question_id = request.query_params.get('question_id')
            question = get_object_or_404(Question, id=question_id)

            # Only question owner can delete
            if question.user != request.user:
                return Response(
                    {'error': 'Only the question owner can delete this question'},
                    status=status.HTTP_403_FORBIDDEN
                )

            with transaction.atomic():
                # Get counts before deletion
                answer_count = question.answers.count()
                attachment_count = question.attachments.count()

                # Get all attachments for S3 cleanup
                attachments = list(question.attachments.all())

                # Delete files from S3 using django-storages
                deleted_files = []
                failed_files = []

                for attachment in attachments:
                    if attachment.file:
                        try:
                            # django-storages handles S3 deletion automatically
                            attachment.file.delete(save=False)
                            deleted_files.append(attachment.file.name)
                            logger.info(f"Deleted S3 file: {attachment.file.name}")
                        except Exception as e:
                            logger.error(f"Failed to delete S3 file {attachment.file.name}: {str(e)}")
                            failed_files.append(attachment.file.name)

                # Delete the question (CASCADE will delete answers and attachments)
                question.delete()

                logger.info(
                    f"Question {question_id} deleted by user {request.user.id}. "
                    f"Removed {answer_count} answers and {attachment_count} attachments"
                )

                return Response({
                    'success': True,
                    'message': 'Question deleted successfully',
                    'deleted_answers': answer_count,
                    'deleted_attachments': attachment_count,
                    'deleted_s3_files': len(deleted_files),
                    'failed_s3_files': len(failed_files)
                }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error deleting question: {str(e)}")
            return Response(
                {'error': 'Failed to delete question', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class QuestionVisibilityView(APIView):
    """
    PATCH /api/qa/questions/visibility/
    Toggle question visibility (public/private) - only by owner
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        """
        Update question visibility

        Request body:
        {
            "is_public": true/false
        }
        """
        try:
            question_id = request.query_params.get('question_id')
            question = get_object_or_404(Question, id=question_id)

            # Only question owner can change visibility
            if question.user != request.user:
                return Response(
                    {'error': 'Only the question owner can change visibility'},
                    status=status.HTTP_403_FORBIDDEN
                )

            is_public = request.data.get('is_public')
            if is_public is None:
                return Response(
                    {'error': 'is_public field is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            question.is_public = bool(is_public)
            question.save()

            logger.info(
                f"Question {question_id} visibility changed to "
                f"{'public' if is_public else 'private'} by user {request.user.id}"
            )

            return Response({
                'success': True,
                'message': f"Question is now {'public' if is_public else 'private'}",
                'is_public': question.is_public
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error updating question visibility: {str(e)}")
            return Response(
                {'error': 'Failed to update question visibility'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UserQuestionsListView(APIView):
    """
    GET /api/qa/user/questions/
    Get all questions created by the authenticated user
    Returns only id, title, body, and attachments
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Get all user's questions, newest first
            questions = Question.objects.filter(
                user=request.user
            ).prefetch_related('attachments').order_by('-created_at')

            # Serialize
            serializer = UserQuestionMinimalSerializer(
                questions,
                many=True,
                context={'request': request}
            )

            return Response({
                'success': True,
                'count': len(serializer.data),
                'results': serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching user questions: {str(e)}")
            return Response(
                {'error': 'Failed to fetch user questions'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UserQuestionViewAPI(generics.GenericAPIView):
    """API to record when a user views a question (no duplicates)."""
    permission_classes = [IsAuthenticated]
    serializer_class = UserQuestionViewSerializer

    def post(self, request):
        user = request.user
        question_id = request.data.get('question_id')

        try:
            # ✅ Allow viewing if question is public OR user is the owner
            question = Question.objects.get(
                Q(is_public=True) | Q(user=user),
                id=question_id
            )
        except Question.DoesNotExist:
            return Response(
                {"detail": "Question not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Create or get existing view
        view_obj, created = UserQuestionView.objects.get_or_create(
            user=user, question=question
        )

        # Return the question with updated view_count
        question_data = QuestionListSerializer(
            question,
            context={'request': request}
        ).data
        return Response(question_data, status=status.HTTP_200_OK)

class SubjectListView(APIView):
    """
    GET /api/qa/subjects/
    Get all available subjects
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all subjects with their question counts"""
        try:
            subjects = Subject.objects.all().order_by('name')

            serializer = SubjectSerializer(subjects, many=True)

            logger.info(f"Retrieved {len(serializer.data)} subjects for user {request.user.id}")

            return Response({
                'success': True,
                'count': len(serializer.data),
                'results': serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching subjects: {str(e)}")
            return Response(
                {'error': 'Failed to fetch subjects'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SearchSubjectsView(APIView):
    """
    GET /api/qa/subjects/search/?q=<query>
    Search subjects by name or description (case-insensitive contains)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Search subjects using contains query"""
        try:
            query = request.query_params.get('q', '').strip()

            if not query:
                return Response(
                    {'error': 'Query parameter "q" is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if len(query) < 2:
                return Response(
                    {'error': 'Query must be at least 2 characters long'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Search in both name and description using case-insensitive contains
            subjects = Subject.objects.filter(
                Q(name__icontains=query)
            ).order_by('name')

            serializer = SubjectSerializer(subjects, many=True)

            logger.info(
                f"Subject search by user {request.user.id}: '{query}' "
                f"- {len(serializer.data)} results"
            )

            return Response({
                'success': True,
                'query': query,
                'count': len(serializer.data),
                'results': serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error searching subjects: {str(e)}")
            return Response(
                {'error': 'Failed to search subjects'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )





































class TempCreateQuestionView(APIView):
    """
    Temporary API endpoint for creating questions with async embedding generation

    This is for testing the vector search process.
    The embedding generation happens asynchronously via Celery.

    POST /api/qa/temp/create-question/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Create a new question and trigger async embedding generation

        Request body:
        {
            "title": "Question title",
            "body": "Question body text",
            "subject_id": "uuid-of-subject" (optional),
            "is_public": true/false (optional, defaults to true)
        }
        """
        serializer = CreateQuestionSerializer(data=request.data)

        if not serializer.is_valid():
            logger.warning(f"Invalid question creation request: {serializer.errors}")
            return Response(
                {
                    'success': False,
                    'error': 'Invalid data',
                    'details': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        try:
            with transaction.atomic():
                # Get subject if provided
                subject = None
                if validated_data.get('subject_id'):
                    try:
                        subject = Subject.objects.get(id=validated_data['subject_id'])
                    except Subject.DoesNotExist:
                        return Response(
                            {
                                'success': False,
                                'error': 'Subject not found'
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                # Create the question (without embedding initially)
                question = Question.objects.create(
                    title=validated_data['title'],
                    body=validated_data['body'],
                    subject=subject,
                    user=request.user,
                    is_public=validated_data.get('is_public', True),
                    embedding=None  # Will be set by the Celery task
                )

                logger.info(f"Created question {question.id} by user {request.user.id}")

                # Trigger async embedding generation
                task = generate_question_embedding.delay(str(question.id))

                logger.info(f"Started embedding generation task {task.id} for question {question.id}")

                # Prepare response data
                question_data = {
                    'id': str(question.id),
                    'title': question.title,
                    'body': question.body,
                    'subject': {
                        'id': str(subject.id),
                        'name': subject.name
                    } if subject else None,
                    'user': request.user.username,
                    'is_public': question.is_public,
                    'created_at': question.created_at,
                    'has_embedding': False,  # Will be False initially
                    'popularity_score': question.popularity_score
                }

                response_data = {
                    'success': True,
                    'question': question_data,
                    'message': 'Question created successfully. Embedding generation started.',
                    'embedding_task_id': task.id
                }

                return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Failed to create question for user {request.user.id}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'error': 'Failed to create question',
                    'message': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class TempQuestionStatusView(APIView):
    """
    Check the status of a question's embedding generation

    GET /api/qa/temp/question-status/<question_id>/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, question_id):
        """Check if a question's embedding has been generated"""
        try:
            question = Question.objects.get(id=question_id)

            # Check if user has permission to view this question
            if not question.is_public and question.user != request.user:
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            has_embedding = question.embedding is not None

            response_data = {
                'question_id': str(question.id),
                'title': question.title,
                'has_embedding': has_embedding,
                'embedding_status': 'completed' if has_embedding else 'pending',
                'created_at': question.created_at
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Question.DoesNotExist:
            return Response(
                {'error': 'Question not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error checking question status: {e}")
            return Response(
                {'error': 'Failed to check question status'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class TempBulkCreateQuestionsView(APIView):
    """
    Create multiple questions at once for testing

    POST /api/qa/temp/bulk-create-questions/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Create multiple questions for testing purposes

        Request body:
        {
            "questions": [
                {
                    "title": "Question 1",
                    "body": "Body 1",
                    "subject_id": "uuid" (optional),
                    "is_public": true (optional)
                },
                ...
            ]
        }
        """
        questions_data = request.data.get('questions', [])

        if not questions_data or len(questions_data) == 0:
            return Response(
                {'error': 'No questions provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(questions_data) > 20:  # Limit bulk creation
            return Response(
                {'error': 'Maximum 20 questions allowed per bulk request'},
                status=status.HTTP_400_BAD_REQUEST
            )

        created_questions = []
        failed_questions = []
        task_ids = []

        for i, question_data in enumerate(questions_data):
            try:
                serializer = CreateQuestionSerializer(data=question_data)

                if not serializer.is_valid():
                    failed_questions.append({
                        'index': i,
                        'data': question_data,
                        'errors': serializer.errors
                    })
                    continue

                validated_data = serializer.validated_data

                # Get subject if provided
                subject = None
                if validated_data.get('subject_id'):
                    try:
                        subject = Subject.objects.get(id=validated_data['subject_id'])
                    except Subject.DoesNotExist:
                        failed_questions.append({
                            'index': i,
                            'data': question_data,
                            'errors': {'subject_id': 'Subject not found'}
                        })
                        continue

                # Create question
                question = Question.objects.create(
                    title=validated_data['title'],
                    body=validated_data['body'],
                    subject=subject,
                    user=request.user,
                    is_public=validated_data.get('is_public', True),
                    embedding=None
                )

                # Start embedding generation
                task = generate_question_embedding.delay(str(question.id))
                task_ids.append(task.id)

                created_questions.append({
                    'id': str(question.id),
                    'title': question.title,
                    'embedding_task_id': task.id
                })

            except Exception as e:
                failed_questions.append({
                    'index': i,
                    'data': question_data,
                    'errors': {'general': str(e)}
                })

        return Response(
            {
                'success': True,
                'created_count': len(created_questions),
                'failed_count': len(failed_questions),
                'created_questions': created_questions,
                'failed_questions': failed_questions,
                'embedding_task_ids': task_ids
            },
            status=status.HTTP_201_CREATED if created_questions else status.HTTP_400_BAD_REQUEST
        )