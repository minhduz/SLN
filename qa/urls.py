from django.urls import path
from .views import (SimilarQuestionsView,
                    VectorSearchStatsView,
                    TempCreateQuestionView,
                    TempQuestionStatusView,
                    TempBulkCreateQuestionsView,
                    ChatWithBotView)

# Phase 1: Vector Similarity Search URLs
urlpatterns = [
    # Main endpoint for similar questions search (Steps 0.1-0.3)
    path('similar-questions/', SimilarQuestionsView.as_view(), name='phase1-similar-questions'),

    # Statistics endpoint for vector search database
    path('stats/', VectorSearchStatsView.as_view(), name='phase1-stats'),

# Temporary testing endpoints
    path('temp/create-question/', TempCreateQuestionView.as_view(), name='temp-create-question'),
    path('temp/question-status/<uuid:question_id>/', TempQuestionStatusView.as_view(), name='temp-question-status'),
    path('temp/bulk-create-questions/', TempBulkCreateQuestionsView.as_view(), name='temp-bulk-create-questions'),
    path('chat/', ChatWithBotView.as_view(), name='chat'),
]