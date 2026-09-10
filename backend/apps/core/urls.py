from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.core.views import AuditLogViewSet

router = DefaultRouter()
router.register("audit", AuditLogViewSet, basename="audit")

urlpatterns = [path("", include(router.urls))]
