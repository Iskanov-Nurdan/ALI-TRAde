from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.points.views import PointViewSet

router = DefaultRouter()
router.register("points", PointViewSet, basename="point")

urlpatterns = [path("", include(router.urls))]
