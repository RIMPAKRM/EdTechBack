from django.urls import path
from api.views_admin import AdminDashboardView, AdminInviteCodeView

urlpatterns = [
    path("dashboard/", AdminDashboardView.as_view()),
    path("invite-code/", AdminInviteCodeView.as_view()),
]
