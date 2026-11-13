from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from hackathon26.listener.models import Contract, ListenerResult, TranscriptSegment


class StartReplay(Contract):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")


class AdvanceReplay(StartReplay):
    expected_sequence: int = Field(strict=True, ge=0, le=999999)


class ScriptUtterance(Contract):
    utterance_id: int
    sequence: int = Field(ge=1)
    speaker: Literal["PATIENT", "DOCTOR", "UNKNOWN"]
    text: str = Field(min_length=1, max_length=4000)
    offset_ms: int = Field(ge=0, le=86400000)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Script text must not be blank")
        return value


class StartEvent(Contract):
    v: int = Field(strict=True, ge=1, le=1)
    replay_id: int = Field(strict=True, gt=0, le=9_999_999_999)
    start_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    script_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: AwareDatetime


class StepEvent(Contract):
    v: int = Field(strict=True, ge=1, le=1)
    replay_id: int = Field(strict=True, gt=0, le=9_999_999_999)
    sequence: int = Field(strict=True, ge=1, le=999999)
    key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")


class ReplaySnapshot(Contract):
    consultation_id: int
    patient_id: int
    replay_id: int
    created_at: AwareDatetime
    sequence: int
    total_utterances: int
    status: Literal["READY", "PLAYING", "COMPLETED"]
    utterances: list[ScriptUtterance]
    last_segment: TranscriptSegment | None
    last_analysis: ListenerResult | None
    progress_persisted: Literal[True] = True
    limitations: list[str]
