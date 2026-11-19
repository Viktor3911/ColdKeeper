"""Demo data: two organizations, sites, rooms, equipment, points and simulated sensors (explicit command only).

Everything goes through the same use cases as the web interface. Re-running creates no duplicates: existing
entities are found by name; the history anchors and the device keys of an existing ``.demo/devices.json`` are kept,
so a running simulator keeps working and reloading history sends identical values. A key is reissued only when it is
missing or no longer valid. Demo passwords are generated with :mod:`secrets` and stored in ``.demo/credentials.json``.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.application.auth import DEMO_CAFE_NAME, DEMO_OWNER_LOGIN
from backend.application.inventory import SiteInput
from backend.composition import Container
from backend.domain.equipment import EquipmentKind, PointSettings, SettingsProfile
from backend.domain.organizations import Actor, Role
from backend.domain.sensors import SensorKind

HISTORY_DAYS = 7
STEP_SECONDS = 60
DEMO_SEED = 20261103

FRIDGE = (2.0, 6.0)
FREEZER = (-22.0, -16.0)


@dataclass(frozen=True, slots=True)
class DemoPoint:
    """A point with its simulated sensor and scenarios."""

    name: str
    thresholds: tuple[float, float]
    hardware_id: str
    profile: str
    history_scenario: str
    live_scenario: str


@dataclass(frozen=True, slots=True)
class DemoEquipment:
    """Equipment with points."""

    room: str
    name: str
    kind: EquipmentKind
    points: tuple[DemoPoint, ...]


@dataclass(frozen=True, slots=True)
class DemoOrganization:
    """Organization with one site and its users."""

    name: str
    site: str
    address: str
    users: tuple[tuple[str, Role], ...]
    equipment: tuple[DemoEquipment, ...]


PROGRAM = (
    DemoOrganization(
        name=DEMO_CAFE_NAME,
        site="Кафе на Светланской (демо)",
        address="г. Владивосток, ул. Светланская, 1 (демо-адрес)",
        users=((DEMO_OWNER_LOGIN, Role.OWNER), ("demo-observer", Role.OBSERVER)),
        equipment=(
            DemoEquipment(
                "Кухня",
                "Холодильный шкаф №1",
                EquipmentKind.REFRIGERATOR,
                (DemoPoint("Камера", FRIDGE, "demo-fridge-1", "refrigerator", "routine_week", "door_spikes"),),
            ),
            DemoEquipment(
                "Кухня",
                "Холодильник с морозильной камерой",
                EquipmentKind.COMBINED,
                (
                    DemoPoint(
                        "Холодильная секция",
                        FRIDGE,
                        "demo-combo-cool",
                        "refrigerator",
                        "routine_week",
                        "sustained_excursion",
                    ),
                    DemoPoint(
                        "Морозильная секция",
                        FREEZER,
                        "demo-combo-freeze",
                        "freezer",
                        "routine_week",
                        "probe_failure",
                    ),
                ),
            ),
            DemoEquipment(
                "Склад",
                "Морозильный ларь",
                EquipmentKind.FREEZER,
                (DemoPoint("Камера", FREEZER, "demo-chest-1", "freezer", "routine_week_gaps", "connection_loss"),),
            ),
        ),
    ),
    DemoOrganization(
        name="Магазин «Юг» (демо)",
        site="Магазин на Русской (демо)",
        address="г. Владивосток, ул. Русская, 2 (демо-адрес)",
        users=(("demo-shop", Role.OWNER),),
        equipment=(
            DemoEquipment(
                "Торговый зал",
                "Витрина-холодильник",
                EquipmentKind.DISPLAY,
                (DemoPoint("Камера", FRIDGE, "demo-shop-1", "refrigerator", "routine_week", "normal"),),
            ),
        ),
    ),
)

# Short, clearly marked demo timeouts so incidents appear within minutes during a presentation.
DEMO_TIMING = {
    "deviation_duration": timedelta(minutes=3),
    "recovery_duration": timedelta(minutes=2),
    "expected_interval": timedelta(seconds=STEP_SECONDS),
    "offline_timeout": timedelta(minutes=3),
}


class DemoSeeder:
    """Creates or refreshes the demo data and writes the local files for the simulator and sign-in."""

    def __init__(self, container: Container, demo_dir: Path) -> None:
        self._container = container
        self._dir = demo_dir

    async def run(self) -> list[str]:
        """Seed and return human-readable lines for the console."""
        previous = self._load_json("devices.json")
        start_text, end_text = previous.get("history_start"), previous.get("history_end")
        if isinstance(start_text, str) and isinstance(end_text, str):
            # The same anchors as before: the generated series and the stored history stay identical.
            history_start, history_end = datetime.fromisoformat(start_text), datetime.fromisoformat(end_text)
        else:
            history_end = self._container.clock.now().replace(second=0, microsecond=0)
            history_start = history_end - timedelta(days=HISTORY_DAYS)
        known_tokens = {
            str(device.get("hardware_id")): str(device.get("token"))
            for device in previous.get("devices", [])
            if isinstance(device, dict)
        }
        # Assignments start before the history window, otherwise loaded history would be "unassigned".
        assigned_from = history_start - timedelta(days=1)
        credentials = {key: str(value) for key, value in self._load_json("credentials.json").items()}
        devices: list[dict[str, object]] = []
        lines: list[str] = []
        for organization in PROGRAM:
            owner = await self._organization(organization, credentials, lines)
            devices.extend(await self._inventory(organization, owner, assigned_from, known_tokens))
        self._dir.mkdir(parents=True, exist_ok=True)
        device_file = {
            "version": 1,
            "seed": DEMO_SEED,
            "step_seconds": STEP_SECONDS,
            "history_start": history_start.isoformat(),
            "history_end": history_end.isoformat(),
            "devices": devices,
        }
        _write_private(self._dir / "devices.json", json.dumps(device_file, ensure_ascii=False, indent=2))
        _write_private(self._dir / "credentials.json", json.dumps(credentials, ensure_ascii=False, indent=2))
        lines.append(f"Ключи симулируемых датчиков: {self._dir / 'devices.json'}")
        lines.append(f"Демо-логины и пароли (только локально): {self._dir / 'credentials.json'}")
        return lines

    def _load_json(self, name: str) -> dict[str, Any]:
        path = self._dir / name
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def _organization(self, spec: DemoOrganization, credentials: dict[str, str], lines: list[str]) -> Actor:
        admin = self._container.admin
        organization = await admin.get_organization(spec.name) or await admin.create_organization(spec.name)
        owner: Actor | None = None
        for login, role in spec.users:
            password = credentials.get(login) or secrets.token_urlsafe(12)
            user = await admin.get_user(login)
            if user is None:
                user = await admin.create_user(spec.name, login, password, role)
            elif login not in credentials:
                await admin.set_password(login, password)  # the local file was lost: issue a new password
            credentials[login] = password
            lines.append(f"{spec.name}: {login} ({'владелец' if role is Role.OWNER else 'наблюдатель'})")
            if role is Role.OWNER and owner is None:
                owner = Actor(user_id=user.id, organization_id=organization.id, role=Role.OWNER)
        if owner is None:  # pragma: no cover - every demo organization has an owner
            msg = f"{spec.name}: нет владельца"
            raise RuntimeError(msg)
        return owner

    async def _inventory(
        self,
        spec: DemoOrganization,
        owner: Actor,
        assigned_from: datetime,
        known_tokens: dict[str, str],
    ) -> list[dict[str, object]]:
        inventory = self._container.inventory
        tree = await inventory.tree(owner)
        site = next((item for item in tree.sites if item.name == spec.site), None)
        if site is None:
            site = await inventory.save_site(
                owner,
                SiteInput(spec.site, spec.address, "Asia/Vladivostok", time(10, 0), timedelta(minutes=30)),
            )
        devices: list[dict[str, object]] = []
        for equipment_spec in spec.equipment:
            room_id = await self._room(owner, site.id, equipment_spec.room)
            equipment_id = await self._equipment(owner, room_id, equipment_spec)
            for point_spec in equipment_spec.points:
                point_id = await self._point(owner, equipment_id, point_spec)
                token = await self._sensor(
                    owner, point_spec, point_id, assigned_from, known_tokens.get(point_spec.hardware_id)
                )
                devices.append(
                    {
                        "hardware_id": point_spec.hardware_id,
                        "token": token,
                        "label": f"{spec.site} / {equipment_spec.name} / {point_spec.name}",
                        "profile": point_spec.profile,
                        "history_scenario": point_spec.history_scenario,
                        "live_scenario": point_spec.live_scenario,
                    },
                )
        return devices

    async def _room(self, owner: Actor, site_id: UUID, name: str) -> UUID:
        tree = await self._container.inventory.tree(owner)
        room = next((item for item in tree.rooms if item.site_id == site_id and item.name == name), None)
        if room is None:
            room = await self._container.inventory.save_room(owner, site_id, name)
        return room.id

    async def _equipment(self, owner: Actor, room_id: UUID, spec: DemoEquipment) -> UUID:
        tree = await self._container.inventory.tree(owner)
        found = next((item for item in tree.equipment if item.room_id == room_id and item.name == spec.name), None)
        if found is None:
            found = await self._container.inventory.save_equipment(owner, room_id, spec.name, spec.kind)
        return found.id

    async def _point(self, owner: Actor, equipment_id: UUID, spec: DemoPoint) -> UUID:
        tree = await self._container.inventory.tree(owner)
        found = next(
            (item for item in tree.points if item.equipment_id == equipment_id and item.name == spec.name), None
        )
        settings = PointSettings(spec.thresholds[0], spec.thresholds[1], profile=SettingsProfile.DEMO, **DEMO_TIMING)
        point = await self._container.inventory.save_point(
            owner,
            equipment_id,
            spec.name,
            settings,
            None if found is None else found.id,
        )
        return point.id

    async def _sensor(
        self,
        owner: Actor,
        spec: DemoPoint,
        point_id: UUID,
        assigned_from: datetime,
        known_token: str | None,
    ) -> str:
        service = self._container.sensors
        existing = next(
            (view for view in await service.list_sensors(owner) if view.sensor.hardware_id == spec.hardware_id),
            None,
        )
        if existing is None:
            issued = await service.register(owner, spec.hardware_id, SensorKind.SIMULATED, "UnitX-T (симуляция)")
            await service.assign(owner, issued.sensor_id, point_id, assigned_from)
            return issued.token
        if existing.assignment is None:
            # Without stored readings the assignment may cover the history window; otherwise it starts now.
            start = assigned_from if existing.last_measured_at is None else None
            await service.assign(owner, existing.sensor.id, point_id, start)
        if known_token is not None and await service.token_matches(owner, existing.sensor.id, known_token):
            return known_token
        # Lost or revoked: a key cannot be recovered from its hash, so a new one is issued.
        return (await service.issue_token(owner, existing.sensor.id)).token


def _write_private(path: Path, content: str) -> None:
    """Local secrets file (the directory is in .gitignore)."""
    path.write_text(content + "\n", encoding="utf-8")
    path.chmod(0o600)
