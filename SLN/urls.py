from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/account/', include('accounts.urls')),
    path('api/qa/', include('qa.urls')),
    path('api/learning/', include('learning.urls')),
    path('api/gamification/', include('gamification.urls')),
    path('api/economy/', include('economy.urls')),
]
