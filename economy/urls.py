# economy/urls.py
from django.urls import path
from .views import (
    UserCurrenciesView,
    DiamondPackagesView,
    GoldPackagesView,
    BuyPackageView,
    UserPackagesView,
    AdminUpdatePackageStatusView,
    AdminPendingPackagesView,
)

app_name = 'economy'

urlpatterns = [
    # User currency endpoints
    path('currencies/', UserCurrenciesView.as_view(), name='user-currencies'),

    # Package browsing
    path('packages/diamonds/', DiamondPackagesView.as_view(), name='diamond-packages'),
    path('packages/gold/', GoldPackagesView.as_view(), name='gold-packages'),

    # Package purchasing
    path('packages/buy/', BuyPackageView.as_view(), name='buy-package'),

    # User's packages
    path('user-packages/', UserPackagesView.as_view(), name='user-packages'),

    # Admin endpoints
    path('admin/packages/pending/', AdminPendingPackagesView.as_view(), name='admin-pending-packages'),
    path('admin/packages/<uuid:pk>/', AdminUpdatePackageStatusView.as_view(), name='admin-update-package'),
]