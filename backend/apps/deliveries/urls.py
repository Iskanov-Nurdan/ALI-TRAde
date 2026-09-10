from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.deliveries.views import DeliveryViewSet, VehicleSearchView

router = DefaultRouter()
router.register("deliveries", DeliveryViewSet, basename="delivery")

urlpatterns = [
    path("vehicles/search/", VehicleSearchView.as_view(), name="vehicle-search"),
    path("", include(router.urls)),
]
