from django.urls import path
from .views import (
    CreateSquadView,
    UpdateSquadView,
    DeleteSquadView,
    RetrieveSquadView,
    GetMySquadView,
    AddMemberView,
    RemoveMemberView,
    UpdateMemberRoleView,
)

app_name = 'squads'

urlpatterns = [
    # Squad management
    path('create/', CreateSquadView.as_view(), name='create-squad'),
    path('my-squad/', GetMySquadView.as_view(), name='get-my-squad'),
    path('<uuid:id>/', RetrieveSquadView.as_view(), name='retrieve-squad'),
    path('<uuid:id>/update/', UpdateSquadView.as_view(), name='update-squad'),
    path('<uuid:id>/delete/', DeleteSquadView.as_view(), name='delete-squad'),

    # Member management
    path('<uuid:squad_id>/members/add/', AddMemberView.as_view(), name='add-member'),
    path('<uuid:squad_id>/members/<uuid:user_id>/remove/', RemoveMemberView.as_view(), name='remove-member'),
    path('<uuid:squad_id>/members/<uuid:user_id>/role/', UpdateMemberRoleView.as_view(), name='update-member-role'),
]