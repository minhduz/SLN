# learning/views.py
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
import logging
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Quiz, QuizQuestion, QuizAnswerOption, QuizAttempt, QuizAttemptAnswer
from .serializers import (
    QuizSerializer,
    QuizListSerializer,
    GenerateAIQuizSerializer,
    QuizQuestionSerializer,
    SubmitQuizSerializer,
    QuizAttemptSerializer,
    QuizAttemptDetailSerializer,
    UserQuizAttemptsSerializer,
    CreateQuizSerializer,
    AddManualQuestionSerializer,
    ImportQuestionsFromExcelSerializer,
    EditQuizSerializer,
    EditQuestionSerializer,
    EditAnswerOptionSerializer,
    UpdateAnswerOptionSerializer,
)
from .service.quiz_service import AIQuizGenerator
from .service.submit_service import QuizSubmitService
from .service.file_service import ExcelQuizImporter
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
    API endpoint to generate an AI quiz

    POST /api/learning/quiz/generate-ai/
    {
        "subject_id": "optional-uuid",
        "num_questions": 10,
        "language": "Vietnamese"
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = GenerateAIQuizSerializer

    def create(self, request, *args, **kwargs):
        """Generate and save an AI quiz with flexible question count and language"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            subject_id = serializer.validated_data.get('subject_id')
            num_questions = serializer.validated_data.get('num_questions', 10)
            language = serializer.validated_data.get('language', 'English')

            # Get subject
            if subject_id:
                subject = Subject.objects.get(id=subject_id)
            else:
                subject = None  # Will be randomly selected

            # Generate and save quiz with specified number of questions and language
            generator = AIQuizGenerator(num_questions=num_questions, language=language)
            quiz = generator.generate_and_save_quiz(
                subject,
                created_by=request.user,)
            quiz_serializer = QuizSerializer(quiz)

            logger.info(
                f"AI Quiz {quiz.id} with {num_questions} questions in {language} "
                f"generated for user {request.user.id}"
            )

            return Response(
                {
                    "success": True,
                    "message": f"Quiz generated successfully with {num_questions} questions in {language}",
                    "num_questions": num_questions,
                    "language": language,
                    "quiz": quiz_serializer.data
                },
                status=status.HTTP_201_CREATED
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

class QuizDetailView(generics.RetrieveAPIView):
    """
    API endpoint to retrieve a specific quiz

    GET /api/learning/quiz/{quiz_id}/
    """
    permission_classes = [IsAuthenticated]
    queryset = Quiz.objects.prefetch_related('questions__answer_options')
    serializer_class = QuizSerializer
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


class QuizListView(generics.ListAPIView):
    """
    API endpoint to list all quizzes

    GET /api/learning/quiz/
    Query params:
    - quiz_type: 'ai' or 'human' (optional)
    - subject_id: filter by subject (optional)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = QuizListSerializer

    def get_queryset(self):
        queryset = Quiz.objects.prefetch_related('questions__answer_options').order_by('-created_at')

        # Filter by quiz type if provided
        quiz_type = self.request.query_params.get('quiz_type')
        if quiz_type in ['ai', 'human']:
            queryset = queryset.filter(quiz_type=quiz_type)

        # Filter by subject if provided
        subject_id = self.request.query_params.get('subject_id')
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)

        return queryset

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)

            return Response(
                {
                    "success": True,
                    "count": len(serializer.data),
                    "quizzes": serializer.data
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error in QuizListView: {str(e)}")
            return Response(
                {"success": False, "error": "Failed to retrieve quizzes"},
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

# =====================QUIZ EDIT & DELETE(WITH OWNERSHIP) ===================

class EditQuizView(QuizOwnershipMixin, generics.UpdateAPIView):
    """
    API endpoint to edit quiz information
    Only the quiz owner (creator) can edit it

    PATCH /api/learning/quiz/{quiz_id}/edit/
    {
        "title": "Updated Title",
        "description": "Updated Description",
        "subject": "uuid-of-subject",
        "language": "Vietnamese"
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = EditQuizSerializer
    queryset = Quiz.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'quiz_id'

    def partial_update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()

            # Check ownership
            permission_error = self.check_permission_or_403(instance, request)
            if permission_error:
                return permission_error

            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            logger.info(f"Quiz {instance.id} updated by owner {request.user.id}")

            return Response(
                {
                    "success": True,
                    "message": "Quiz updated successfully",
                    "quiz": {
                        "id": str(instance.id),
                        "title": instance.title,
                        "description": instance.description,
                        "subject": str(instance.subject.id),
                        "language": instance.language
                    }
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
            logger.error(f"Error in EditQuizView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


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


# ===================== QUESTION EDIT & DELETE (WITH OWNERSHIP) =====================

class EditQuestionView(QuizOwnershipMixin, generics.UpdateAPIView):
    """
    API endpoint to edit a quiz question and its answer options
    Only the quiz owner can edit questions

    PATCH /api/learning/quiz/{quiz_id}/question/{question_id}/edit/
    {
        "question_text": "Updated question text?",
        "answer_options": [
            {
                "option_text": "Answer 1",
                "is_correct": true
            },
            {
                "option_text": "Answer 2",
                "is_correct": false
            }
        ]
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = EditQuestionSerializer
    queryset = QuizQuestion.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'question_id'

    def get_queryset(self):
        """Filter questions by quiz_id"""
        quiz_id = self.kwargs.get('quiz_id')
        return QuizQuestion.objects.filter(quiz_id=quiz_id)

    def partial_update(self, request, *args, **kwargs):
        try:
            # Check quiz ownership first
            quiz = self.get_quiz_owner()
            permission_error = self.check_permission_or_403(quiz, request)
            if permission_error:
                return permission_error

            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            logger.info(f"Question {instance.id} updated by quiz owner {request.user.id}")

            # Get updated answer options
            answer_options = [
                {
                    "id": str(option.id),
                    "option_text": option.option_text,
                    "is_correct": option.is_correct
                }
                for option in instance.answer_options.all()
            ]

            return Response(
                {
                    "success": True,
                    "message": "Question updated successfully",
                    "question": {
                        "id": str(instance.id),
                        "question_text": instance.question_text,
                        "answer_options": answer_options
                    }
                },
                status=status.HTTP_200_OK
            )
        except QuizQuestion.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": "Question not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in EditQuestionView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class DeleteQuestionView(QuizOwnershipMixin, generics.DestroyAPIView):
    """
    API endpoint to delete a quiz question
    Only the quiz owner can delete questions

    DELETE /api/learning/quiz/{quiz_id}/question/{question_id}/delete/

    This will delete:
    - The question itself
    - All answer options for this question
    """
    permission_classes = [IsAuthenticated]
    queryset = QuizQuestion.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'question_id'

    def get_queryset(self):
        """Filter questions by quiz_id"""
        quiz_id = self.kwargs.get('quiz_id')
        return QuizQuestion.objects.filter(quiz_id=quiz_id)

    def destroy(self, request, *args, **kwargs):
        try:
            # Check quiz ownership first
            quiz = self.get_quiz_owner()
            permission_error = self.check_permission_or_403(quiz, request)
            if permission_error:
                return permission_error

            instance = self.get_object()
            question_text = instance.question_text[:50]

            instance.delete()

            logger.info(f"Question {instance.id} deleted by quiz owner {request.user.id}")

            return Response(
                {
                    "success": True,
                    "message": f"Question '{question_text}...' and all its answer options have been deleted successfully"
                },
                status=status.HTTP_200_OK
            )
        except QuizQuestion.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": "Question not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in DeleteQuestionView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": "Failed to delete question"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ===================== ANSWER OPTION EDIT & DELETE (WITH OWNERSHIP) =====================

class EditAnswerOptionView(QuizOwnershipMixin, generics.UpdateAPIView):
    """
    API endpoint to edit a single answer option
    Only the quiz owner can edit answer options

    PATCH /api/learning/quiz/{quiz_id}/question/{question_id}/option/{option_id}/edit/
    {
        "option_text": "Updated answer text",
        "is_correct": true
    }
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UpdateAnswerOptionSerializer
    queryset = QuizAnswerOption.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'option_id'

    def get_queryset(self):
        """Filter options by question_id"""
        question_id = self.kwargs.get('question_id')
        return QuizAnswerOption.objects.filter(question_id=question_id)

    def partial_update(self, request, *args, **kwargs):
        try:
            # Check quiz ownership first
            quiz = self.get_quiz_owner()
            permission_error = self.check_permission_or_403(quiz, request)
            if permission_error:
                return permission_error

            instance = self.get_object()

            # Validate that if we're updating is_correct to False,
            # at least one other option remains correct
            if 'is_correct' in request.data and request.data['is_correct'] is False:
                other_correct = instance.question.answer_options.filter(
                    is_correct=True
                ).exclude(id=instance.id).exists()

                if not other_correct:
                    return Response(
                        {
                            "success": False,
                            "error": "Cannot unmark as correct - question must have at least one correct answer"
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Check for duplicate option text if updating option_text
            if 'option_text' in request.data:
                new_text = request.data['option_text'].strip()
                duplicate = instance.question.answer_options.filter(
                    option_text=new_text
                ).exclude(id=instance.id).exists()

                if duplicate:
                    return Response(
                        {
                            "success": False,
                            "error": "An answer option with this text already exists for this question"
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)

            # Manual update since we need to handle stripped text
            if 'option_text' in request.data:
                instance.option_text = request.data['option_text'].strip()
            if 'is_correct' in request.data:
                instance.is_correct = request.data['is_correct']

            instance.save()

            logger.info(f"Answer option {instance.id} updated by quiz owner {request.user.id}")

            return Response(
                {
                    "success": True,
                    "message": "Answer option updated successfully",
                    "option": {
                        "id": str(instance.id),
                        "option_text": instance.option_text,
                        "is_correct": instance.is_correct
                    }
                },
                status=status.HTTP_200_OK
            )
        except QuizAnswerOption.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": "Answer option not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in EditAnswerOptionView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class DeleteAnswerOptionView(QuizOwnershipMixin, generics.DestroyAPIView):
    """
    API endpoint to delete a single answer option
    Only the quiz owner can delete answer options

    DELETE /api/learning/quiz/{quiz_id}/question/{question_id}/option/{option_id}/delete/

    Validation:
    - Cannot delete if it's the only correct answer
    - Question must have at least 2 options after deletion
    """
    permission_classes = [IsAuthenticated]
    queryset = QuizAnswerOption.objects.all()
    lookup_field = 'id'
    lookup_url_kwarg = 'option_id'

    def get_queryset(self):
        """Filter options by question_id"""
        question_id = self.kwargs.get('question_id')
        return QuizAnswerOption.objects.filter(question_id=question_id)

    def destroy(self, request, *args, **kwargs):
        try:
            # Check quiz ownership first
            quiz = self.get_quiz_owner()
            permission_error = self.check_permission_or_403(quiz, request)
            if permission_error:
                return permission_error

            instance = self.get_object()
            question = instance.question
            option_text = instance.option_text[:50]

            # Check if question would have less than 2 options after deletion
            remaining_options = question.answer_options.exclude(id=instance.id).count()
            if remaining_options < 2:
                return Response(
                    {
                        "success": False,
                        "error": "Cannot delete - question must have at least 2 answer options"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if this is the only correct answer
            if instance.is_correct:
                other_correct = question.answer_options.filter(
                    is_correct=True
                ).exclude(id=instance.id).exists()

                if not other_correct:
                    return Response(
                        {
                            "success": False,
                            "error": "Cannot delete - this is the only correct answer for this question"
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

            instance.delete()

            logger.info(f"Answer option {instance.id} deleted by quiz owner {request.user.id}")

            return Response(
                {
                    "success": True,
                    "message": f"Answer option '{option_text}...' has been deleted successfully"
                },
                status=status.HTTP_200_OK
            )
        except QuizAnswerOption.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": "Answer option not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error in DeleteAnswerOptionView: {str(e)}")
            return Response(
                {
                    "success": False,
                    "error": "Failed to delete answer option"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )