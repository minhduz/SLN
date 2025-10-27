# learning/views.py
from rest_framework.views import APIView
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.conf import settings
import logging
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.db.models import Q

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
    AddManualQuestionSerializer,
    ImportQuestionsFromExcelSerializer,
    QuizDetailPreviewSerializer,
    UnifiedEditQuizSerializer
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
    """
    API endpoint to generate an AI quiz WITHOUT saving to database

    Returns the generated quiz data that can be previewed before saving

    POST /api/learning/quiz/generate-ai/
    Request Body:
    {
        "subject_id": "optional-uuid",
        "num_questions": 15,
        "language": "English",
        "description": "Optional custom description",
        "options_per_question": 2,
        "correct_answers_per_question": 1
    }

    Response:
    {
        "success": true,
        "message": "Quiz generated successfully",
        "num_questions": 15,
        "language": "English",
        "options_per_question": 2,
        "correct_answers_per_question": 1,
        "quiz_data": {
            "title": "...",
            "description": "...",
            "questions": [...]
        },
        "subject": {
            "id": "...",
            "name": "...",
            "description": "..."
        }
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = GenerateAIQuizSerializer

    def create(self, request, *args, **kwargs):
        """Generate AI quiz without saving to database"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
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

            logger.info(
                f"AI Quiz generated (not saved) with {num_questions} questions in {language} "
                f"({options_per_question} options, {correct_answers_per_question} correct) "
                f"for user {request.user.id}"
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
                    }
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

    Returns 1/3 random questions without answers (preview mode)
    """
    permission_classes = [IsAuthenticated]
    queryset = Quiz.objects.prefetch_related('questions')
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
    """
    permission_classes = [IsAuthenticated]
    serializer_class = QuizQuestionSerializer

    def get_queryset(self):
        quiz_id = self.kwargs.get('quiz_id')
        return QuizQuestion.objects.filter(quiz_id=quiz_id).prefetch_related('answer_options')

    def list(self, request, *args, **kwargs):
        try:
            quiz_id = self.kwargs.get('quiz_id')
            quiz = get_object_or_404(Quiz, id=quiz_id)

            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)

            return Response(
                {
                    "success": True,
                    "quiz_id": str(quiz.id),
                    "quiz_title": quiz.title,
                    "count": len(serializer.data),
                    "questions": serializer.data
                },
                status=status.HTTP_200_OK
            )
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

    POST /api/learning/quiz/create/
    {
        "title": "Biology Basics",
        "description": "An introductory biology quiz",
        "subject": "uuid-of-subject",
        "language": "English"
    }

    Returns: Quiz object with id for use in next step
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CreateQuizSerializer

    def create(self, request, *args, **kwargs):
        try:
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

            logger.info(f"Quiz {quiz.id} created by user {request.user.id}")

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
                    }
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


class AddManualQuestionView(generics.CreateAPIView):
    """
    API endpoint to add a question manually to a quiz (for manual creation)

    POST /api/learning/quiz/{quiz_id}/add-manual-question/
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
    }

    Can be called multiple times to add multiple questions to same quiz
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AddManualQuestionSerializer

    def create(self, request, *args, **kwargs):
        try:
            quiz_id = self.kwargs.get('quiz_id')
            quiz = get_object_or_404(Quiz, id=quiz_id)

            # Validate input
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            question_text = serializer.validated_data['question_text']
            answer_options_data = serializer.validated_data['answer_options']

            # Create question and answer options in a transaction
            with transaction.atomic():
                # Create question
                question = QuizQuestion.objects.create(
                    quiz=quiz,
                    question_text=question_text
                )

                # Create answer options
                for option_data in answer_options_data:
                    QuizAnswerOption.objects.create(
                        question=question,
                        option_text=option_data['option_text'],
                        is_correct=option_data['is_correct']
                    )

            logger.info(
                f"Question {question.id} added to quiz {quiz.id} by user {request.user.id}"
            )

            return Response(
                {
                    "success": True,
                    "message": "Question added successfully",
                    "question": {
                        "id": str(question.id),
                        "question_text": question.question_text,
                        "answer_options_count": len(answer_options_data)
                    }
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"Error in AddManualQuestionView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )


class ImportQuestionsFromExcelView(generics.CreateAPIView):
    """
    API endpoint to import questions from Excel file to a quiz

    POST /api/learning/quiz/{quiz_id}/import-questions-from-excel/

    Form data:
    - file: Excel file (.xlsx or .xls)

    Excel file format:
    | question | answer | results |
    |----------|--------|---------|
    | What is 2+2? | 4 | true |
    | What is 2+2? | 5 | false |
    | What is 2+2? | 3 | false |
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ImportQuestionsFromExcelSerializer
    parser_classes = (
        __import__('rest_framework.parsers', fromlist=['MultiPartParser']).MultiPartParser,
        __import__('rest_framework.parsers', fromlist=['FormParser']).FormParser,
    )

    def create(self, request, *args, **kwargs):
        try:
            quiz_id = self.kwargs.get('quiz_id')
            quiz = get_object_or_404(Quiz, id=quiz_id)

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            excel_file = serializer.validated_data['file']

            # Save uploaded file to temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                for chunk in excel_file.chunks():
                    tmp_file.write(chunk)
                tmp_file_path = tmp_file.name

            try:
                # Parse Excel file
                excel_importer = ExcelQuizImporter(tmp_file_path)
                quiz_data = excel_importer.parse_quiz_data()

                # Create questions and answer options in a transaction
                with transaction.atomic():
                    total_options = 0
                    for question_data in quiz_data:
                        question = QuizQuestion.objects.create(
                            quiz=quiz,
                            question_text=question_data['question_text']
                        )

                        for option_data in question_data['answer_options']:
                            QuizAnswerOption.objects.create(
                                question=question,
                                option_text=option_data['option_text'],
                                is_correct=option_data['is_correct']
                            )
                            total_options += 1

                logger.info(
                    f"Quiz {quiz.id} imported from Excel by user {request.user.id}: "
                    f"{len(quiz_data)} questions, {total_options} options"
                )

                return Response(
                    {
                        "success": True,
                        "message": f"Questions imported successfully from Excel",
                        "import_summary": {
                            "quiz_id": str(quiz.id),
                            "questions_added": len(quiz_data),
                            "total_options_added": total_options
                        }
                    },
                    status=status.HTTP_201_CREATED
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
                    "error": "Failed to import questions from Excel"
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