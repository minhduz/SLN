# gamification/urls.py
from django.urls import path
from .views import UserMissionsView,UserSquadMissionsView

app_name = 'gamification'

urlpatterns = [
    path('missions/', UserMissionsView.as_view(), name='user_missions'),
    path('squad-missions/', UserSquadMissionsView.as_view(), name='user-squad-missions'),
]