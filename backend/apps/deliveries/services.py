"""Бизнес-логика рейсов: расчёт дедлайна, отправление, приём, просрочка, история."""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.services import AuditService
from apps.deliveries.models import Delivery, DeliveryEvent, DeliveryStatus, DeliveryWaypoint
from apps.deliveries.repositories import DeliveryEventRepository, DeliveryRepository
from apps.points.repositories import PointRepository

logger = logging.getLogger(__name__)


class DeliveryEventService:
    """Единая точка записи истории рейса."""

    def __init__(self, repository: DeliveryEventRepository | None = None) -> None:
        self.repository = repository or DeliveryEventRepository()

    def log(
        self,
        *,
        delivery: Delivery,
        event_type: str,
        user=None,
        comment: str = "",
        metadata: dict | None = None,
        event_time=None,
    ) -> DeliveryEvent:
        return DeliveryEvent.objects.create(
            delivery=delivery,
            event_type=event_type,
            user=user,
            comment=comment or "",
            metadata=metadata,
            event_time=event_time or timezone.now(),
        )


class DeliveryService:
    def __init__(
        self,
        repository: DeliveryRepository | None = None,
        event_service: DeliveryEventService | None = None,
        point_repository: PointRepository | None = None,
    ) -> None:
        self.repository = repository or DeliveryRepository()
        self.events = event_service or DeliveryEventService()
        self.points = point_repository or PointRepository()

    # --- Вспомогательные проверки ---

    # Небольшой допуск на расхождение часов клиента и сервера
    FUTURE_TOLERANCE = timedelta(minutes=5)

    @staticmethod
    def _lock(delivery: Delivery) -> Delivery:
        """Перечитывает рейс с блокировкой строки: защита от параллельных операций."""
        return Delivery.objects.select_for_update().get(pk=delivery.pk)

    def _reject_future(self, moment, label: str) -> None:
        if moment and moment > timezone.now() + self.FUTURE_TOLERANCE:
            raise BusinessError(f"{label} не может быть в будущем.")

    def _get_point(self, point_id: int, label: str):
        point = self.points.get_by_id(point_id)
        if point is None:
            raise BusinessError(f"{label}: точка не найдена.")
        if not point.is_active:
            raise BusinessError(f"{label}: точка отключена, выберите другую.")
        return point

    def _resolve_waypoints(self, point_ids, point_from_id: int, point_to_id: int) -> list:
        """Проверяет промежуточные точки: активные, без повторов и без краёв маршрута."""
        if not point_ids:
            return []
        if len(point_ids) > 10:
            raise BusinessError("Не больше 10 промежуточных точек в одном рейсе.")
        if len(set(point_ids)) != len(point_ids):
            raise BusinessError("Промежуточные точки не должны повторяться.")

        points = []
        for point_id in point_ids:
            if point_id in (point_from_id, point_to_id):
                raise BusinessError(
                    "Промежуточная точка не может совпадать с точкой отправления или прибытия."
                )
            points.append(self._get_point(point_id, "Промежуточная точка"))
        return points

    @staticmethod
    def _calc_deadline(dispatched_at, duration_hours=None, duration_minutes=None, deadline_at=None):
        """Дедлайн задаётся либо длительностью, либо конкретным временем."""
        if deadline_at:
            if deadline_at <= dispatched_at:
                raise BusinessError("Срок прибытия должен быть позже времени отправления.")
            minutes = int((deadline_at - dispatched_at).total_seconds() // 60)
            if minutes > 60 * 24 * 30:
                raise BusinessError("Срок прибытия не может превышать 30 суток.")
            return deadline_at, minutes

        total_minutes = int((duration_hours or 0) * 60 + (duration_minutes or 0))
        if total_minutes <= 0:
            raise BusinessError("Укажите срок прибытия: количество часов либо конкретное время.")
        if total_minutes > 60 * 24 * 30:
            raise BusinessError("Срок прибытия не может превышать 30 суток.")
        return dispatched_at + timedelta(minutes=total_minutes), total_minutes

    # --- Основные операции ---

    @transaction.atomic
    def create_delivery(self, *, actor, data: dict, ip: str | None = None) -> Delivery:
        point_from = self._get_point(data["point_from_id"], "Точка отправления")
        point_to = self._get_point(data["point_to_id"], "Точка прибытия")
        if point_from.id == point_to.id:
            raise BusinessError("Точки отправления и прибытия должны различаться.")

        dispatched_at = data.get("dispatched_at") or timezone.now()
        self._reject_future(dispatched_at, "Время отправления")
        deadline_at, duration_minutes = self._calc_deadline(
            dispatched_at,
            duration_hours=data.get("duration_hours"),
            duration_minutes=data.get("duration_minutes"),
            deadline_at=data.get("deadline_at"),
        )

        waypoints = self._resolve_waypoints(
            data.get("waypoint_ids") or [], point_from.id, point_to.id
        )
        auto_dispatch = data.get("auto_dispatch", True)
        comment = (data.get("comment") or "").strip()

        delivery = Delivery(
            point_from=point_from,
            point_to=point_to,
            vehicle_number=data["vehicle_number"],
            created_by=actor,
            dispatched_at=dispatched_at,
            deadline_at=deadline_at,
            planned_duration_minutes=duration_minutes,
            status=DeliveryStatus.CREATED,
            dispatch_comment=comment,
        )
        if auto_dispatch:
            delivery.status = DeliveryStatus.IN_TRANSIT
            delivery.dispatched_by = actor
        delivery.save()

        if waypoints:
            DeliveryWaypoint.objects.bulk_create(
                [
                    DeliveryWaypoint(delivery=delivery, point=point, order=index)
                    for index, point in enumerate(waypoints, start=1)
                ]
            )

        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.CREATED,
            user=actor,
            comment=comment,
            metadata={
                "vehicle_number": delivery.vehicle_number,
                "route": " → ".join(
                    [point_from.name, *[p.name for p in waypoints], point_to.name]
                ),
                "deadline_at": deadline_at.isoformat(),
            },
            # Создание всегда первое в истории, даже если отправление указано задним числом.
            event_time=min(delivery.created_at or timezone.now(), dispatched_at),
        )
        if auto_dispatch:
            self.events.log(
                delivery=delivery,
                event_type=DeliveryEvent.EventType.DISPATCHED,
                user=actor,
                comment=comment,
                metadata={"dispatched_at": dispatched_at.isoformat()},
                event_time=dispatched_at,
            )

        AuditService.log(
            user=actor,
            action=AuditLog.Action.CREATE,
            entity_type="delivery",
            entity_id=delivery.id,
            new_value={
                "vehicle_number": delivery.vehicle_number,
                "point_from": point_from.name,
                "point_to": point_to.name,
                "dispatched_at": dispatched_at.isoformat(),
                "deadline_at": deadline_at.isoformat(),
                "status": delivery.status,
            },
            ip_address=ip,
        )
        logger.info(
            "Рейс #%s создан (%s: %s → %s) сотрудником %s",
            delivery.id, delivery.vehicle_number, point_from.name, point_to.name, actor.login,
        )
        return delivery

    @transaction.atomic
    def dispatch(self, *, actor, delivery: Delivery, data: dict, ip: str | None = None) -> Delivery:
        delivery = self._lock(delivery)
        if delivery.status == DeliveryStatus.CANCELLED:
            raise BusinessError("Рейс отменён — отправление невозможно.")
        if delivery.status != DeliveryStatus.CREATED:
            raise BusinessError("Отправление этого рейса уже подтверждено.")

        dispatched_at = data.get("dispatched_at") or timezone.now()
        self._reject_future(dispatched_at, "Время отправления")
        comment = (data.get("comment") or "").strip()

        delivery.dispatched_at = dispatched_at
        # Если срок задавался длительностью — дедлайн считается от фактического отправления.
        if delivery.planned_duration_minutes:
            delivery.deadline_at = dispatched_at + timedelta(minutes=delivery.planned_duration_minutes)
        if delivery.deadline_at <= dispatched_at:
            raise BusinessError("Срок прибытия должен быть позже времени отправления.")

        delivery.status = DeliveryStatus.IN_TRANSIT
        delivery.dispatched_by = actor
        if comment:
            delivery.dispatch_comment = comment
        delivery.save()

        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.DISPATCHED,
            user=actor,
            comment=comment,
            metadata={
                "dispatched_at": dispatched_at.isoformat(),
                "deadline_at": delivery.deadline_at.isoformat(),
            },
            event_time=dispatched_at,
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="delivery",
            entity_id=delivery.id,
            old_value={"status": DeliveryStatus.CREATED},
            new_value={"status": delivery.status, "dispatched_at": dispatched_at.isoformat()},
            ip_address=ip,
        )
        logger.info("Рейс #%s отправлен сотрудником %s", delivery.id, actor.login)
        return delivery

    @transaction.atomic
    def receive(self, *, actor, delivery: Delivery, data: dict, ip: str | None = None) -> Delivery:
        delivery = self._lock(delivery)
        if delivery.status == DeliveryStatus.CANCELLED:
            raise BusinessError("Рейс отменён — подтвердить прибытие нельзя.")
        if delivery.status == DeliveryStatus.ARRIVED:
            raise BusinessError("Прибытие этого рейса уже подтверждено.")
        if delivery.status == DeliveryStatus.CREATED:
            raise BusinessError("Сначала подтвердите отправление машины.")

        received_at = data.get("received_at") or timezone.now()
        self._reject_future(received_at, "Время прибытия")
        if received_at < delivery.dispatched_at:
            raise BusinessError("Время прибытия не может быть раньше времени отправления.")
        last_passed = delivery.waypoints.aggregate(last=Max("passed_at"))["last"]
        if last_passed and received_at < last_passed:
            raise BusinessError(
                "Время прибытия не может быть раньше прохождения промежуточной точки."
            )
        comment = (data.get("comment") or "").strip()

        # Факт просрочки фиксируется по реальному времени: указанное задним числом
        # время прибытия не должно стирать уже наступившую просрочку.
        self._log_deadline_passed(delivery)

        delivery.received_at = received_at
        delivery.received_by = actor
        delivery.status = DeliveryStatus.ARRIVED
        if comment:
            delivery.receive_comment = comment
        delivery.save()

        late_minutes = delivery.late_minutes
        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.RECEIVED,
            user=actor,
            comment=comment,
            metadata={
                "received_at": received_at.isoformat(),
                "deadline_at": delivery.deadline_at.isoformat(),
                "late_minutes": late_minutes,
            },
            event_time=received_at,
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="delivery",
            entity_id=delivery.id,
            old_value={"status": DeliveryStatus.IN_TRANSIT},
            new_value={
                "status": delivery.status,
                "received_at": received_at.isoformat(),
                "late_minutes": late_minutes,
            },
            ip_address=ip,
        )
        logger.info(
            "Рейс #%s принят сотрудником %s (опоздание %s мин)", delivery.id, actor.login, late_minutes
        )
        return delivery

    @transaction.atomic
    def cancel(self, *, actor, delivery: Delivery, data: dict, ip: str | None = None) -> Delivery:
        delivery = self._lock(delivery)
        if delivery.status == DeliveryStatus.ARRIVED:
            raise BusinessError("Прибывший рейс отменить нельзя.")
        if delivery.status == DeliveryStatus.CANCELLED:
            raise BusinessError("Рейс уже отменён.")

        comment = (data.get("comment") or "").strip()
        if not comment:
            raise BusinessError("Укажите причину отмены рейса.")

        delivery.status = DeliveryStatus.CANCELLED
        delivery.cancel_comment = comment
        delivery.cancelled_by = actor
        delivery.cancelled_at = timezone.now()
        delivery.save()

        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.CANCELLED,
            user=actor,
            comment=comment,
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="delivery",
            entity_id=delivery.id,
            new_value={"status": delivery.status, "reason": comment},
            ip_address=ip,
        )
        logger.warning("Рейс #%s отменён сотрудником %s", delivery.id, actor.login)
        return delivery

    @transaction.atomic
    def update_delivery(self, *, actor, delivery: Delivery, data: dict, ip: str | None = None) -> Delivery:
        """Правка рейса доступна администратору (исправление ошибок ввода)."""
        delivery = self._lock(delivery)

        # У завершённого рейса сроки не правятся: иначе задним числом исчезает опоздание.
        time_fields = {"dispatched_at", "deadline_at", "duration_hours", "duration_minutes"}
        if delivery.status in (DeliveryStatus.ARRIVED, DeliveryStatus.CANCELLED) and (
            time_fields & set(data.keys())
        ):
            raise BusinessError(
                "Сроки завершённого рейса изменить нельзя — факт прибытия и опоздание фиксируются."
            )

        old = {
            "vehicle_number": delivery.vehicle_number,
            "point_from": delivery.point_from.name,
            "point_to": delivery.point_to.name,
            "dispatched_at": delivery.dispatched_at.isoformat(),
            "deadline_at": delivery.deadline_at.isoformat(),
        }

        if "point_from_id" in data:
            delivery.point_from = self._get_point(data["point_from_id"], "Точка отправления")
        if "point_to_id" in data:
            delivery.point_to = self._get_point(data["point_to_id"], "Точка прибытия")
        if delivery.point_from_id == delivery.point_to_id:
            raise BusinessError("Точки отправления и прибытия должны различаться.")

        # Новый край маршрута не должен уже присутствовать среди промежуточных точек
        edge_ids = {delivery.point_from_id, delivery.point_to_id}
        kept_ids = set(data["waypoint_ids"] or []) if "waypoint_ids" in data else set(
            delivery.waypoints.values_list("point_id", flat=True)
        )
        if edge_ids & kept_ids:
            raise BusinessError(
                "Точка отправления или прибытия уже указана как промежуточная — исправьте маршрут."
            )

        if "waypoint_ids" in data:
            waypoints = self._resolve_waypoints(
                data["waypoint_ids"] or [], delivery.point_from_id, delivery.point_to_id
            )
            passed = delivery.waypoints.filter(passed_at__isnull=False).values_list("point_id", flat=True)
            missing = set(passed) - {point.id for point in waypoints}
            if missing:
                raise BusinessError("Нельзя убрать точку, прохождение которой уже отмечено.")
            existing = {w.point_id: w for w in delivery.waypoints.all()}
            delivery.waypoints.exclude(point_id__in=[point.id for point in waypoints]).delete()
            for index, point in enumerate(waypoints, start=1):
                current = existing.get(point.id)
                if current is None:
                    DeliveryWaypoint.objects.create(delivery=delivery, point=point, order=index)
                elif current.order != index:
                    current.order = index
                    current.save(update_fields=["order"])

        if "vehicle_number" in data:
            delivery.vehicle_number = data["vehicle_number"]
        if "dispatched_at" in data and data["dispatched_at"]:
            delivery.dispatched_at = data["dispatched_at"]
        if "deadline_at" in data and data["deadline_at"]:
            # Через общий расчёт: он же проверяет порядок дат и предел в 30 суток
            delivery.deadline_at, delivery.planned_duration_minutes = self._calc_deadline(
                delivery.dispatched_at, deadline_at=data["deadline_at"]
            )
        elif data.get("duration_hours") or data.get("duration_minutes"):
            delivery.deadline_at, delivery.planned_duration_minutes = self._calc_deadline(
                delivery.dispatched_at,
                duration_hours=data.get("duration_hours"),
                duration_minutes=data.get("duration_minutes"),
            )

        if delivery.deadline_at <= delivery.dispatched_at:
            raise BusinessError("Срок прибытия должен быть позже времени отправления.")
        if delivery.received_at and delivery.received_at < delivery.dispatched_at:
            raise BusinessError("Время прибытия не может быть раньше времени отправления.")
        # Пройденные точки — часть той же хронологии: правка отправления не должна
        # делать их «пройденными до выезда».
        passed = delivery.waypoints.aggregate(first=Min("passed_at"), last=Max("passed_at"))
        if passed["first"] and delivery.dispatched_at > passed["first"]:
            raise BusinessError(
                "Время отправления не может быть позже прохождения промежуточной точки."
            )
        if delivery.received_at and passed["last"] and delivery.received_at < passed["last"]:
            raise BusinessError(
                "Время прибытия не может быть раньше прохождения промежуточной точки."
            )

        # Срок продлён: прошлая просрочка уже записана в историю, но по новому
        # сроку рейс может просрочиться снова. Флаг снимаем всегда, иначе вторая
        # просрочка не попадёт в историю вообще.
        if delivery.status == DeliveryStatus.IN_TRANSIT and delivery.deadline_at > timezone.now():
            delivery.deadline_passed_logged = False

        delivery.save()

        new = {
            "vehicle_number": delivery.vehicle_number,
            "point_from": delivery.point_from.name,
            "point_to": delivery.point_to.name,
            "dispatched_at": delivery.dispatched_at.isoformat(),
            "deadline_at": delivery.deadline_at.isoformat(),
        }
        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.UPDATED,
            user=actor,
            comment=(data.get("comment") or "").strip(),
            metadata={"old": old, "new": new},
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="delivery",
            entity_id=delivery.id,
            old_value=old,
            new_value=new,
            ip_address=ip,
        )
        return delivery

    @transaction.atomic
    def pass_waypoint(
        self, *, actor, delivery: Delivery, waypoint: DeliveryWaypoint, data: dict, ip: str | None = None
    ) -> DeliveryWaypoint:
        """Сотрудник отмечает, что машина прошла промежуточную точку."""
        delivery = self._lock(delivery)
        if delivery.status == DeliveryStatus.CANCELLED:
            raise BusinessError("Рейс отменён — отметить прохождение нельзя.")
        if delivery.status == DeliveryStatus.CREATED:
            raise BusinessError("Сначала подтвердите отправление машины.")
        if delivery.status == DeliveryStatus.ARRIVED:
            raise BusinessError("Рейс уже прибыл — маршрут закрыт.")
        waypoint = DeliveryWaypoint.objects.select_for_update().get(pk=waypoint.pk)
        if waypoint.passed_at:
            raise BusinessError("Прохождение этой точки уже отмечено.")

        previous = (
            delivery.waypoints.filter(order__lt=waypoint.order, passed_at__isnull=True)
            .order_by("order")
            .first()
        )
        if previous is not None:
            raise BusinessError(
                f"Сначала отметьте прохождение точки «{previous.point.name}» — маршрут идёт по порядку."
            )

        passed_at = data.get("passed_at") or timezone.now()
        self._reject_future(passed_at, "Время прохождения точки")
        if passed_at < delivery.dispatched_at:
            raise BusinessError("Время прохождения не может быть раньше отправления.")

        comment = (data.get("comment") or "").strip()
        waypoint.passed_at = passed_at
        waypoint.passed_by = actor
        if comment:
            waypoint.comment = comment
        waypoint.save(update_fields=["passed_at", "passed_by", "comment"])

        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.WAYPOINT_PASSED,
            user=actor,
            comment=comment,
            metadata={
                "waypoint_id": waypoint.id,
                "point": waypoint.point.name,
                "passed_at": passed_at.isoformat(),
            },
            event_time=passed_at,
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="delivery_waypoint",
            entity_id=waypoint.id,
            new_value={"point": waypoint.point.name, "passed_at": passed_at.isoformat()},
            ip_address=ip,
        )
        logger.info(
            "Рейс #%s: пройдена точка %s (отметил %s)", delivery.id, waypoint.point.name, actor.login
        )
        return waypoint

    @transaction.atomic
    def delete_delivery(self, *, actor, delivery: Delivery, ip: str | None = None) -> None:
        """Удаление рейса вместе с историей и расходами — операция администратора."""
        snapshot = {
            "vehicle_number": delivery.vehicle_number,
            "point_from": delivery.point_from.name,
            "point_to": delivery.point_to.name,
            "route": " → ".join(delivery.route_points),
            "status": delivery.status,
            "dispatched_at": delivery.dispatched_at.isoformat(),
            "deadline_at": delivery.deadline_at.isoformat(),
            "received_at": delivery.received_at.isoformat() if delivery.received_at else None,
            "expenses_count": delivery.expenses.count(),
            "events_count": delivery.events.count(),
        }
        delivery_id = delivery.id
        delivery.delete()

        AuditService.log(
            user=actor,
            action=AuditLog.Action.DELETE,
            entity_type="delivery",
            entity_id=delivery_id,
            old_value=snapshot,
            ip_address=ip,
        )
        logger.warning("Рейс #%s удалён администратором %s", delivery_id, actor.login)

    @transaction.atomic
    def add_comment(self, *, actor, delivery: Delivery, comment: str) -> DeliveryEvent:
        comment = (comment or "").strip()
        if not comment:
            raise BusinessError("Комментарий не может быть пустым.")
        event = self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.COMMENT_ADDED,
            user=actor,
            comment=comment,
        )
        logger.info("Комментарий к рейсу #%s от %s", delivery.id, actor.login)
        return event

    # --- Автоматическая просрочка ---

    def _log_deadline_passed(self, delivery: Delivery, limit_time=None) -> None:
        """Пишет событие о просроченном сроке ровно один раз."""
        if delivery.deadline_passed_logged:
            return
        moment = limit_time or timezone.now()
        if moment <= delivery.deadline_at:
            return
        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.DEADLINE_PASSED,
            user=None,
            comment="Срок прибытия истёк, прибытие не подтверждено.",
            metadata={"deadline_at": delivery.deadline_at.isoformat()},
            event_time=delivery.deadline_at,
        )
        delivery.deadline_passed_logged = True
        Delivery.objects.filter(pk=delivery.pk).update(deadline_passed_logged=True)

    def sync_overdue_events(self, limit: int = 500) -> int:
        """Фиксирует в истории рейсы, у которых истёк срок. Идемпотентно."""
        overdue = list(self.repository.unlogged_overdue()[:limit])
        if not overdue:
            return 0

        events = [
            DeliveryEvent(
                delivery=delivery,
                event_type=DeliveryEvent.EventType.DEADLINE_PASSED,
                user=None,
                comment="Срок прибытия истёк, прибытие не подтверждено.",
                metadata={"deadline_at": delivery.deadline_at.isoformat()},
                event_time=delivery.deadline_at,
            )
            for delivery in overdue
        ]
        DeliveryEvent.objects.bulk_create(events)
        Delivery.objects.filter(pk__in=[d.pk for d in overdue]).update(deadline_passed_logged=True)
        logger.info("Зафиксирована просрочка по %s рейсам", len(overdue))
        return len(overdue)
