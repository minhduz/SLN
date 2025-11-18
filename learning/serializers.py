from rest_framework import serializers
from .models import Quiz, QuizQuestion, QuizAnswerOption, QuizAttempt, QuizAttemptAnswer
from qa.models import Subject
from accounts.models import User
import random


class QuizAnswerOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizAnswerOption
        fields = ['id', 'option_text', 'is_correct']
        extra_kwargs = {
            'is_correct': {'read_only': True}  # Hide correct answer from frontend initially
        }


class QuizQuestionSerializer(serializers.ModelSerializer):
    answer_options = QuizAnswerOptionSerializer(many=True, read_only=True)
    attempt_number = serializers.SerializerMethodField()

    class Meta:
        model = QuizQuestion
        fields = ['id', 'question_text', 'answer_options', 'attempt_number']

    def get_attempt_number(self, obj):
        return self.context.get('attempt_number', None)


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['id', 'name', 'description']


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model (basic info only)"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name', 'avatar', 'role']
        read_only_fields = ['id']


class QuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'language', 'subject', 'quiz_type', 'quiz_type_display', 'questions', 'created_by', 'created_at']


class QuizQuestionPreviewSerializer(serializers.ModelSerializer):
    """Serializer for quiz questions without answer options (preview mode)"""

    class Meta:
        model = QuizQuestion
        fields = ['id', 'question_text']


class QuizDetailPreviewSerializer(serializers.ModelSerializer):
    """Serializer for quiz detail preview - shows 1/3 random questions without answers"""
    questions = serializers.SerializerMethodField()
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    total_questions = serializers.SerializerMethodField()
    preview_questions_count = serializers.SerializerMethodField()
    preview_mode = serializers.SerializerMethodField()

    # NEW: Add these fields
    user_attempt_count = serializers.SerializerMethodField()
    user_remaining_attempts = serializers.SerializerMethodField()
    total_attempts_count = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            'id', 'title', 'description', 'language', 'rating', 'rating_count',  # Added rating_count
            'subject', 'quiz_type', 'quiz_type_display', 'questions', 'created_by',
            'created_at', 'total_questions', 'preview_questions_count', 'preview_mode',
            'user_attempt_count', 'user_remaining_attempts', 'total_attempts_count'  # NEW fields
        ]

    def get_total_questions(self, obj):
        return obj.questions.count()

    def get_preview_questions_count(self, obj):
        total = obj.questions.count()
        return max(1, total // 3)

    def get_preview_mode(self, obj):
        return True

    def get_user_attempt_count(self, obj):
        """Get the number of attempts the current user has made"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.get_attempt_count(request.user)
        return 0

    def get_user_remaining_attempts(self, obj):
        """Get remaining attempts for the current user"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.get_user_remaining_attempts(request.user)
        return 3

    def get_total_attempts_count(self, obj):
        """Get total number of attempts by all users"""
        return obj.attempts.count()

    def get_questions(self, obj):
        """Get 1/3 random questions without answers"""
        all_questions = list(obj.questions.all())
        # If no questions exist → return empty list
        if not all_questions:
            return []

        total_count = len(all_questions)
        preview_count = max(1, total_count // 3)

        # Get random sample
        preview_questions = random.sample(all_questions, preview_count)

        return QuizQuestionPreviewSerializer(
            preview_questions,
            many=True
        ).data


# ========== USER QUIZ DETAIL SERIALIZERS (Full Access for Owner) ==========

class AnswerOptionFullSerializer(serializers.ModelSerializer):
    """Serializer for answer options with correct/incorrect info (for owner)"""

    class Meta:
        model = QuizAnswerOption
        fields = ['id', 'option_text', 'is_correct']


class QuestionWithAnswersSerializer(serializers.ModelSerializer):
    """Serializer for questions with all answer options (for owner)"""
    answer_options = AnswerOptionFullSerializer(many=True, read_only=True)
    correct_answers = serializers.SerializerMethodField()
    incorrect_answers = serializers.SerializerMethodField()

    class Meta:
        model = QuizQuestion
        fields = ['id', 'question_text', 'answer_options', 'correct_answers', 'incorrect_answers']

    def get_correct_answers(self, obj):
        """Return list of correct answer texts"""
        return [opt.option_text for opt in obj.answer_options.all() if opt.is_correct]

    def get_incorrect_answers(self, obj):
        """Return list of incorrect answer texts"""
        return [opt.option_text for opt in obj.answer_options.all() if not opt.is_correct]


class UserQuizDetailSerializer(serializers.ModelSerializer):
    """Serializer for full quiz details - shows all questions with answers for owner"""
    questions = QuestionWithAnswersSerializer(many=True, read_only=True)
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    total_questions = serializers.SerializerMethodField()

    # NEW: Add these fields
    user_attempt_count = serializers.SerializerMethodField()
    user_remaining_attempts = serializers.SerializerMethodField()
    total_attempts_count = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            'id', 'title', 'description', 'language', 'rating', 'rating_count',  # Added rating_count
            'subject', 'quiz_type', 'quiz_type_display', 'questions', 'created_by',
            'created_at', 'total_questions',
            'user_attempt_count', 'user_remaining_attempts', 'total_attempts_count'  # NEW fields
        ]

    def get_total_questions(self, obj):
        return obj.questions.count()

    def get_user_attempt_count(self, obj):
        """Get the number of attempts the current user has made"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.get_attempt_count(request.user)
        return 0

    def get_user_remaining_attempts(self, obj):
        """Get remaining attempts for the current user"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.get_user_remaining_attempts(request.user)
        return 3

    def get_total_attempts_count(self, obj):
        """Get total number of attempts by all users"""
        return obj.attempts.count()

# ========== OTHER SERIALIZERS ==========

class QuizListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for quiz list - excludes questions"""
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    question_count = serializers.SerializerMethodField()
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'language', 'rating', 'subject', 'quiz_type', 'quiz_type_display', 'question_count', 'created_by', 'created_at']

    def get_question_count(self, obj):
        return obj.questions.count()


class GenerateAIQuizSerializer(serializers.Serializer):
    """Serializer for generating AI quiz WITHOUT saving to database"""
    subject_id = serializers.UUIDField(required=False, allow_null=True)
    num_questions = serializers.IntegerField(required=False, default=10, min_value=5, max_value=20)
    language = serializers.CharField(required=False, default='English', max_length=50)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)
    options_per_question = serializers.IntegerField(required=False, default=4, min_value=2, max_value=10)
    correct_answers_per_question = serializers.IntegerField(required=False, default=1, min_value=1)

    def validate_subject_id(self, value):
        if value is not None:
            try:
                Subject.objects.get(id=value)
            except Subject.DoesNotExist:
                raise serializers.ValidationError("Subject with this ID does not exist.")
        return value

    def validate_num_questions(self, value):
        if value < 5 or value > 20:
            raise serializers.ValidationError("Number of questions must be between 5 and 20.")
        return value

    def validate_language(self, value):
        if not value or len(value.strip()) == 0:
            raise serializers.ValidationError("Language cannot be empty.")
        return value.strip()

    def validate_description(self, value):
        if value:
            return value.strip()
        return value

    def validate_options_per_question(self, value):
        if value < 2 or value > 10:
            raise serializers.ValidationError("Options per question must be between 2 and 10.")
        return value

    def validate(self, data):
        """Validate that correct_answers_per_question < options_per_question"""
        options = data.get('options_per_question', 4)
        correct = data.get('correct_answers_per_question', 1)

        if correct >= options:
            raise serializers.ValidationError({
                "correct_answers_per_question": f"Must be less than options_per_question ({options})"
            })

        # Validate 2/3 rule
        if correct >= (options * 2) / 3:
            raise serializers.ValidationError({
                "correct_answers_per_question": f"Must be less than {int((options * 2) / 3)} (2/3 of {options} options)"
            })

        return data


class SaveGeneratedQuizSerializer(serializers.Serializer):
    """Serializer for saving a generated quiz to database"""
    subject_id = serializers.UUIDField(required=True)
    quiz_data = serializers.JSONField(required=True)
    num_questions = serializers.IntegerField(required=True, min_value=5, max_value=20)
    language = serializers.CharField(required=True, max_length=50)
    options_per_question = serializers.IntegerField(required=True, min_value=2, max_value=10)
    correct_answers_per_question = serializers.IntegerField(required=True, min_value=1)

    def validate_subject_id(self, value):
        try:
            Subject.objects.get(id=value)
        except Subject.DoesNotExist:
            raise serializers.ValidationError("Subject with this ID does not exist.")
        return value

    def validate_quiz_data(self, value):
        """Validate quiz_data structure"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("quiz_data must be a dictionary")

        required_fields = ['title', 'description', 'questions']
        for field in required_fields:
            if field not in value:
                raise serializers.ValidationError(f"quiz_data must contain '{field}' field")

        if not isinstance(value['questions'], list):
            raise serializers.ValidationError("questions must be a list")

        if len(value['questions']) == 0:
            raise serializers.ValidationError("questions list cannot be empty")

        # Validate each question structure
        for idx, question in enumerate(value['questions']):
            if not isinstance(question, dict):
                raise serializers.ValidationError(f"Question {idx} must be a dictionary")

            required_q_fields = ['question', 'correct_answers', 'incorrect_answers']
            for field in required_q_fields:
                if field not in question:
                    raise serializers.ValidationError(f"Question {idx} must contain '{field}' field")

        return value

    def validate(self, data):
        """Cross-field validation"""
        options = data.get('options_per_question')
        correct = data.get('correct_answers_per_question')

        if correct >= options:
            raise serializers.ValidationError({
                "correct_answers_per_question": f"Must be less than options_per_question ({options})"
            })

        return data


class SubmitQuizAnswerSerializer(serializers.Serializer):
    """Serializer for individual quiz answer submission"""
    question_id = serializers.UUIDField()
    selected_option_id = serializers.UUIDField()


class SubmitQuizSerializer(serializers.Serializer):
    """Serializer for submitting quiz answers"""
    answers = SubmitQuizAnswerSerializer(many=True)
    duration_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    def validate_answers(self, value):
        if not value:
            raise serializers.ValidationError("At least one answer must be provided.")
        return value

    def validate_duration_seconds(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Duration must be a positive number.")
        return value


class QuizAttemptSerializer(serializers.ModelSerializer):
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    can_rate = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttempt
        fields = ['id', 'quiz_title', 'score', 'duration_seconds','rating', 'can_rate', 'created_at']

    def get_can_rate(self, obj):
        """Check if this attempt can be rated (rating is None)"""
        return obj.rating is None


class QuizAttemptAnswerSerializer(serializers.ModelSerializer):
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    selected_option_text = serializers.CharField(source='selected_option.option_text', read_only=True)
    correct_answer_text = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttemptAnswer
        fields = ['id', 'question_text', 'selected_option_text', 'correct_answer_text', 'is_correct']

    def get_correct_answer_text(self, obj):
        correct_option = obj.question.answer_options.filter(is_correct=True).first()
        return correct_option.option_text if correct_option else None


class QuizAttemptDetailSerializer(serializers.ModelSerializer):
    answers = QuizAttemptAnswerSerializer(many=True, read_only=True)
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    quiz_id = serializers.CharField(source='quiz.id', read_only=True)
    total_questions = serializers.SerializerMethodField()
    can_rate = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz_id', 'quiz_title', 'score', 'total_questions',
            'duration_seconds', 'rating', 'can_rate',
            'created_at', 'answers'
        ]

    def get_total_questions(self, obj):
        return obj.answers.count()

    def get_can_rate(self, obj):
        """Check if this attempt can still be rated"""
        return obj.can_rate()

class UserQuizAttemptsSerializer(serializers.ModelSerializer):
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    quiz_id = serializers.CharField(source='quiz.id', read_only=True)

    class Meta:
        model = QuizAttempt
        fields = ['id', 'quiz_id', 'quiz_title', 'score', 'duration_seconds', 'created_at']


class CreateQuizSerializer(serializers.ModelSerializer):
    """Serializer for creating a new quiz (used for both manual and import)"""
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'subject', 'language', 'created_by']
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True}
        }

    def validate_subject(self, value):
        """Validate subject exists"""
        if value is None:
            raise serializers.ValidationError("Subject is required")
        return value


class AnswerOptionInputSerializer(serializers.Serializer):
    """Serializer for individual answer option"""
    option_text = serializers.CharField(max_length=500)
    is_correct = serializers.BooleanField()

    def validate_option_text(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Option text cannot be empty")
        return value.strip()


class ManualQuestionInputSerializer(serializers.Serializer):
    """Serializer for a single question input"""
    question_text = serializers.CharField(max_length=1000)
    answer_options = AnswerOptionInputSerializer(many=True)

    def validate_question_text(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Question text cannot be empty")
        return value.strip()

    def validate_answer_options(self, value):
        if not value or len(value) < 2:
            raise serializers.ValidationError("At least 2 answer options are required")

        if len(value) > 10:
            raise serializers.ValidationError("Maximum 10 answer options allowed")

        # Check if at least one option is correct
        correct_count = sum(1 for option in value if option['is_correct'])
        if correct_count < 1:
            raise serializers.ValidationError("At least one option must be marked as correct")

        # Check correct answers ratio (must be ≤ 50% of total)
        max_correct = len(value) // 2
        if correct_count > max_correct:
            raise serializers.ValidationError(
                f"Too many correct answers. Maximum {max_correct} correct answers allowed for {len(value)} total options (must be ≤ 50%)"
            )

        # Check for duplicate options
        option_texts = [opt['option_text'] for opt in value]
        if len(option_texts) != len(set(option_texts)):
            raise serializers.ValidationError("Duplicate answer options are not allowed")

        return value


class AddManualQuestionsSerializer(serializers.Serializer):
    """Serializer for adding multiple questions at once"""
    questions = ManualQuestionInputSerializer(many=True)

    def validate_questions(self, value):
        if not value or len(value) == 0:
            raise serializers.ValidationError("At least one question is required")

        if len(value) > 50:
            raise serializers.ValidationError("Maximum 50 questions allowed per request")

        return value


class ImportQuestionsFromExcelSerializer(serializers.Serializer):
    """Serializer for importing questions from Excel file"""
    file = serializers.FileField()

    def validate_file(self, value):
        """Validate file is Excel format"""
        allowed_extensions = ['xlsx', 'xls']
        file_extension = value.name.split('.')[-1].lower()

        if file_extension not in allowed_extensions:
            raise serializers.ValidationError(
                f"Invalid file format. Supported formats: {', '.join(allowed_extensions)}"
            )

        # Check file size (max 5MB)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("File size must not exceed 5MB")

        return value


# ===================== UNIFIED QUIZ EDIT SERIALIZER =====================

class UnifiedAnswerOptionSerializer(serializers.Serializer):
    """Serializer for answer options in unified edit"""
    id = serializers.UUIDField(required=False, allow_null=True)  # None for new options
    option_text = serializers.CharField(max_length=500)
    is_correct = serializers.BooleanField()
    _action = serializers.ChoiceField(
        choices=['keep', 'update', 'delete', 'create'],
        required=False,
        default='keep'
    )

    def validate_option_text(self, value):
        """Validate option text"""
        if not value or not value.strip():
            raise serializers.ValidationError("Option text cannot be empty")
        return value.strip()


class UnifiedQuestionSerializer(serializers.Serializer):
    """Serializer for questions in unified edit"""
    id = serializers.UUIDField(required=False, allow_null=True)  # None for new questions
    question_text = serializers.CharField(max_length=1000)
    answer_options = UnifiedAnswerOptionSerializer(many=True)
    _action = serializers.ChoiceField(
        choices=['keep', 'update', 'delete', 'create'],
        required=False,
        default='keep'
    )

    def validate_question_text(self, value):
        """Validate question text"""
        if not value or not value.strip():
            raise serializers.ValidationError("Question text cannot be empty")
        return value.strip()

    def validate_answer_options(self, value):
        """Validate answer options"""
        if not value or len(value) < 2:
            raise serializers.ValidationError("At least 2 answer options are required")

        if len(value) > 10:
            raise serializers.ValidationError("Maximum 10 answer options allowed")

        # Check if at least one option is correct
        if not any(option.get('is_correct', False) for option in value):
            raise serializers.ValidationError("At least one option must be marked as correct")

        # Check for duplicate options
        option_texts = [opt['option_text'] for opt in value]
        if len(option_texts) != len(set(option_texts)):
            raise serializers.ValidationError("Duplicate answer options are not allowed")

        return value


class UnifiedEditQuizSerializer(serializers.Serializer):
    """
    Unified serializer for editing quiz, questions, and answer options in one API call

    This allows you to:
    - Edit quiz metadata (title, description, subject, language)
    - Add/Update/Delete questions
    - Add/Update/Delete answer options

    All in a single API request!
    """
    # Quiz fields (optional - only include fields you want to update)
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    subject_id = serializers.UUIDField(required=False)
    language = serializers.CharField(max_length=50, required=False)

    # Questions (optional - include to modify questions)
    questions = UnifiedQuestionSerializer(many=True, required=False)

    def validate_title(self, value):
        """Validate title if provided"""
        if value is not None:
            if not value or not value.strip():
                raise serializers.ValidationError("Title cannot be empty")
            return value.strip()
        return value

    def validate_description(self, value):
        """Validate description if provided"""
        if value is not None:
            return value.strip() if value else ""
        return value

    def validate_subject_id(self, value):
        """Validate subject exists if provided"""
        if value is not None:
            try:
                Subject.objects.get(id=value)
            except Subject.DoesNotExist:
                raise serializers.ValidationError("Subject does not exist")
        return value

    def validate_language(self, value):
        """Validate language if provided"""
        if value is not None:
            if not value or not value.strip():
                raise serializers.ValidationError("Language cannot be empty")
            return value.strip()
        return value

    def validate_questions(self, value):
        """Validate questions if provided"""
        if value:
            # Ensure at least one question is not marked for deletion
            non_deleted = [q for q in value if q.get('_action') != 'delete']
            if not non_deleted:
                raise serializers.ValidationError("Quiz must have at least one question")
        return value

    def update(self, instance, validated_data):
        """
        Update quiz, questions, and answer options

        Handles:
        - Quiz metadata updates
        - Question CRUD operations
        - Answer option CRUD operations
        """
        from django.db import transaction

        with transaction.atomic():
            # ========== UPDATE QUIZ METADATA ==========
            if 'title' in validated_data:
                instance.title = validated_data['title']

            if 'description' in validated_data:
                instance.description = validated_data['description']

            if 'subject_id' in validated_data:
                instance.subject = Subject.objects.get(id=validated_data['subject_id'])

            if 'language' in validated_data:
                instance.language = validated_data['language']

            instance.save()

            # ========== PROCESS QUESTIONS ==========
            if 'questions' in validated_data:
                questions_data = validated_data['questions']

                for question_data in questions_data:
                    action = question_data.get('_action', 'keep')
                    question_id = question_data.get('id')

                    if action == 'delete' and question_id:
                        # DELETE existing question
                        QuizQuestion.objects.filter(id=question_id, quiz=instance).delete()

                    elif action == 'create':
                        # CREATE new question
                        question = QuizQuestion.objects.create(
                            quiz=instance,
                            question_text=question_data['question_text']
                        )

                        # Create answer options for new question
                        for option_data in question_data['answer_options']:
                            QuizAnswerOption.objects.create(
                                question=question,
                                option_text=option_data['option_text'],
                                is_correct=option_data['is_correct']
                            )

                    elif action in ['update', 'keep'] and question_id:
                        # UPDATE existing question
                        try:
                            question = QuizQuestion.objects.get(id=question_id, quiz=instance)

                            # Update question text if changed
                            if 'question_text' in question_data:
                                question.question_text = question_data['question_text']
                                question.save()

                            # Process answer options
                            if 'answer_options' in question_data:
                                answer_options_data = question_data['answer_options']

                                for option_data in answer_options_data:
                                    option_action = option_data.get('_action', 'keep')
                                    option_id = option_data.get('id')

                                    if option_action == 'delete' and option_id:
                                        # DELETE existing option
                                        QuizAnswerOption.objects.filter(
                                            id=option_id,
                                            question=question
                                        ).delete()

                                    elif option_action == 'create':
                                        # CREATE new option
                                        QuizAnswerOption.objects.create(
                                            question=question,
                                            option_text=option_data['option_text'],
                                            is_correct=option_data['is_correct']
                                        )

                                    elif option_action in ['update', 'keep'] and option_id:
                                        # UPDATE existing option
                                        try:
                                            option = QuizAnswerOption.objects.get(
                                                id=option_id,
                                                question=question
                                            )
                                            option.option_text = option_data['option_text']
                                            option.is_correct = option_data['is_correct']
                                            option.save()
                                        except QuizAnswerOption.DoesNotExist:
                                            pass  # Skip if option doesn't exist

                        except QuizQuestion.DoesNotExist:
                            pass  # Skip if question doesn't exist

        return instance


class RateQuizSerializer(serializers.Serializer):
    """Serializer for rating a quiz attempt"""
    rating = serializers.DecimalField(
        max_digits=2,
        decimal_places=1,
        min_value=0,
        max_value=5,
        help_text="Rating from 0 to 5 (e.g., 4.5)"
    )

    def validate_rating(self, value):
        """Validate rating is in 0.5 increments"""
        if (value * 10) % 5 != 0:
            raise serializers.ValidationError(
                "Rating must be in 0.5 increments (e.g., 0, 0.5, 1.0, 1.5, ..., 5.0)"
            )
        return value


class QuizAttemptWithRatingSerializer(serializers.ModelSerializer):
    """Enhanced QuizAttempt serializer with rating info"""
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    attempt_number = serializers.SerializerMethodField()
    can_rate = serializers.SerializerMethodField()
    remaining_attempts = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz_title', 'score', 'duration_seconds',
            'rating', 'attempt_number', 'can_rate',
            'remaining_attempts', 'created_at'
        ]

    def get_attempt_number(self, obj):
        """Get which attempt number this is (1st, 2nd, 3rd)"""
        return obj.get_attempt_number()

    def get_can_rate(self, obj):
        """Check if this attempt can be rated"""
        return obj.can_rate()

    def get_remaining_attempts(self, obj):
        """Get remaining attempts for this quiz"""
        return obj.quiz.get_user_remaining_attempts(obj.user)


class QuizWithRatingSerializer(serializers.ModelSerializer):
    """Quiz serializer with rating information"""
    questions = serializers.SerializerMethodField()
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    user_attempt_count = serializers.SerializerMethodField()
    user_can_attempt = serializers.SerializerMethodField()
    user_remaining_attempts = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            'id', 'title', 'description', 'language', 'subject',
            'quiz_type', 'quiz_type_display', 'rating', 'rating_count',
            'questions', 'created_by', 'created_at',
            'user_attempt_count', 'user_can_attempt', 'user_remaining_attempts'
        ]

    def get_questions(self, obj):
        """Return question count"""
        return obj.questions.count()

    def get_subject(self, obj):
        """Return subject info"""
        return {
            'id': str(obj.subject.id),
            'name': obj.subject.name,
            'description': obj.subject.description
        }

    def get_created_by(self, obj):
        """Return creator info"""
        if obj.created_by:
            return {
                'id': str(obj.created_by.id),
                'username': obj.created_by.username,
                'full_name': getattr(obj.created_by, 'full_name', '')
            }
        return None

    def get_user_attempt_count(self, obj):
        """Get user's attempt count for this quiz"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.get_attempt_count(request.user)
        return 0

    def get_user_can_attempt(self, obj):
        """Check if user can attempt this quiz"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.can_user_attempt(request.user)
        return False

    def get_user_remaining_attempts(self, obj):
        """Get user's remaining attempts"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.get_user_remaining_attempts(request.user)
        return 0


class QuizRatingStatsSerializer(serializers.Serializer):
    """Serializer for quiz rating statistics"""
    quiz_id = serializers.UUIDField()
    quiz_title = serializers.CharField()
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=2)
    rating_count = serializers.IntegerField()
    rating_distribution = serializers.DictField()
    user_ratings = serializers.ListField()