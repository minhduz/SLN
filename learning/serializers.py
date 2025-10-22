from rest_framework import serializers
from .models import Quiz, QuizQuestion, QuizAnswerOption, QuizAttempt, QuizAttemptAnswer
from qa.models import Subject
from accounts.models import User


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
        fields = ['id', 'username', 'email', 'full_name', 'avatar']
        read_only_fields = ['id']

class QuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    quiz_type_display = serializers.CharField(source='get_quiz_type_display', read_only=True)
    subject = SubjectSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)  # ✅ NEW: Added creator info

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'language', 'subject', 'quiz_type', 'quiz_type_display', 'questions','created_by','created_at']


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
    """Serializer for generating AI quiz"""
    subject_id = serializers.UUIDField(required=False, allow_null=True)
    num_questions = serializers.IntegerField(required=False, default=10, min_value=1, max_value=20)
    language = serializers.CharField(required=False, default='English', max_length=50)

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


# ===================== QUIZ EDIT/DELETE SERIALIZERS =====================

class EditQuizSerializer(serializers.ModelSerializer):
    """Serializer for editing quiz information"""

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'subject', 'language']
        read_only_fields = ['id']
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'title': {'required': False},
            'subject': {'required': False},
            'language': {'required': False}
        }

    def validate_subject(self, value):
        """Validate subject exists if provided"""
        if value is not None:
            try:
                Subject.objects.get(id=value.id)
            except Subject.DoesNotExist:
                raise serializers.ValidationError("Subject does not exist")
        return value

    def validate_title(self, value):
        """Validate title if provided"""
        if value is not None:
            if not value or not value.strip():
                raise serializers.ValidationError("Title cannot be empty")
        return value

    def validate_language(self, value):
        """Validate language if provided"""
        if value is not None:
            if not value or not value.strip():
                raise serializers.ValidationError("Language cannot be empty")
        return value


# ===================== QUESTION & ANSWER EDIT/DELETE SERIALIZERS =====================

class EditAnswerOptionSerializer(serializers.ModelSerializer):
    """Serializer for editing answer options"""

    class Meta:
        model = QuizAnswerOption
        fields = ['id', 'option_text', 'is_correct']
        read_only_fields = ['id']

    def validate_option_text(self, value):
        """Validate option text"""
        if not value or not value.strip():
            raise serializers.ValidationError("Option text cannot be empty")
        return value.strip()


class EditQuestionSerializer(serializers.ModelSerializer):
    """Serializer for editing quiz questions with answer options"""

    answer_options = EditAnswerOptionSerializer(many=True, required=False)

    class Meta:
        model = QuizQuestion
        fields = ['id', 'question_text', 'answer_options']
        read_only_fields = ['id']

    def validate_question_text(self, value):
        """Validate question text"""
        if not value or not value.strip():
            raise serializers.ValidationError("Question text cannot be empty")
        return value.strip()

    def validate_answer_options(self, value):
        """Validate answer options if provided"""
        if value:
            if len(value) < 2:
                raise serializers.ValidationError("At least 2 answer options are required")

            if len(value) > 10:
                raise serializers.ValidationError("Maximum 10 answer options allowed")

            # Check if at least one option is correct
            if not any(option['is_correct'] for option in value if 'is_correct' in option):
                raise serializers.ValidationError("At least one option must be marked as correct")

            # Check for duplicate options
            option_texts = [opt['option_text'] for opt in value if 'option_text' in opt]
            if len(option_texts) != len(set(option_texts)):
                raise serializers.ValidationError("Duplicate answer options are not allowed")

        return value

    def update(self, instance, validated_data):
        """Update question and its answer options"""
        from django.db import transaction

        answer_options_data = validated_data.pop('answer_options', None)

        # Update question fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update answer options if provided
        if answer_options_data is not None:
            with transaction.atomic():
                # Delete existing options
                instance.answer_options.all().delete()

                # Create new options
                for option_data in answer_options_data:
                    QuizAnswerOption.objects.create(
                        question=instance,
                        option_text=option_data['option_text'],
                        is_correct=option_data['is_correct']
                    )

        return instance


class UpdateAnswerOptionSerializer(serializers.Serializer):
    """Serializer for updating a single answer option"""

    option_text = serializers.CharField(max_length=500, required=False)
    is_correct = serializers.BooleanField(required=False)

    def validate_option_text(self, value):
        """Validate option text if provided"""
        if value is not None:
            if not value or not value.strip():
                raise serializers.ValidationError("Option text cannot be empty")
            return value.strip()
        return value