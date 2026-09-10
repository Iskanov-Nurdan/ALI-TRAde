from django.db.models import QuerySet

from apps.core.repositories import BaseRepository
from apps.points.models import Point


class PointRepository(BaseRepository[Point]):
    model = Point

    def list_active(self) -> QuerySet[Point]:
        return self.get_queryset().filter(is_active=True)

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        qs = self.get_queryset().filter(name__iexact=name.strip())
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return qs.exists()

    def has_deliveries(self, point: Point) -> bool:
        """Точка занята, если она край маршрута либо промежуточная точка любого рейса."""
        return point.departures.exists() or point.arrivals.exists() or point.waypoints.exists()
