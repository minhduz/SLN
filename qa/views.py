from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.conf import settings
import logging
from django.db import transaction

from django.utils import timezone

from .models import Question, Subject
from .tasks import generate_question_embedding

from .services.chatbot_agent import get_chatbot


from .services.vector_search_service import VectorSearchService
from .serializers import (
    VectorSearchRequestSerializer,
    VectorSearchResponseSerializer,
    CreateQuestionSerializer,
    ChatWithBotRequestSerializer, ChatWithBotResponseSerializer,
    GetConversationStatusRequestSerializer, DiscardConversationRequestSerializer,
    ClearConversationRequestSerializer, ClearConversationResponseSerializer,
    SaveConversationRequestSerializer, SaveConversationResponseSerializer, DiscardConversationResponseSerializer
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


class ChatWithBotView(APIView):
    """
    API endpoint to chat with the Smart Learning System chatbot with file upload support

    POST /api/chat/
    Content-Type: multipart/form-data

    Form fields:
    - message: "What is photosynthesis?"
    - thread_id: "optional-thread-id"
    - files: [file1, file2, ...] (optional, max 5 files)

    Returns token information and attachment info for frontend
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Use request.data for form data instead of JSON
            serializer = ChatWithBotRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            message = serializer.validated_data['message'].strip()
            thread_id = serializer.validated_data.get(
                'thread_id',
                f"user_{request.user.id}_default"
            )
            uploaded_files = serializer.validated_data.get('files', [])

            # Process file attachments
            file_attachments = []
            if uploaded_files:
                chatbot = get_chatbot()

                for uploaded_file in uploaded_files:
                    try:
                        # Read file data
                        file_data = uploaded_file.read()

                        # Create file attachment
                        attachment = chatbot.create_file_attachment(
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

            # Get chatbot and send message
            if not file_attachments:  # Only get chatbot if not already retrieved above
                chatbot = get_chatbot()

            result = chatbot.chat(
                message=message,
                user_id=str(request.user.id),
                thread_id=thread_id,
                file_attachments=file_attachments
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


class ClearConversationView(APIView):  # Fixed typo in class name
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        serializer = ClearConversationRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        thread_id = serializer.validated_data["thread_id"]

        try:
            chatbot = get_chatbot()
            result = chatbot.clear_conversation(thread_id=thread_id)

            response_serializer = ClearConversationResponseSerializer(result)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in ClearConversationView: {str(e)}")
            return Response(
                {"error": "Failed to clear conversation", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SaveConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SaveConversationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        thread_id = serializer.validated_data["thread_id"]

        try:
            chatbot = get_chatbot()
            # Use save_conversation instead of create_conversation_summary for file handling
            result = chatbot.save_conversation(
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


class DiscardConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        thread_id = request.query_params.get("thread_id")
        if not thread_id:
            return Response({"error": "thread_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            chatbot = get_chatbot()
            result = chatbot.delete_conversation_attachments(thread_id=thread_id)

            response_serializer = DiscardConversationResponseSerializer(result)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in DiscardConversationView: {str(e)}")
            return Response(
                {"error": "Failed to discard conversation", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
