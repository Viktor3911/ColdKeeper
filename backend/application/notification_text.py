"""Texts of incident notifications (Russian, local time of the site)."""

from __future__ import annotations

from datetime import datetime

from backend.domain.equipment import PointLocation
from backend.domain.incidents import EventKind, Incident
from backend.domain.monitoring import Direction, IncidentType

_OPENED_TITLES = {
    IncidentType.TEMPERATURE: "Температура вне допустимого диапазона",
    IncidentType.SENSOR_ERROR: "Ошибка датчика: нет значения температуры",
    IncidentType.CONNECTION_LOST: "Нет связи с датчиком",
}
_CLOSED_TITLES = {
    IncidentType.TEMPERATURE: "Температура вернулась в норму",
    IncidentType.SENSOR_ERROR: "Датчик снова передаёт температуру",
    IncidentType.CONNECTION_LOST: "Связь с датчиком восстановлена",
}
_DIRECTIONS = {Direction.HIGH: "выше верхнего порога", Direction.LOW: "ниже нижнего порога"}


def format_temperature(value: float | None) -> str:
    """``-18,2 °C`` with a decimal comma."""
    if value is None:
        return "—"
    return f"{value:.1f} °C".replace(".", ",")


def format_local(moment: datetime, location: PointLocation) -> str:
    """``03.11.2026 10:05`` in the site's time zone."""
    return moment.astimezone(location.zone).strftime("%d.%m.%Y %H:%M")


def incident_message(location: PointLocation, incident: Incident, kind: EventKind) -> str:
    """Notification text: what happened, where, the value or reason and the local time."""
    titles = _OPENED_TITLES if kind is EventKind.OPENED else _CLOSED_TITLES
    icon = "⚠️" if kind is EventKind.OPENED else "✅"
    lines = [
        f"{icon} {titles[incident.type]}",
        f"Объект: {location.site_name}",
        f"Помещение: {location.room_name}",
        f"Оборудование: {location.equipment_name}",
        f"Точка: {location.point_name}",
    ]
    if kind is EventKind.OPENED:
        if incident.type is IncidentType.TEMPERATURE and incident.direction is not None:
            lines.append(
                f"Температура: {format_temperature(incident.open_temperature)}, {_DIRECTIONS[incident.direction]}"
            )
        lines.append(f"Время: {format_local(incident.opened_at, location)}")
    else:
        if incident.close_temperature is not None:
            lines.append(f"Температура: {format_temperature(incident.close_temperature)}")
        closed_at = incident.closed_at or incident.opened_at
        lines.append(f"Время: {format_local(closed_at, location)} (с {format_local(incident.opened_at, location)})")
    return "\n".join(lines)
