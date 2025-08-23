from django.urls import path
from .views import RegisterView, CustomTokenObtainPairView, CustomTokenRefreshView, LogoutView, UserProfileView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomTokenObtainPairView.as_view(), name='token'),
    path('refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("users/me", UserProfileView.as_view(), name="user-profile")
]