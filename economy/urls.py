# economy/urls.py
from django.urls import path
from .views import UserCurrenciesView

app_name = 'economy'

urlpatterns = [
    path('currencies/', UserCurrenciesView.as_view(), name='user_currencies'),
]