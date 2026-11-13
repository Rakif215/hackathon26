"""Synthetic-development replay transport; domain failures never imply progress."""

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, HTTPException, Path

from .models import AdvanceReplay, ReplaySnapshot, StartReplay
from .repository import ReplayConflict, ReplayStoreUnavailable, UnknownConsultation, UnknownReplay

Identifier = Annotated[int, Path(gt=0, le=9_999_999_999)]


class ReplayStore(Protocol):
    def start(self, consultation_id: int, command: StartReplay) -> ReplaySnapshot: ...
    def get(self, consultation_id: int, replay_id: int) -> ReplaySnapshot: ...
    def advance(self, consultation_id: int, replay_id: int, command: AdvanceReplay) -> ReplaySnapshot: ...


def _execute(operation: Callable[[], ReplaySnapshot]) -> ReplaySnapshot:
    try:
        return operation()
    except (UnknownConsultation, UnknownReplay):
        raise HTTPException(status_code=404, detail="Synthetic consultation or replay not found") from None
    except ReplayConflict:
        raise HTTPException(status_code=409, detail="Replay cursor, request key or script conflicts; reload the snapshot") from None
    except ReplayStoreUnavailable:
        raise HTTPException(status_code=503, detail="Replay storage unavailable; retry with the same request key") from None


def build_router(store: ReplayStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/consultations", tags=["consultation replay"])

    @router.post("/{consultation_id}/replays", response_model=ReplaySnapshot)
    def start(consultation_id: Identifier, command: StartReplay) -> ReplaySnapshot:
        return _execute(lambda: store.start(consultation_id, command))

    @router.get("/{consultation_id}/replays/{replay_id}", response_model=ReplaySnapshot)
    def get(consultation_id: Identifier, replay_id: Identifier) -> ReplaySnapshot:
        return _execute(lambda: store.get(consultation_id, replay_id))

    @router.post("/{consultation_id}/replays/{replay_id}/advance", response_model=ReplaySnapshot)
    def advance(consultation_id: Identifier, replay_id: Identifier, command: AdvanceReplay) -> ReplaySnapshot:
        return _execute(lambda: store.advance(consultation_id, replay_id, command))

    return router
