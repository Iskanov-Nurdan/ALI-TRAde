from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    ChangePasswordView,
    EmployeeDirectoryView,
    LoginView,
    MeView,
    SessionRefreshView,
    SessionVerifyView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

auth_patterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", SessionRefreshView.as_view(), name="auth-refresh"),
    path("verify/", SessionVerifyView.as_view(), name="auth-verify"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
]

urlpatterns = [
    path("auth/", include(auth_patterns)),
    path("users/directory/", EmployeeDirectoryView.as_view(), name="user-directory"),
    path("", include(router.urls)),
]
