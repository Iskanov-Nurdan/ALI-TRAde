"""Маршруты проекта."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.views import HealthView

api_patterns = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.points.urls")),
    path("", include("apps.deliveries.urls")),
    path("", include("apps.expenses.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.core.urls")),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("health/", HealthView.as_view(), name="health"),
    path("api/", include(api_patterns)),
]

if settings.DEBUG:
    # В режиме разработки открываем фронтенд по корневому адресу.
    urlpatterns += [path("", RedirectView.as_view(url="/static/index.html", permanent=False))]

admin.site.site_header = "ALI trade"
admin.site.site_title = "ALI trade"
admin.site.index_title = "Администрирование"
