"""Composition root: the only place that knows concrete adapters and wires them into use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from backend.adapters.db.unit_of_work import SqlUnitOfWorkFactory, create_engine, session_factory
from backend.adapters.export.csv_export import CsvJournalExporter
from backend.adapters.export.docx_form import DocxJournalFormRenderer
from backend.adapters.export.xlsx_export import XlsxJournalExporter
from backend.adapters.security.passwords import ScryptPasswordHasher
from backend.adapters.security.tokens import RandomSecretIssuer
from backend.application.auth import AdminService, AuthService
from backend.application.dashboard import DashboardService
from backend.application.incidents import IncidentRecorder
from backend.application.ingest import IngestReading
from backend.application.inventory import InventoryService
from backend.application.journal import ExportFormat, JournalService
from backend.application.monitoring import CheckConnectivity
from backend.application.notifications import DeliverNotifications, RecipientService
from backend.application.ports import (
    Clock,
    JournalExporter,
    NotificationSender,
    PasswordHasher,
    SystemClock,
    UnitOfWorkFactory,
)
from backend.application.sensors import SensorService
from backend.domain.auth import SessionPolicy, ThrottlePolicy
from backend.domain.incidents import RetryPolicy
from backend.settings import Settings


@dataclass(slots=True)
class Container:
    """Use cases shared by the API, the worker and the CLI."""

    engine: AsyncEngine
    uow_factory: UnitOfWorkFactory
    clock: Clock
    auth: AuthService
    admin: AdminService
    inventory: InventoryService
    sensors: SensorService
    ingest: IngestReading
    dashboard: DashboardService
    journal: JournalService
    recipients: RecipientService
    check_connectivity: CheckConnectivity
    settings: Settings = field(repr=False)

    async def close(self) -> None:
        """Release database connections."""
        await self.engine.dispose()


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    hasher: PasswordHasher | None = None,
) -> Container:
    """Production wiring; tests pass a controlled clock or a faster hasher instead of patching code."""
    engine = create_engine(settings.database_url.get_secret_value())
    uow_factory = SqlUnitOfWorkFactory(session_factory(engine))
    clock = clock or SystemClock()
    hasher = hasher or ScryptPasswordHasher()
    secrets = RandomSecretIssuer()
    incidents = IncidentRecorder()
    exporters: dict[ExportFormat, JournalExporter] = {
        ExportFormat.CSV: CsvJournalExporter(),
        ExportFormat.XLSX: XlsxJournalExporter(),
    }
    return Container(
        engine=engine,
        uow_factory=uow_factory,
        clock=clock,
        auth=AuthService(
            uow_factory,
            clock,
            hasher,
            secrets,
            SessionPolicy(
                idle_timeout=timedelta(days=settings.session_idle_days),
                absolute_timeout=timedelta(days=settings.session_absolute_days),
            ),
            ThrottlePolicy(
                max_failures=settings.login_max_failures,
                lockout=timedelta(minutes=settings.login_lockout_minutes),
            ),
        ),
        admin=AdminService(uow_factory, clock, hasher),
        inventory=InventoryService(uow_factory),
        sensors=SensorService(uow_factory, clock, secrets),
        ingest=IngestReading(uow_factory, clock, secrets, incidents),
        dashboard=DashboardService(uow_factory),
        journal=JournalService(uow_factory, exporters, DocxJournalFormRenderer()),
        recipients=RecipientService(
            uow_factory,
            clock,
            secrets,
            settings.telegram_bot_username if settings.bot_configured else None,
        ),
        check_connectivity=CheckConnectivity(uow_factory, clock, incidents),
        settings=settings,
    )


def build_delivery(container: Container, sender: NotificationSender) -> DeliverNotifications:
    """Delivery step for the worker with the chosen sender (Telegram or dry-run)."""
    return DeliverNotifications(container.uow_factory, container.clock, sender, RetryPolicy())
