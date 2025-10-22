from django.urls import path
from . import views


urlpatterns = [
    # Quiz generation and listing
    path('quiz/generate-ai/', views.GenerateAIQuizView.as_view(), name='generate-ai-quiz'),
    path('quiz/', views.QuizListView.as_view(), name='quiz-list'),

    # Quiz detail and questions
    path('quiz/<uuid:quiz_id>/', views.QuizDetailView.as_view(), name='quiz-detail'),
    path('quiz/<uuid:quiz_id>/questions/', views.QuizQuestionListView.as_view(), name='quiz-questions'),

    # Quiz submission
    path('quiz/<uuid:quiz_id>/submit/', views.SubmitQuizView.as_view(), name='submit-quiz'),

    # Quiz attempts
    path('quiz/attempts/', views.UserQuizAttemptsView.as_view(), name='user-attempts'),
    path('quiz/attempt/<uuid:attempt_id>/', views.QuizAttemptDetailView.as_view(), name='attempt-detail'),


    path('quiz/create/', views.CreateQuizView.as_view(), name='create-quiz'),
    path('quiz/<uuid:quiz_id>/add-manual-question/', views.AddManualQuestionView.as_view(), name='add-manual-question'),
    path('quiz/<uuid:quiz_id>/import-questions-from-excel/', views.ImportQuestionsFromExcelView.as_view(), name='import-questions-excel'),

    # ======================== QUIZ EDIT & DELETE ========================
    path('quiz/<uuid:quiz_id>/edit/', views.EditQuizView.as_view(), name='edit-quiz'),
    path('quiz/<uuid:quiz_id>/delete/', views.DeleteQuizView.as_view(), name='delete-quiz'),

    # ======================== QUESTION EDIT & DELETE ========================
    path('quiz/<uuid:quiz_id>/question/<uuid:question_id>/edit/', views.EditQuestionView.as_view(), name='edit-question'),
    path('quiz/<uuid:quiz_id>/question/<uuid:question_id>/delete/', views.DeleteQuestionView.as_view(),
         name='delete-question'),

    # ======================== ANSWER OPTION EDIT & DELETE ========================
    path('quiz/<uuid:quiz_id>/question/<uuid:question_id>/option/<uuid:option_id>/edit/',
         views.EditAnswerOptionView.as_view(), name='edit-answer-option'),
    path('quiz/<uuid:quiz_id>/question/<uuid:question_id>/option/<uuid:option_id>/delete/',
         views.DeleteAnswerOptionView.as_view(), name='delete-answer-option'),
]