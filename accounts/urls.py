from django.urls import path
from .views import (RegisterView, CustomTokenObtainPairView, CustomTokenRefreshView,
                    LogoutView, UserProfileView, UpdateUserView, SendOTPView,
                    VerifyOTPView, UserSearchView, ChangePasswordView)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomTokenObtainPairView.as_view(), name='token'),
    path('refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("users/me", UserProfileView.as_view(), name="user-profile"),
    path("users/", UpdateUserView.as_view(), name="update-user-profile"),
    path("users/search/", UserSearchView.as_view(), name="user-search"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
]