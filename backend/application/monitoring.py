"""Time-based monitoring done by the worker: detecting a lost connection without new requests."""

from __future__ import annotations

from backend.application.incidents import IncidentRecorder
from backend.application.ports import Clock, UnitOfWorkFactory
from backend.domain.monitoring import apply_silence


class CheckConnectivity:
    """Open "no connection" incidents for points that went silent; safe to run from several workers."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, incidents: IncidentRecorder) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._incidents = incidents

    async def __call__(self, batch: int = 100) -> int:
        """Check silent points; returns how many were marked offline."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            candidates = await uow.point_states.silent_candidates(now, batch)
        marked = 0
        for point_id in candidates:
            # One transaction per point: a failure on one point does not block the others.
            async with self._uow_factory() as uow:
                record = await uow.inventory.point_record(point_id)
                if record is None:
                    continue
                state = await uow.point_states.lock(point_id)
                evaluation = apply_silence(state, record.settings, now)
                if not evaluation.transitions:
                    continue
                await uow.point_states.save(evaluation.state)
                await self._incidents.record(uow, record.location, evaluation.transitions, now)
                await uow.commit()
                marked += 1
        return marked
