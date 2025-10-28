from django.urls import path
from . import views


urlpatterns = [
    # Quiz generation and listing
    path('quiz/generate-ai/', views.GenerateAIQuizView.as_view(), name='generate-ai-quiz'),
    path('quiz/save-generated/', views.SaveGeneratedQuizView.as_view(), name='save-generated-quiz'),

    path('quiz/random/', views.RandomQuizzesView.as_view(), name='random-quizzes'),
    path('quiz/random/subject/<uuid:subject_id>/', views.RandomQuizzesSubjectView.as_view(), name='random-quizzes-subject'),
    path('quiz/search/', views.SearchQuizzesView.as_view(), name='search-quizzes'),

    # Quiz detail and questions
    path('quiz/<uuid:quiz_id>/', views.QuizDetailView.as_view(), name='quiz-detail'),
    path('quiz/<uuid:quiz_id>/questions/', views.QuizQuestionListView.as_view(), name='quiz-questions'),

    # Quiz submission
    path('quiz/<uuid:quiz_id>/submit/', views.SubmitQuizView.as_view(), name='submit-quiz'),

    # Quiz attempts
    path('quiz/attempts/', views.UserQuizAttemptsView.as_view(), name='user-attempts'),
    path('quiz/attempt/<uuid:attempt_id>/', views.QuizAttemptDetailView.as_view(), name='attempt-detail'),


    path('quiz/create/', views.CreateQuizView.as_view(), name='create-quiz'),
    path('quiz/<uuid:quiz_id>/add-manual-questions/', views.AddManualQuestionsView.as_view(), name='add-manual-question'),
    path('quiz/import-questions-from-excel/', views.ImportQuestionsFromExcelView.as_view(), name='import-questions-excel'),

    # ======================== QUIZ EDIT & DELETE ========================
    path('quiz/<uuid:quiz_id>/edit/', views.EditQuizView.as_view(), name='edit-quiz'),
    path('quiz/<uuid:quiz_id>/delete/', views.DeleteQuizView.as_view(), name='delete-quiz'),
]