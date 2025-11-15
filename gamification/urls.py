# gamification/urls.py
from django.urls import path
from .views import UserMissionsView

app_name = 'gamification'

urlpatterns = [
    path('missions/', UserMissionsView.as_view(), name='user_missions'),
]