"""Frontend-oriented consultation analysis transport."""

from fastapi import APIRouter, HTTPException

from hackathon26.evidence_check.repository import UnknownCandidate
from hackathon26.replay.http import Identifier
from hackathon26.replay.repository import ReplayConflict, ReplayStoreUnavailable, UnknownConsultation, UnknownReplay

from .models import WorkbenchRequest, WorkbenchResult
from .service import Workbench, WorkbenchConflict


def build_workbench_router(workbench: Workbench) -> APIRouter:
    router = APIRouter(tags=["consultation workbench"])

    @router.post("/api/v1/consultations/{consultation_id}/replays/{replay_id}/workbench", response_model=WorkbenchResult)
    def run(consultation_id: Identifier, replay_id: Identifier, command: WorkbenchRequest) -> WorkbenchResult:
        try:
            return workbench.run(consultation_id, replay_id, command)
        except (UnknownConsultation, UnknownReplay):
            raise HTTPException(status_code=404, detail="Synthetic consultation or replay not found") from None
        except (ReplayConflict, WorkbenchConflict):
            raise HTTPException(status_code=409, detail="Replay context changed; reload the snapshot") from None
        except ReplayStoreUnavailable:
            raise HTTPException(status_code=503, detail="Replay storage unavailable") from None
        except UnknownCandidate:
            raise HTTPException(status_code=422, detail="Unknown candidate: no recorded class mapping") from None

    return router
