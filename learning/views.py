# learning/views.py
from rest_framework.views import APIView
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.conf import settings
import logging
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .tasks import recalculate_quiz_rating
from gamification.mixins import MissionTrackingMixin
from economy.services.pricing_service import PricingService

from .models import Quiz, QuizQuestion, QuizAnswerOption, QuizAttempt, QuizAttemptAnswer
from .serializers import (
    QuizSerializer,
    QuizListSerializer,
    GenerateAIQuizSerializer,
    SaveGeneratedQuizSerializer,
    QuizQuestionSerializer,
    SubmitQuizSerializer,
    QuizAttemptSerializer,
    QuizAttemptDetailSerializer,
    UserQuizAttemptsSerializer,
    CreateQuizSerializer,
    AddManualQuestionsSerializer,
    ImportQuestionsFromExcelSerializer,
    QuizDetailPreviewSerializer,
    UserQuizDetailSerializer,
    UnifiedEditQuizSerializer,
    QuizAttemptWithRatingSerializer,
    RateQuizSerializer
)
from .service.quiz_service import AIQuizGenerator
from .service.submit_service import QuizSubmitService
from .service.file_service import ExcelQuizImporter
from .service.random_quiz_service import get_random_quizzes_for_user,get_random_quizzes_by_subject
from qa.models import Subject

import tempfile
import os

logger = logging.getLogger(__name__)

# ===================== OWNERSHIP PERMISSION MIXIN =====================

class QuizOwnershipMixin:
    """
    Mixin to check if the current user is the owner of the quiz.
    Ensures only the quiz creator can edit/delete it.
    """

    def get_quiz_owner(self):
        """Get the quiz object - override in subclass if using different lookup"""
        quiz_id = self.kwargs.get('quiz_id')
        return get_object_or_404(Quiz, id=quiz_id)

    def check_quiz_ownership(self, quiz, user):
        """Check if user is the owner of the quiz"""
        # Try to get the user from quiz.created_by if your model has this field
        # Option 1: If Quiz has a 'created_by' field:
        # if hasattr(quiz, 'created_by') and quiz.created_by != user:
        #     return False

        # Option 2: Use quiz attempts to verify user involvement
        # This is a workaround if you don't have created_by field
        # For now, we'll assume you want to add created_by to Quiz model

        # Check if quiz has created_by field
        if hasattr(quiz, 'created_by'):
            return quiz.created_by == user

        # If no created_by field, use quiz.user if it exists
        if hasattr(quiz, 'user'):
            return quiz.user == user

        # Fallback: deny access (safer option)
        return False

    def check_permission_or_403(self, quiz, request):
        """Check ownership and return 403 if not owner"""
        if not self.check_quiz_ownership(quiz, request.user):
            return Response(
                {
                    "success": False,
                    "error": "You don't have permission to modify this quiz. Only the quiz creator can edit or delete it."
                },
                status=status.HTTP_403_FORBIDDEN
            )
        return None

class GenerateAIQuizView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = GenerateAIQuizSerializer

    QUIZ_GENERATION_COST = 5
    COST_CURRENCY = "diamond"

    def create(self, request, *args, **kwargs):
        """Generate AI quiz without saving to database"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # ✅ Check if user has sufficient diamonds
            if not PricingService.has_sufficient_currency(
                    request.user,
                    self.COST_CURRENCY,
                    self.QUIZ_GENERATION_COST
            ):
                remaining_balance = PricingService.get_user_balance(
                    request.user,
                    self.COST_CURRENCY
                )
                return Response(
                    {
                        "success": False,
                        "error": f"Insufficient {self.COST_CURRENCY}",
                        "required": self.QUIZ_GENERATION_COST,
                        "available": remaining_balance
                    },
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )

            subject_id = serializer.validated_data.get('subject_id')
            num_questions = serializer.validated_data.get('num_questions', 10)
            language = serializer.validated_data.get('language', 'English')
            custom_description = serializer.validated_data.get('description')
            options_per_question = serializer.validated_data.get('options_per_question', 4)
            correct_answers_per_question = serializer.validated_data.get('correct_answers_per_question', 1)

            # Get subject
            if subject_id:
                subject = Subject.objects.get(id=subject_id)
            else:
                subject = None  # Will be randomly selected

            # Initialize generator
            generator = AIQuizGenerator(
                num_questions=num_questions,
                language=language,
                custom_description=custom_description,
                options_per_question=options_per_question,
                correct_answers_per_question=correct_answers_per_question
            )

            # Generate quiz (does NOT save to database)
            result = generator.generate_quiz(subject)

            # ✅ Deduct currency after successful generation
            deduct_result = PricingService.deduct_currency(
                request.user,
                self.COST_CURRENCY,
                self.QUIZ_GENERATION_COST
            )

            logger.info(
                f"AI Quiz generated (not saved) with {num_questions} questions in {language} "
                f"({options_per_question} options, {correct_answers_per_question} correct) "
                f"for user {request.user.id} - Deducted {self.QUIZ_GENERATION_COST} {self.COST_CURRENCY}"
            )

            return Response(
                {
                    "success": True,
                    "message": f"Quiz generated successfully with {num_questions} questions in {language}",
                    "num_questions": num_questions,
                    "language": language,
                    "options_per_question": options_per_question,
                    "correct_answers_per_question": correct_answers_per_question,
                    "quiz_data": result["quiz_data"],
                    "subject": {
                        "id": str(result["subject"].id),
                        "name": result["subject"].name,
                        "description": result["subject"].description
                    },
                    "currency_deducted": deduct_result["success"],
                    "remaining_balance": deduct_result["remaining_balance"]
                },
                status=status.HTTP_200_OK
            )

        except Subject.DoesNotExist:
            return Response(
                {"success": False, "error": "Subject not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error in GenerateAIQuizView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e) if settings.DEBUG else "Failed to generate quiz"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SaveGeneratedQuizView(generics.CreateAPIView):
    """
    API endpoint to save a generated quiz to database

    Receives the quiz data from GenerateAIQuizView and saves it

    POST /api/learning/quiz/save-generated/
    Request Body:
    {
        "subject_id": "uuid",
        "quiz_data": {
            "title": "...",
            "description": "...",
            "questions": [...]
        },
        "num_questions": 15,
        "language": "English",
        "options_per_question": 2,
        "correct_answers_per_question": 1
    }

    Response:
    {
        "success": true,
        "message": "Quiz saved successfully",
        "quiz": {
            "id": "...",
            "title": "...",
            ... (full quiz data with questions and options)
        }
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SaveGeneratedQuizSerializer

    def create(self, request, *args, **kwargs):
        """Save generated quiz to database"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            subject_id = serializer.validated_data.get('subject_id')
            quiz_data = serializer.validated_data.get('quiz_data')
            num_questions = serializer.validated_data.get('num_questions')
            language = serializer.validated_data.get('language')
            options_per_question = serializer.validated_data.get('options_per_question')
            correct_answers_per_question = serializer.validated_data.get('correct_answers_per_question')

            # Get subject
            subject = Subject.objects.get(id=subject_id)

            # Initialize generator (needed for save_quiz_to_database method)
            generator = AIQuizGenerator(
                num_questions=num_questions,
                language=language,
                options_per_question=options_per_question,
                correct_answers_per_question=correct_answers_per_question
            )

            # Save quiz to database
            quiz = generator.save_quiz_to_database(
                subject=subject,
                quiz_data=quiz_data,
                created_by=request.user,
                num_questions=num_questions,
                language=language,
                options_per_question=options_per_question,
                correct_answers_per_question=correct_answers_per_question
            )

            # Serialize the saved quiz
            quiz_serializer = QuizSerializer(quiz)

            logger.info(
                f"AI Quiz {quiz.id} saved to database with {num_questions} questions in {language} "
                f"({options_per_question} options, {correct_answers_per_question} correct) "
                f"by user {request.user.id}"
            )

            return Response(
                {
                    "success": True,
                    "message": f"Quiz saved successfully with {num_questions} questions",
                    "quiz": quiz_serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        except Subject.DoesNotExist:
            return Response(
                {"success": False, "error": "Subject not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in SaveGeneratedQuizView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e) if settings.DEBUG else "Failed to save quiz"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class QuizDetailView(generics.RetrieveAPIView):
    """
    API endpoint to retrieve a specific quiz in preview mode

    GET /api/learning/quiz/{quiz_id}/

    Returns:
    - 1/3 random questions without answers (preview mode)
    - Quiz rating and rating count
    - User's attempt count and remaining attempts
    - Total attempts count by all users
    """
    permission_classes = [IsAuthenticated]
    queryset = Quiz.objects.prefetch_related('questions', 'attempts')
    serializer_class = QuizDetailPreviewSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'quiz_id'

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Quiz.DoesNotExist:
            return Response(
                {"success": False, "error": "Quiz not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in QuizDetailView: {str(e)}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UserQuizDetailView(generics.RetrieveAPIView):
    """
    API endpoint to retrieve full quiz details with all questions and answers
    Only accessible by the quiz creator

    GET /api/learning/quiz/{quiz_id}/user-detail/

    Returns:
    - All questions with their answers (full access for owner)
    - Quiz rating and rating count
    - User's attempt count and remaining attempts
    - Total attempts count by all users
    """
    permission_classes = [IsAuthenticated]
    queryset = Quiz.objects.prefetch_related('questions__answer_options', 'attempts')  # Added 'attempts'
    serializer_class = UserQuizDetailSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'quiz_id'

    def get_object(self):
        """Override to ensure only the creator can access full details"""
        obj = super().get_object()

        # Check if the user is the creator
        if obj.created_by != self.request.user:
            raise PermissionDenied("You don't have permission to view full details of this quiz.")

        return obj

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Quiz.DoesNotExist:
            return Response(
                {"success": False, "error": "Quiz not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except PermissionDenied as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            logger.error(f"Error in UserQuizDetailView: {str(e)}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class RandomQuizzesView(APIView):
    """
    GET /api/learning/quiz/random/
    Get random public quizzes for the authenticated user (excluding their own quizzes)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit", 10))
            limit = min(max(limit, 1), 50)  # constrain 1–50

            quizzes = get_random_quizzes_for_user(request.user.id, limit=limit)

            serializer = QuizListSerializer(
                quizzes, many=True, context={"request": request}
            )

            return Response(
                {
                    "success": True,
                    "count": len(serializer.data),
                    "quizzes": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error fetching random quizzes: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to fetch random quizzes"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class RandomQuizzesSubjectView(APIView):
    """
    GET /api/learning/quiz/random/subject/<subject_id>/
    Get random public quizzes by subject for the authenticated user
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, subject_id):
        try:
            limit = int(request.query_params.get("limit", 10))
            limit = min(max(limit, 1), 50)  # constrain 1–50

            quizzes = get_random_quizzes_by_subject(
                subject_id, request.user.id, limit=limit
            )

            serializer = QuizListSerializer(
                quizzes, many=True, context={"request": request}
            )

            return Response(
                {
                    "success": True,
                    "count": len(serializer.data),
                    "quizzes": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error fetching random quizzes by subject: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to fetch random quizzes"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class UserQuizzesView(APIView):
    """
    GET /api/learning/quiz/my-quizzes/
    Get all quizzes created by the authenticated user with optional filters

    Query Parameters:
    - limit: number of results (1-50, default: all)
    - offset: pagination offset (default: 0)
    - quiz_type: filter by quiz_type (ai/manual)
    - subject: filter by subject_id
    - language: filter by language
    - title: search by quiz title (case-insensitive partial match)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Get query parameters
            limit = request.query_params.get("limit")
            offset = int(request.query_params.get("offset", 0))
            quiz_type = request.query_params.get("quiz_type")
            subject_id = request.query_params.get("subject")
            language = request.query_params.get("language")
            title = request.query_params.get("title")

            # Base queryset - quizzes created by the user
            quizzes = Quiz.objects.filter(
                created_by=request.user
            ).prefetch_related(
                'questions__answer_options',
                'subject',
                'created_by'
            )

            # Apply filters
            if quiz_type:
                quizzes = quizzes.filter(quiz_type=quiz_type)

            if subject_id:
                quizzes = quizzes.filter(subject_id=subject_id)

            if language:
                quizzes = quizzes.filter(language=language)

            if title:
                quizzes = quizzes.filter(title__icontains=title)

            # Order by most recent first
            quizzes = quizzes.order_by('-created_at')

            # Get total count before pagination
            total_count = quizzes.count()

            # Apply pagination if limit is provided
            if limit:
                limit = min(max(int(limit), 1), 50)  # constrain 1–50
                quizzes = quizzes[offset:offset + limit]

            serializer = QuizListSerializer(
                quizzes, many=True, context={"request": request}
            )

            return Response(
                {
                    "success": True,
                    "total_count": total_count,
                    "count": len(serializer.data),
                    "offset": offset,
                    "quizzes": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error fetching user quizzes: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to fetch user quizzes"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class QuizSearchPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class SearchQuizzesView(generics.ListAPIView):
    """
    API endpoint to search and filter quizzes

    GET /api/learning/quiz/search/

    Query Parameters:
    - q: Search term (searches in title and description) (optional)
    - subject_id: Filter by subject (optional)
    - quiz_type: Filter by type 'ai' or 'human' (optional)
    - language: Filter by language (optional)
    - ordering: Sort by 'created_at', 'title' (optional, default: '-created_at')
    - page: Page number (default: 1)
    - page_size: Items per page (default: 10, max: 100)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = QuizListSerializer
    pagination_class = QuizSearchPagination

    def get_queryset(self):
        queryset = Quiz.objects.prefetch_related('questions').order_by('-created_at')

        # ✅ Remove quizzes created by the authenticated user
        queryset = queryset.exclude(created_by=self.request.user)

        # Search by title or description (optional)
        search_query = self.request.query_params.get('q', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) |
                Q(description__icontains=search_query)
            )

        # Filter by subject
        subject_id = self.request.query_params.get('subject_id')
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)

        # Filter by quiz type
        quiz_type = self.request.query_params.get('quiz_type')
        if quiz_type in ['ai', 'human']:
            queryset = queryset.filter(quiz_type=quiz_type)

        # Filter by language
        language = self.request.query_params.get('language')
        if language:
            # Exact match for language
            queryset = queryset.filter(language=language)

        # Ordering
        ordering = self.request.query_params.get('ordering', '-created_at')
        allowed_ordering = ['-created_at', 'created_at', 'title', '-title']
        if ordering in allowed_ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.filter_queryset(self.get_queryset())
            search_query = request.query_params.get('q', '').strip()

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response({
                    "success": True,
                    "search_query": search_query if search_query else None,
                    "count": len(serializer.data),
                    "results": serializer.data
                })

            serializer = self.get_serializer(queryset, many=True)
            return Response(
                {
                    "success": True,
                    "search_query": search_query if search_query else None,
                    "count": len(serializer.data),
                    "results": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in SearchQuizzesView: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to search quizzes"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class QuizQuestionListView(generics.ListAPIView):
    """
    API endpoint to list questions for a specific quiz

    GET /api/learning/quiz/{quiz_id}/questions/

    Returns questions with attempt tracking.
    If max attempts reached (3), includes error message.

    Costs 200 gold per quiz attempt (when loading questions to do quiz)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = QuizQuestionSerializer

    QUIZ_ATTEMPT_COST = 200
    COST_CURRENCY = "gold"

    def get_queryset(self):
        quiz_id = self.kwargs.get('quiz_id')
        return QuizQuestion.objects.filter(quiz_id=quiz_id).prefetch_related('answer_options')

    def get_serializer_context(self):
        """
        Add attempt_number to serializer context
        This allows QuizQuestionSerializer to access it via self.context
        """
        context = super().get_serializer_context()

        # Get quiz and calculate attempt number
        quiz_id = self.kwargs.get('quiz_id')
        try:
            quiz = Quiz.objects.get(id=quiz_id)
            attempt_count = quiz.get_attempt_count(self.request.user)
            # Current attempt number is count + 1 (e.g., if 2 attempts done, this is attempt 3)
            context['attempt_number'] = attempt_count + 1
        except Quiz.DoesNotExist:
            context['attempt_number'] = None

        return context

    def list(self, request, *args, **kwargs):
        try:
            quiz_id = self.kwargs.get('quiz_id')
            quiz = get_object_or_404(Quiz, id=quiz_id)

            # Check attempt limit
            attempt_count = quiz.get_attempt_count(request.user)
            can_attempt = quiz.can_user_attempt(request.user)
            remaining_attempts = quiz.get_user_remaining_attempts(request.user)
            current_attempt_number = attempt_count + 1

            # ✅ Check if user has sufficient gold BEFORE loading questions
            if not PricingService.has_sufficient_currency(
                    request.user,
                    self.COST_CURRENCY,
                    self.QUIZ_ATTEMPT_COST
            ):
                remaining_balance = PricingService.get_user_balance(
                    request.user,
                    self.COST_CURRENCY
                )
                return Response(
                    {
                        "success": False,
                        "error": f"Insufficient {self.COST_CURRENCY}",
                        "required": self.QUIZ_ATTEMPT_COST,
                        "available": remaining_balance
                    },
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )

            # Get questions with attempt_number in context
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)

            # ✅ Deduct gold after successfully loading questions
            deduct_result = PricingService.deduct_currency(
                request.user,
                self.COST_CURRENCY,
                self.QUIZ_ATTEMPT_COST
            )

            # Base response structure
            response_data = {
                "success": True,
                "quiz_id": str(quiz.id),
                "quiz_title": quiz.title,
                "count": len(serializer.data),
                "questions": serializer.data,
                "attempt_number": current_attempt_number,
                "currency_deducted": deduct_result["success"],
                "remaining_balance": deduct_result["remaining_balance"]
            }

            # Add error if max attempts reached
            if not can_attempt:
                response_data[
                    "error"] = f"Maximum attempts reached. You have already completed this quiz {attempt_count} times."
                logger.warning(
                    f"User {request.user.id} attempted to load quiz {quiz_id} "
                    f"but has reached max attempts ({attempt_count}/3)"
                )
            else:
                logger.info(
                    f"User {request.user.id} loaded quiz {quiz_id}. "
                    f"Attempt {current_attempt_number}/3, Remaining: {remaining_attempts - 1} after this. "
                    f"Deducted {self.QUIZ_ATTEMPT_COST} {self.COST_CURRENCY}"
                )

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in QuizQuestionListView: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to retrieve questions"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SubmitQuizView(generics.CreateAPIView):
    """
    API endpoint to submit quiz answers

    POST /api/learning/quiz/{quiz_id}/submit/
    {
        "answers": [
            {
                "question_id": "uuid",
                "selected_option_id": "uuid"
            },
            ...
        ],
        "duration_seconds": 325
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SubmitQuizSerializer

    def create(self, request, *args, **kwargs):
        """Submit and score quiz answers"""
        try:
            quiz_id = self.kwargs.get('quiz_id')
            quiz = get_object_or_404(Quiz, id=quiz_id)

            # Validate with serializer
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            answers_data = serializer.validated_data.get('answers', [])
            duration_seconds = serializer.validated_data.get('duration_seconds')

            submit_service = QuizSubmitService()
            attempt = submit_service.submit_quiz(quiz, request.user, answers_data, duration_seconds)

            # Serialize the attempt
            attempt_serializer = QuizAttemptSerializer(attempt)

            # Get summary info
            summary = submit_service.get_attempt_summary(attempt)

            logger.info(
                f"Quiz attempt {attempt.id} submitted by user {request.user.id}: "
                f"{summary['correct_answers']}/{summary['total_questions']} in {summary['duration_seconds']}s"
            )

            return Response(
                {
                    "success": True,
                    "message": f"Quiz completed! You got {summary['correct_answers']}/{summary['total_questions']} correct.",
                    "attempt": attempt_serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        except ValueError as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error in SubmitQuizView: {str(e)}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class QuizAttemptDetailView(generics.RetrieveAPIView):
    """
    API endpoint to retrieve quiz attempt details with answers

    GET /api/learning/quiz/attempt/{attempt_id}/

    Response includes:
    - attempt details with score and duration
    - rating (if already rated) and can_rate flag
    - all answers with correct/incorrect status
    """
    permission_classes = [IsAuthenticated]
    queryset = QuizAttempt.objects.prefetch_related('answers__question', 'answers__selected_option')
    serializer_class = QuizAttemptDetailSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'attempt_id'

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()

            # Only allow user to view their own attempts
            if instance.user != request.user:
                return Response(
                    {"error": "Permission denied"},
                    status=status.HTTP_403_FORBIDDEN
                )

            serializer = self.get_serializer(instance)
            return Response(
                {
                    "success": True,
                    "attempt": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except QuizAttempt.DoesNotExist:
            return Response(
                {"error": "Quiz attempt not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in QuizAttemptDetailView: {str(e)}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UserQuizAttemptsView(generics.ListAPIView):
    """
    API endpoint to list all quiz attempts by authenticated user

    GET /api/learning/quiz/attempts/
    Query params:
    - quiz_id: filter by quiz (optional)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserQuizAttemptsSerializer

    def get_queryset(self):
        queryset = QuizAttempt.objects.filter(user=self.request.user).order_by('-created_at')

        quiz_id = self.request.query_params.get('quiz_id')
        if quiz_id:
            queryset = queryset.filter(quiz_id=quiz_id)

        return queryset

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)

            return Response(
                {
                    "success": True,
                    "count": len(serializer.data),
                    "attempts": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in UserQuizAttemptsView: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to retrieve attempts"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# ===================== QUIZ CREATION (Used by both methods) =====================

class CreateQuizView(generics.CreateAPIView):
    """
    API endpoint to create a new quiz (step 1: quiz information)
    Used as the first step for both manual creation and Excel import

    Costs 1000 gold per quiz creation (one-time charge)

    POST /api/learning/quiz/create/
    {
        "title": "Biology Basics",
        "description": "An introductory biology quiz",
        "subject": "uuid-of-subject",
        "language": "English"
    }

    Returns: Quiz object with id for use in next step

    Error Response (HTTP 402):
    {
        "success": false,
        "error": "Insufficient gold",
        "required": 1000,
        "available": 500
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CreateQuizSerializer

    QUIZ_CREATION_COST = 1000
    COST_CURRENCY = "gold"

    def create(self, request, *args, **kwargs):
        try:
            # ✅ Check if user has sufficient gold
            if not PricingService.has_sufficient_currency(
                    request.user,
                    self.COST_CURRENCY,
                    self.QUIZ_CREATION_COST
            ):
                remaining_balance = PricingService.get_user_balance(
                    request.user,
                    self.COST_CURRENCY
                )
                return Response(
                    {
                        "success": False,
                        "error": f"Insufficient {self.COST_CURRENCY}",
                        "required": self.QUIZ_CREATION_COST,
                        "available": remaining_balance
                    },
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            # Create quiz with human type (for both manual and import)
            quiz = Quiz.objects.create(
                title=serializer.validated_data['title'],
                description=serializer.validated_data.get('description', ''),
                subject=serializer.validated_data['subject'],
                language=serializer.validated_data.get('language', 'English'),
                created_by=request.user,
                quiz_type='human'
            )

            # ✅ Deduct currency after successful creation
            deduct_result = PricingService.deduct_currency(
                request.user,
                self.COST_CURRENCY,
                self.QUIZ_CREATION_COST
            )

            logger.info(
                f"Quiz {quiz.id} created by user {request.user.id} - "
                f"Deducted {self.QUIZ_CREATION_COST} {self.COST_CURRENCY}"
            )

            return Response(
                {
                    "success": True,
                    "message": "Quiz created successfully",
                    "quiz": {
                        "id": str(quiz.id),
                        "title": quiz.title,
                        "description": quiz.description,
                        "subject": str(quiz.subject.id),
                        "language": quiz.language,
                        "quiz_type": quiz.quiz_type
                    },
                    "currency_deducted": deduct_result["success"],
                    "remaining_balance": deduct_result["remaining_balance"]
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"Error in CreateQuizView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e) if request.user.is_staff else "Failed to create quiz"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

class AddManualQuestionsView(generics.CreateAPIView):
    """
    API endpoint to add multiple questions manually to a quiz at once

    POST /api/learning/quiz/{quiz_id}/add-manual-questions/
    {
        "questions": [
            {
                "question_text": "What is the capital of France?",
                "answer_options": [
                    {
                        "option_text": "Paris",
                        "is_correct": true
                    },
                    {
                        "option_text": "London",
                        "is_correct": false
                    },
                    {
                        "option_text": "Berlin",
                        "is_correct": false
                    }
                ]
            },
            {
                "question_text": "What is 2+2?",
                "answer_options": [
                    {
                        "option_text": "4",
                        "is_correct": true
                    },
                    {
                        "option_text": "3",
                        "is_correct": false
                    },
                    {
                        "option_text": "5",
                        "is_correct": false
                    }
                ]
            }
        ]
    }

    Returns:
    {
        "success": true,
        "message": "2 questions added successfully",
        "questions_added": 2,
        "questions": [
            {
                "id": "uuid",
                "question_text": "What is the capital of France?",
                "answer_options_count": 3
            },
            {
                "id": "uuid",
                "question_text": "What is 2+2?",
                "answer_options_count": 3
            }
        ]
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AddManualQuestionsSerializer

    def create(self, request, *args, **kwargs):
        try:
            quiz_id = self.kwargs.get('quiz_id')
            quiz = get_object_or_404(Quiz, id=quiz_id)

            # Check if quiz belongs to user or user has permission
            if quiz.created_by != request.user:
                return Response(
                    {
                        "success": False,
                        "error": "You don't have permission to add questions to this quiz"
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            # Validate input
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            questions_data = serializer.validated_data['questions']
            created_questions = []

            # Create all questions and answer options in a single transaction
            with transaction.atomic():
                for question_data in questions_data:
                    question_text = question_data['question_text']
                    answer_options_data = question_data['answer_options']

                    # Create question
                    question = QuizQuestion.objects.create(
                        quiz=quiz,
                        question_text=question_text
                    )

                    # Create answer options
                    answer_options = []
                    for option_data in answer_options_data:
                        answer_option = QuizAnswerOption.objects.create(
                            question=question,
                            option_text=option_data['option_text'],
                            is_correct=option_data['is_correct']
                        )
                        answer_options.append(answer_option)

                    created_questions.append({
                        "id": str(question.id),
                        "question_text": question.question_text,
                        "answer_options_count": len(answer_options)
                    })

            logger.info(
                f"{len(created_questions)} questions added to quiz {quiz.id} by user {request.user.id}"
            )

            return Response(
                {
                    "success": True,
                    "message": f"{len(created_questions)} question{'s' if len(created_questions) != 1 else ''} added successfully",
                    "questions_added": len(created_questions),
                    "questions": created_questions
                },
                status=status.HTTP_201_CREATED
            )

        except ValidationError as e:
            logger.warning(f"Validation error in AddManualQuestionsView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error in AddManualQuestionsView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": "An unexpected error occurred while adding questions"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ImportQuestionsFromExcelView(generics.CreateAPIView):
    """
    API endpoint to parse questions from Excel file (does NOT save to database, does NOT require quiz_id)

    POST /api/learning/import-questions-from-excel/

    Form data:
    - file: Excel file (.xlsx or .xls)

    Excel file format:
    | question | answer | results |
    |----------|--------|---------|
    | What is 2+2? | 4 | true |
    | What is 2+2? | 5 | false |
    | What is 2+2? | 3 | false |

    Returns:
    {
        "success": true,
        "message": "Questions parsed successfully from Excel",
        "questions_count": 2,
        "total_options": 7,
        "questions": [
            {
                "question_text": "What is 2+2?",
                "answer_options": [
                    {
                        "option_text": "4",
                        "is_correct": true
                    },
                    {
                        "option_text": "5",
                        "is_correct": false
                    },
                    {
                        "option_text": "3",
                        "is_correct": false
                    }
                ]
            }
        ]
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ImportQuestionsFromExcelSerializer
    parser_classes = (
        __import__('rest_framework.parsers', fromlist=['MultiPartParser']).MultiPartParser,
        __import__('rest_framework.parsers', fromlist=['FormParser']).FormParser,
    )

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            excel_file = serializer.validated_data['file']

            # Validate file extension
            file_name = excel_file.name.lower()
            if not (file_name.endswith('.xlsx') or file_name.endswith('.xls')):
                return Response(
                    {
                        "success": False,
                        "error": "Invalid file format. Only .xlsx and .xls files are supported"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Save uploaded file to temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                for chunk in excel_file.chunks():
                    tmp_file.write(chunk)
                tmp_file_path = tmp_file.name

            try:
                # Parse Excel file
                excel_importer = ExcelQuizImporter(tmp_file_path)
                quiz_data = excel_importer.parse_quiz_data()

                # Count total options
                total_options = sum(len(q['answer_options']) for q in quiz_data)

                logger.info(
                    f"Excel parsed by user {request.user.id}: "
                    f"{len(quiz_data)} questions, {total_options} options"
                )

                # Return parsed questions WITHOUT saving to database
                return Response(
                    {
                        "success": True,
                        "message": f"Questions parsed successfully from Excel",
                        "questions_count": len(quiz_data),
                        "total_options": total_options,
                        "questions": quiz_data  # Return the parsed questions
                    },
                    status=status.HTTP_200_OK
                )

            finally:
                # Clean up temporary file
                if os.path.exists(tmp_file_path):
                    os.remove(tmp_file_path)

        except ValueError as e:
            logger.error(f"Excel parsing error: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error in ImportQuestionsFromExcelView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": "Failed to parse questions from Excel"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeleteQuizView(QuizOwnershipMixin, generics.DestroyAPIView):
    """
    API endpoint to delete a quiz
    Only the quiz owner (creator) can delete it

    DELETE /api/learning/quiz/{quiz_id}/delete/

    This will delete:
    - The quiz itself
    - All questions in the quiz
    - All answer options for those questions
    """
    permission_classes = [IsAuthenticated]
    queryset = Quiz.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'quiz_id'

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()

            # Check ownership
            permission_error = self.check_permission_or_403(instance, request)
            if permission_error:
                return permission_error

            quiz_id = str(instance.id)
            quiz_title = instance.title

            instance.delete()

            logger.info(f"Quiz {quiz_id} deleted by owner {request.user.id}")

            return Response(
                {
                    "success": True,
                    "message": f"Quiz '{quiz_title}' and all its questions have been deleted successfully"
                },
                status=status.HTTP_200_OK
            )
        except Quiz.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": "Quiz not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in DeleteQuizView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": "Failed to delete quiz"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class EditQuizView(generics.UpdateAPIView):
    """
    Unified API endpoint to edit quiz, questions, and answer options in ONE request

    PATCH/PUT /api/learning/quiz/{quiz_id}/edit-unified/

    This endpoint allows you to:
    1. Edit quiz metadata (title, description, subject, language)
    2. Add new questions
    3. Update existing questions
    4. Delete questions
    5. Add new answer options
    6. Update existing answer options
    7. Delete answer options

    All in a single API call!

    Request Body Structure:
    {
        "title": "Updated Quiz Title",  // optional
        "description": "Updated description",  // optional
        "subject_id": "uuid",  // optional
        "language": "Vietnamese",  // optional
        "questions": [  // optional
            {
                "id": "existing-question-uuid",  // required for update/delete, null for create
                "_action": "update",  // "create", "update", "delete", "keep"
                "question_text": "Updated question?",
                "answer_options": [
                    {
                        "id": "existing-option-uuid",  // required for update/delete, null for create
                        "_action": "update",  // "create", "update", "delete", "keep"
                        "option_text": "Updated option",
                        "is_correct": true
                    }
                ]
            }
        ]
    }

    Response:
    {
        "success": true,
        "message": "Quiz updated successfully",
        "quiz": { ... full quiz data with questions and options ... }
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UnifiedEditQuizSerializer
    queryset = Quiz.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'quiz_id'

    def update(self, request, *args, **kwargs):
        """Handle unified quiz edit"""
        quiz = self.get_object()

        # Check if user owns the quiz (optional - adjust based on your permissions)
        # if quiz.created_by != request.user:
        #     return Response(
        #         {"success": False, "error": "You don't have permission to edit this quiz"},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        serializer = self.get_serializer(quiz, data=request.data, partial=True)

        try:
            serializer.is_valid(raise_exception=True)
            updated_quiz = serializer.save()

            # Return the updated quiz with all questions and options
            quiz_serializer = QuizSerializer(updated_quiz)

            logger.info(f"Quiz {quiz.id} updated successfully by user {request.user.id}")

            return Response(
                {
                    "success": True,
                    "message": "Quiz updated successfully",
                    "quiz": quiz_serializer.data
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error updating quiz {quiz.id}: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e) if settings.DEBUG else "Failed to update quiz"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    def partial_update(self, request, *args, **kwargs):
        """Handle PATCH requests (same as PUT for this endpoint)"""
        return self.update(request, *args, **kwargs)

# ===================== QUIZ RATING =====================

class RateQuizAttemptView(APIView):
    """
    API endpoint to rate a quiz attempt

    POST /api/learning/quiz/attempt/{attempt_id}/rate/

    Request Body:
    {
        "rating": 4.5
    }

    Response:
    {
        "success": true,
        "message": "Rating submitted successfully",
        "attempt": {
            "id": "uuid",
            "rating": 4.5,
            "quiz_title": "Biology Basics",
            "attempt_number": 2,
            "remaining_attempts": 1
        },
        "quiz_rating": {
            "average_rating": 4.2,
            "rating_count": 15
        }
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, attempt_id):
        try:
            # Get the attempt
            attempt = get_object_or_404(QuizAttempt, id=attempt_id)

            # Check if user owns this attempt
            if attempt.user != request.user:
                return Response(
                    {
                        "success": False,
                        "error": "You can only rate your own quiz attempts"
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            # Check if already rated
            if not attempt.can_rate():
                return Response(
                    {
                        "success": False,
                        "error": "This attempt has already been rated"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate rating
            serializer = RateQuizSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            rating = serializer.validated_data['rating']

            # Save rating to attempt
            with transaction.atomic():
                attempt.rating = rating
                attempt.save()

                # Trigger async task to recalculate quiz rating
                recalculate_quiz_rating.delay(str(attempt.quiz.id))

            # Serialize response
            attempt_serializer = QuizAttemptWithRatingSerializer(
                attempt,
                context={'request': request}
            )

            logger.info(
                f"User {request.user.id} rated quiz attempt {attempt_id} "
                f"with rating {rating}"
            )

            return Response(
                {
                    "success": True,
                    "message": "Rating submitted successfully",
                    "attempt": attempt_serializer.data,
                    "quiz_rating": {
                        "quiz_id": str(attempt.quiz.id),
                        "message": "Quiz rating is being recalculated"
                    }
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in RateQuizAttemptView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

