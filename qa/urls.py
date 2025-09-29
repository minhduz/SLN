from django.urls import path
from .views import (SimilarQuestionsView,
                    VectorSearchStatsView,
                    TempCreateQuestionView,
                    TempQuestionStatusView,
                    TempBulkCreateQuestionsView,
                    ChatWithBotView,
                    GetConversationStatusView,
                    ClearConversationView,
                    SaveConversationView,
                    AnswerListCreateView,
                    AnswerDetailView,
                    VerifyAnswerView,
                    DisproveAnswerView,
                    RandomQuestionsView,
                    QuestionsBySubjectView,
                    QuestionView,
                    QuestionVisibilityView,
                    UserQuestionViewAPI)

# Phase 1: Vector Similarity Search URLs
urlpatterns = [
    # Main endpoint for similar questions search (Steps 0.1-0.3)
    path('similar-questions/', SimilarQuestionsView.as_view(), name='phase1-similar-questions'),
    # Statistics endpoint for vector search database
    path('stats/', VectorSearchStatsView.as_view(), name='phase1-stats'),

    # Chat endpoint
    path('chat/', ChatWithBotView.as_view(), name='chat'),
    path('get-conversation-status/', GetConversationStatusView.as_view(), name='get-conversation-status'),
    path('clear-conversation/', ClearConversationView.as_view(), name='clear-conversation'),
    path('save-conversation/', SaveConversationView.as_view(), name='save-conversation'),

    # Answer endpoint
    path('answer/', AnswerListCreateView.as_view(), name='answer'),
    path('answer-detail/', AnswerDetailView.as_view(), name='answer-detail'),

    # Question endpoint
    path('verify-answer/', VerifyAnswerView.as_view(), name='verify-answer'),
    path('disprove-answer/', DisproveAnswerView.as_view(), name='disprove-answer'),
    path('questions/random/', RandomQuestionsView.as_view(), name='random-questions'),
    path('questions/subject/', QuestionsBySubjectView.as_view(), name='questions-subject'),
    path('question/', QuestionView.as_view(), name='question'),
    path('question-visibility/', QuestionVisibilityView.as_view(), name='question-visibility'),
    path('view-question/', UserQuestionViewAPI.as_view(), name='view-question'),

    # Temporary testing endpoints
    path('temp/create-question/', TempCreateQuestionView.as_view(), name='temp-create-question'),
    path('temp/question-status/<uuid:question_id>/', TempQuestionStatusView.as_view(), name='temp-question-status'),
    path('temp/bulk-create-questions/', TempBulkCreateQuestionsView.as_view(), name='temp-bulk-create-questions'),
]