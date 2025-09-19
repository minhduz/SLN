from rest_framework import serializers
from .models import Subject, Question, Answer, QuestionFileAttachment, AnswerVerification, UserQuestionView
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model (basic info only)"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name']
        read_only_fields = ['id']


class SubjectSerializer(serializers.ModelSerializer):
    """Serializer for Subject model"""
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ['id', 'name', 'description', 'question_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'question_count']

    def get_question_count(self, obj):
        return obj.questions.count()


class QuestionDataSerializer(serializers.Serializer):
    """Serializer for question data in search results"""

    id = serializers.UUIDField()
    title = serializers.CharField()
    body = serializers.CharField()
    subject_name = serializers.CharField(allow_null=True)
    subject_id = serializers.UUIDField(allow_null=True)
    user_name = serializers.CharField()
    popularity_score = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    answer_count = serializers.IntegerField()
    is_public = serializers.BooleanField()


class SimilarQuestionResultSerializer(serializers.Serializer):
    """Serializer for individual similar question result"""

    similarity = serializers.FloatField()
    question_data = QuestionDataSerializer()


class VectorSearchRequestSerializer(serializers.Serializer):
    """Serializer for vector search request validation"""

    q = serializers.CharField(
        max_length=1000,
        min_length=3,
        help_text="The query text to search for similar questions"
    )
    limit = serializers.IntegerField(
        default=10,
        min_value=1,
        max_value=50,
        help_text="Maximum number of results to return"
    )
    min_similarity = serializers.FloatField(
        default=0.7,
        min_value=0.0,
        max_value=1.0,
        help_text="Minimum similarity threshold (0.0 to 1.0)"
    )
    include_private = serializers.BooleanField(
        default=False,
        help_text="Include private questions in search results"
    )
    use_pgvector = serializers.BooleanField(
        default=True,
        help_text="Use pgvector for search (faster for large datasets)"
    )


class VectorSearchResponseSerializer(serializers.Serializer):
    """Serializer for vector search response"""

    success = serializers.BooleanField()
    query = serializers.CharField()
    count = serializers.IntegerField()
    results = SimilarQuestionResultSerializer(many=True)
    search_params = serializers.DictField()
    error = serializers.CharField(required=False)


class CreateQuestionSerializer(serializers.ModelSerializer):
    """Temporary serializer for creating questions with async embedding generation"""

    subject_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = Question
        fields = ['title', 'body', 'subject_id', 'is_public']

    def validate_title(self, value):
        """Validate question title"""
        if not value or not value.strip():
            raise serializers.ValidationError("Title cannot be empty")

        if len(value.strip()) < 5:
            raise serializers.ValidationError("Title must be at least 5 characters long")

        if len(value) > 200:
            raise serializers.ValidationError("Title cannot exceed 200 characters")

        return value.strip()

    def validate_body(self, value):
        """Validate question body"""
        if not value or not value.strip():
            raise serializers.ValidationError("Question body cannot be empty")

        if len(value.strip()) < 10:
            raise serializers.ValidationError("Question body must be at least 10 characters long")

        if len(value) > 5000:
            raise serializers.ValidationError("Question body cannot exceed 5000 characters")

        return value.strip()

    def validate_subject_id(self, value):
        """Validate subject exists if provided"""
        if value:
            try:
                Subject.objects.get(id=value)
            except Subject.DoesNotExist:
                raise serializers.ValidationError("Subject not found")
        return value


class QuestionCreatedResponseSerializer(serializers.Serializer):
    """Serializer for question creation response"""

    success = serializers.BooleanField()
    question = serializers.DictField()
    message = serializers.CharField()
    embedding_task_id = serializers.CharField(required=False)


class QuestionFileAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for Question File Attachments"""
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()

    class Meta:
        model = QuestionFileAttachment
        fields = ['id', 'file', 'file_url', 'file_name', 'created_at']
        read_only_fields = ['id', 'created_at', 'file_url', 'file_name']

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None

    def get_file_name(self, obj):
        if obj.file:
            return obj.file.name.split('/')[-1]
        return None


class AnswerVerificationSerializer(serializers.ModelSerializer):
    """Serializer for Answer Verification"""
    verified_by = UserSerializer(read_only=True)

    class Meta:
        model = AnswerVerification
        fields = ['id', 'verified_by', 'is_verified', 'created_at']
        read_only_fields = ['id', 'created_at']


class AnswerSerializer(serializers.ModelSerializer):
    """Serializer for Answer model"""
    user = UserSerializer(read_only=True)
    verifications = AnswerVerificationSerializer(many=True, read_only=True)
    verification_count = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = Answer
        fields = [
            'id', 'user', 'content', 'is_ai_generated',
            'verifications', 'verification_count', 'is_verified',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_verification_count(self, obj):
        return obj.verifications.filter(is_verified=True).count()

    def get_is_verified(self, obj):
        return obj.verifications.filter(is_verified=True).exists()

class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for Question model"""
    user = UserSerializer(read_only=True)
    subject = SubjectSerializer(read_only=True)
    subject_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    attachments = QuestionFileAttachmentSerializer(many=True, read_only=True)
    answers = AnswerSerializer(many=True, read_only=True)
    answer_count = serializers.SerializerMethodField()
    view_count = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = [
            'id', 'user', 'subject', 'subject_id', 'title', 'body',
            'is_public', 'popularity_score', 'attachments', 'answers',
            'answer_count', 'view_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'popularity_score', 'created_at', 'updated_at']

    def get_answer_count(self, obj):
        return obj.answers.count()

    def get_view_count(self, obj):
        return obj.views.count()

    def create(self, validated_data):
        # Remove subject_id from validated_data and handle it separately
        subject_id = validated_data.pop('subject_id', None)

        # Set the user from the request context
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['user'] = request.user

        # Handle subject assignment
        if subject_id:
            try:
                subject = Subject.objects.get(id=subject_id)
                validated_data['subject'] = subject
            except Subject.DoesNotExist:
                raise serializers.ValidationError({'subject_id': 'Invalid subject ID'})

        return super().create(validated_data)


class UserQuestionViewSerializer(serializers.ModelSerializer):
    """Serializer for User Question Views"""
    user = UserSerializer(read_only=True)
    question = serializers.StringRelatedField()

    class Meta:
        model = UserQuestionView
        fields = ['id', 'user', 'question', 'created_at']
        read_only_fields = ['id', 'created_at']

# =============================================================================
# CHATBOT SERIALIZERS
# =============================================================================

class ChatMessageSerializer(serializers.Serializer):
    """Serializer for chat messages"""
    message = serializers.CharField(max_length=5000, required=True)
    thread_id = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_message(self, value):
        if not value.strip():
            raise serializers.ValidationError("Message cannot be empty")
        return value.strip()


class TokenStatusSerializer(serializers.Serializer):
    """Serializer for token status details"""
    current_tokens = serializers.IntegerField()
    max_tokens = serializers.IntegerField()
    warning_threshold = serializers.IntegerField()
    critical_threshold = serializers.IntegerField()
    usage_percentage = serializers.FloatField()
    status = serializers.ChoiceField(choices=['normal', 'warning', 'critical'])
    should_start_new_chat = serializers.BooleanField()
    warning_message = serializers.CharField(allow_null=True, required=False)


class TokenInfoSerializer(serializers.Serializer):
    """Serializer for token information"""
    message_tokens = serializers.IntegerField()
    conversation_tokens = serializers.IntegerField()
    total_tokens = serializers.IntegerField(required=False)
    token_status = TokenStatusSerializer()


class ChatResponseSerializer(serializers.Serializer):
    """Serializer for chat responses with token information"""
    message = serializers.CharField()
    response = serializers.CharField()
    thread_id = serializers.CharField()
    status = serializers.CharField()
    timestamp = serializers.DateTimeField()
    token_info = TokenInfoSerializer(required=False)
    action_required = serializers.CharField(required=False)


class ConversationStateSerializer(serializers.Serializer):
    """Serializer for conversation state with token information"""
    summary = serializers.CharField()
    message_count = serializers.IntegerField()
    conversation_tokens = serializers.IntegerField()
    token_status = TokenStatusSerializer()
    status = serializers.CharField()


class SaveQuestionAnswerSerializer(serializers.Serializer):
    """Serializer for saving question-answer pairs"""
    title = serializers.CharField(max_length=255, required=True)
    question_body = serializers.CharField(required=True)
    answer_content = serializers.CharField(required=True)
    subject_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_public = serializers.BooleanField(default=False)
    is_ai_generated = serializers.BooleanField(default=True)

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty")
        return value.strip()

    def validate_question_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Question body cannot be empty")
        return value.strip()

    def validate_answer_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("Answer content cannot be empty")
        return value.strip()