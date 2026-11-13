"""Replay progress uses canonical AUDIT_LOG; seeded script rows are read-only."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

from pyexasol import ExaConnection, ExaError

from hackathon26.db import connect
from hackathon26.listener.detect import detect_mentions
from hackathon26.listener.models import TranscriptSegment

from .models import AdvanceReplay, ReplaySnapshot, ScriptUtterance, StartReplay, StartEvent, StepEvent


class UnknownReplay(Exception):
    """Replay is absent or belongs to a different consultation."""


class UnknownConsultation(Exception):
    """No seeded consultation attached to a synthetic patient."""


class ReplayConflict(Exception):
    """Stale cursor, changed script, reused key or audit-ID collision."""


class ReplayStoreUnavailable(Exception):
    """Script/progress could not be loaded or committed."""


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _event_id(*parts) -> int:
    return int.from_bytes(sha256(_json(parts).encode()).digest(), "big") % 9_999_999_999 + 1


def _event(conn, audit_id):
    rows = conn.execute("SELECT EVENT_TYPE, CONSULT_ID, DETAIL FROM MEDGUARD.AUDIT_LOG WHERE AUDIT_ID = {audit_id!d}",
                        {"audit_id": audit_id}).fetchall()
    return rows[0] if rows else None


def _insert(conn, audit_id, consultation_id, event_type, detail):
    conn.execute("INSERT INTO MEDGUARD.AUDIT_LOG (AUDIT_ID, CONSULT_ID, EVENT_TYPE, DETAIL, CREATED_AT) "
                 "VALUES ({audit_id!d}, {consultation_id!d}, {event_type}, {detail}, CURRENT_TIMESTAMP)",
                 {"audit_id": audit_id, "consultation_id": consultation_id, "event_type": event_type, "detail": _json(detail)})


def _script(conn, consultation_id):
    rows = conn.execute(
        "SELECT c.PATIENT_ID, c.CLINICIAN, c.STARTED_AT, c.SCENARIO FROM MEDGUARD.CONSULTATION c "
        "JOIN MEDGUARD.PATIENT p ON p.PATIENT_ID = c.PATIENT_ID "
        "WHERE c.CONSULT_ID = {consultation_id!d} AND p.IS_SYNTHETIC = TRUE",
        {"consultation_id": consultation_id},
    ).fetchall()
    if not rows:
        raise UnknownConsultation()
    patient_id, clinician, started_at, scenario = rows[0]
    started = datetime.fromisoformat(str(started_at))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    utterances = [ScriptUtterance(utterance_id=row[0], sequence=row[1], speaker=row[2], text=row[3], offset_ms=row[4])
                  for row in conn.execute(
                      "SELECT UTTERANCE_ID, SEQ, SPEAKER, UTTERANCE_TEXT, OFFSET_MS FROM MEDGUARD.UTTERANCE "
                      "WHERE CONSULT_ID = {consultation_id!d} ORDER BY SEQ, UTTERANCE_ID", {"consultation_id": consultation_id}).fetchall()]
    if not utterances or len(utterances) > 1000 or [u.sequence for u in utterances] != list(range(1, len(utterances) + 1)):
        raise ValueError("Script must have contiguous unique sequences starting at one")
    fingerprint = sha256(_json([int(patient_id), clinician, started.isoformat(), scenario,
                               [u.model_dump() for u in utterances]]).encode()).hexdigest()
    return int(patient_id), started, utterances, fingerprint


def _state(conn, consultation_id, replay_id):
    event = _event(conn, replay_id)
    if event is None or event[0] != "REPLAY_STARTED" or int(event[1]) != consultation_id:
        raise UnknownReplay()
    start = StartEvent.model_validate_json(event[2]).model_dump(mode="json")
    if start["replay_id"] != replay_id or _event_id("REPLAY_STARTED", consultation_id, start["start_key"]) != replay_id:
        raise ReplayConflict("Replay identifier collision")
    patient_id, started, utterances, fingerprint = _script(conn, consultation_id)
    if start.get("script_hash") != fingerprint:
        raise ReplayConflict("Script changed; start a new replay")
    steps = []
    for row in conn.execute("SELECT AUDIT_ID, DETAIL FROM MEDGUARD.AUDIT_LOG WHERE CONSULT_ID = {consultation_id!d} "
                            "AND EVENT_TYPE = 'REPLAY_STEP'", {"consultation_id": consultation_id}).fetchall():
        detail = StepEvent.model_validate_json(row[1]).model_dump()
        if int(row[0]) != _event_id("REPLAY_STEP", detail["replay_id"], detail["sequence"]):
            raise ValueError("Noncanonical replay step identifier")
        if detail["replay_id"] == replay_id:
            steps.append(detail)
    steps.sort(key=lambda step: step["sequence"])
    if ([step["sequence"] for step in steps] != list(range(1, len(steps) + 1))
            or len(steps) > len(utterances) or len({step["key"] for step in steps}) != len(steps)):
        raise ValueError("Inconsistent replay progress")
    return start, steps, patient_id, started, utterances


def _snapshot(consultation_id, replay_id, state):
    start, steps, patient_id, started, utterances = state
    sequence = len(steps)
    segment = None
    if sequence:
        utterance = utterances[sequence - 1]
        segment = TranscriptSegment(schema_version="1", event_id=f"replay-{replay_id}-step-{sequence}",
                                    consultation_id=str(consultation_id), segment_id=str(utterance.utterance_id),
                                    revision=1, sequence=sequence, speaker=utterance.speaker, text=utterance.text,
                                    is_final=True, source="script", occurred_at=started + timedelta(milliseconds=utterance.offset_ms))
    return ReplaySnapshot(consultation_id=consultation_id, patient_id=patient_id, replay_id=replay_id,
                          created_at=start["created_at"], sequence=sequence, total_utterances=len(utterances),
                          status="COMPLETED" if sequence == len(utterances) else "PLAYING" if sequence else "READY",
                          utterances=utterances[:sequence], last_segment=segment,
                          last_analysis=detect_mentions(segment) if segment else None,
                          limitations=["Only replay progress is persisted; listener analysis is recomputed using the current detector version.",
                                       "No medication confirmation, evidence check, model call or clinician decision is triggered by navigation.",
                                       "Naive seeded consultation timestamps are interpreted as UTC for this synthetic replay."])


_STORAGE_ERRORS = (ExaError, OSError, RuntimeError, ValueError, KeyError, TypeError)


class ReplayRepository:
    def __init__(self, connection_factory: Callable[..., ExaConnection] = connect):
        self._connect = connection_factory

    def start(self, consultation_id: int, command: StartReplay) -> ReplaySnapshot:
        replay_id = _event_id("REPLAY_STARTED", consultation_id, command.idempotency_key)
        try:
            with self._connect(autocommit=False) as conn:
                patient_id, started, utterances, fingerprint = _script(conn, consultation_id)
                event = _event(conn, replay_id)
                if event is not None:
                    if event[0] != "REPLAY_STARTED" or int(event[1]) != consultation_id or StartEvent.model_validate_json(event[2]).start_key != command.idempotency_key:
                        raise ReplayConflict("Start key or audit identifier collision")
                else:
                    detail = {"v": 1, "replay_id": replay_id, "start_key": command.idempotency_key,
                              "script_hash": fingerprint, "created_at": datetime.now(timezone.utc).isoformat()}
                    try:
                        _insert(conn, replay_id, consultation_id, "REPLAY_STARTED", detail)
                        conn.commit()
                    except _STORAGE_ERRORS:
                        conn.rollback()
                        event = _event(conn, replay_id)
                        if event is None:
                            raise
                        if event[0] != "REPLAY_STARTED" or int(event[1]) != consultation_id or StartEvent.model_validate_json(event[2]).start_key != command.idempotency_key:
                            raise ReplayConflict("Start key or audit identifier collision")
                return _snapshot(consultation_id, replay_id, _state(conn, consultation_id, replay_id))
        except _STORAGE_ERRORS as error:
            raise ReplayStoreUnavailable("Replay storage unavailable or incompatible") from error

    def get(self, consultation_id: int, replay_id: int) -> ReplaySnapshot:
        try:
            with self._connect(autocommit=False) as conn:
                return _snapshot(consultation_id, replay_id, _state(conn, consultation_id, replay_id))
        except _STORAGE_ERRORS as error:
            raise ReplayStoreUnavailable("Replay storage unavailable or incompatible") from error

    def advance(self, consultation_id: int, replay_id: int, command: AdvanceReplay) -> ReplaySnapshot:
        try:
            with self._connect(autocommit=False) as conn:
                state = _state(conn, consultation_id, replay_id)
                start, steps, _, _, utterances = state
                for step in steps:
                    if step["key"] == command.idempotency_key:
                        if step["sequence"] != command.expected_sequence + 1:
                            raise ReplayConflict("Advance key reused for a different sequence")
                        return _snapshot(consultation_id, replay_id, state)
                if command.expected_sequence != len(steps) or len(steps) == len(utterances):
                    raise ReplayConflict("Stale sequence or replay already completed")
                sequence = len(steps) + 1
                audit_id = _event_id("REPLAY_STEP", replay_id, sequence)
                detail = {"v": 1, "replay_id": replay_id, "sequence": sequence, "key": command.idempotency_key}
                existing = _event(conn, audit_id)
                if existing is not None:
                    if existing[0] != "REPLAY_STEP" or int(existing[1]) != consultation_id or StepEvent.model_validate_json(existing[2]).model_dump() != detail:
                        raise ReplayConflict("Step audit identifier collision")
                    return _snapshot(consultation_id, replay_id, _state(conn, consultation_id, replay_id))
                try:
                    _insert(conn, audit_id, consultation_id, "REPLAY_STEP", detail)
                    conn.commit()
                except _STORAGE_ERRORS:
                    conn.rollback()
                    event = _event(conn, audit_id)
                    if event is None:
                        raise
                    if event[0] != "REPLAY_STEP" or int(event[1]) != consultation_id or StepEvent.model_validate_json(event[2]).model_dump() != detail:
                        raise ReplayConflict("Concurrent step or audit identifier conflict")
                return _snapshot(consultation_id, replay_id, _state(conn, consultation_id, replay_id))
        except _STORAGE_ERRORS as error:
            raise ReplayStoreUnavailable("Replay storage unavailable or incompatible") from error
