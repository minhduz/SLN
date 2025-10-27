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

    class Meta:
        model = QuizQuestion
        fields = ['id', 'question_text', 'answer_options']


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['id', 'name', 'description']

class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model (basic info only)"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name', 'avatar','role']
        read_only_fields = ['id']

class QuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)  # ✅ NEW: Added creator info

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'language', 'subject', 'quiz_type', 'quiz_type_display', 'questions','created_by','created_at']


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

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'language', 'subject', 'quiz_type',
                  'quiz_type_display', 'questions', 'created_by', 'created_at',
                  'total_questions', 'preview_questions_count', 'preview_mode']

    def get_total_questions(self, obj):
        return obj.questions.count()

    def get_preview_questions_count(self, obj):
        total = obj.questions.count()
        return max(1, total // 3)

    def get_preview_mode(self, obj):
        return True

    def get_questions(self, obj):
        """Get 1/3 random questions without answers"""
        all_questions = list(obj.questions.all())
        total_count = len(all_questions)
        preview_count = max(1, total_count // 3)

        # Get random sample
        preview_questions = random.sample(all_questions, preview_count)

        return QuizQuestionPreviewSerializer(
            preview_questions,
            many=True
        ).data

class QuizListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for quiz list - excludes questions"""
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    question_count = serializers.SerializerMethodField()
    created_by = UserSerializer(read_only=True)  # ✅ NEW: Added creator info

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'language', 'subject', 'quiz_type', 'quiz_type_display', 'question_count','created_by','created_at']

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

    class Meta:
        model = QuizAttempt
        fields = ['id', 'quiz_title', 'score', 'duration_seconds', 'created_at']


class QuizAttemptAnswerSerializer(serializers.ModelSerializer):
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    selected_option_text = serializers.CharField(source='selected_option.option_text', read_only=True)
    correct_answer_text = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttemptAnswer
        fields = ['question_text', 'selected_option_text', 'correct_answer_text', 'is_correct']

    def get_correct_answer_text(self, obj):
        correct_option = obj.question.answer_options.filter(is_correct=True).first()
        return correct_option.option_text if correct_option else None


class QuizAttemptDetailSerializer(serializers.ModelSerializer):
    answers = QuizAttemptAnswerSerializer(many=True, read_only=True)
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    quiz_id = serializers.CharField(source='quiz.id', read_only=True)
    total_questions = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz_id', 'quiz_title', 'score', 'total_questions',
            'duration_seconds',
            'created_at', 'answers'
        ]

    def get_total_questions(self, obj):
        return obj.answers.count()


class UserQuizAttemptsSerializer(serializers.ModelSerializer):
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    quiz_id = serializers.CharField(source='quiz.id', read_only=True)

    class Meta:
        model = QuizAttempt
        fields = ['id', 'quiz_id', 'quiz_title', 'score', 'duration_seconds', 'created_at']


class CreateQuizSerializer(serializers.ModelSerializer):
    """Serializer for creating a new quiz (used for both manual and import)"""
    created_by=UserSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'subject', 'language','created_by']
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


class AddManualQuestionSerializer(serializers.Serializer):
    """Serializer for adding a single question manually"""
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
        if not any(option['is_correct'] for option in value):
            raise serializers.ValidationError("At least one option must be marked as correct")

        # Check for duplicate options
        option_texts = [opt['option_text'] for opt in value]
        if len(option_texts) != len(set(option_texts)):
            raise serializers.ValidationError("Duplicate answer options are not allowed")

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