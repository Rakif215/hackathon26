"""Canonical review/audit transaction. Does not create or alter schema."""

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Protocol

from pyexasol import ExaConnection, ExaError

from hackathon26.db import connect

from .models import ReviewRequest, ReviewResult


class UnknownFinding(Exception):
    """Finding is absent, belongs to another consultation, or is not synthetic."""


class ReviewConflict(Exception):
    """Command key is reused or a finding already has a review."""


class ReviewStoreUnavailable(Exception):
    """Review and audit persistence could not be confirmed."""


class ReviewStore(Protocol):
    def save(self, consultation_id: int, finding_id: int, command: ReviewRequest) -> ReviewResult: ...


def _identity(consultation_id: int, finding_id: int, command: ReviewRequest) -> tuple[int, str]:
    key = json.dumps([consultation_id, command.idempotency_key], separators=(",", ":"))
    # Canonical IDs are DECIMAL(10,0). Collisions fail closed by comparing the
    # full fingerprint in the audit record, rather than treating it as a retry.
    audit_id = int.from_bytes(sha256(key.encode()).digest(), "big") % 9_999_999_999 + 1
    body = json.dumps([consultation_id, finding_id, command.model_dump()],
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return audit_id, sha256(body.encode()).hexdigest()


def _replay(conn: ExaConnection, audit_id: int, fingerprint: str) -> ReviewResult | None:
    rows = conn.execute("SELECT DETAIL FROM MEDGUARD.AUDIT_LOG WHERE AUDIT_ID = {audit_id!d}",
                        {"audit_id": audit_id}).fetchall()
    if not rows:
        return None
    try:
        detail = json.loads(rows[0][0])
        if not isinstance(detail, dict) or detail.get("fingerprint") != fingerprint:
            raise ReviewConflict("Request key reused or audit identifier collision")
        return ReviewResult.model_validate(detail["result"])
    except (ValueError, KeyError, TypeError) as error:
        raise ReviewConflict("Existing audit record cannot be replayed") from error


def _has_review(conn: ExaConnection, finding_id: int) -> bool:
    return bool(conn.execute("SELECT REVIEW_ID FROM MEDGUARD.CLINICIAN_REVIEW WHERE FINDING_ID = {finding_id!d}",
                             {"finding_id": finding_id}).fetchall())


class ReviewRepository:
    def __init__(self, connection_factory: Callable[..., ExaConnection] = connect):
        self._connect = connection_factory

    def save(self, consultation_id: int, finding_id: int, command: ReviewRequest) -> ReviewResult:
        audit_id, fingerprint = _identity(consultation_id, finding_id, command)
        try:
            with self._connect(autocommit=False) as conn:
                try:
                    return self._save(conn, consultation_id, finding_id, command, audit_id, fingerprint)
                except (ExaError, OSError, RuntimeError, ValueError) as error:
                    conn.rollback()
                    # A concurrent identical request or an uncertain commit may
                    # already have completed. Confirm persisted state before replying.
                    replay = _replay(conn, audit_id, fingerprint)
                    if replay is not None:
                        return replay
                    if _has_review(conn, finding_id):
                        raise ReviewConflict("Finding already reviewed") from error
                    raise ReviewStoreUnavailable("Review persistence unavailable") from error
        except (ExaError, OSError, RuntimeError, ValueError) as error:
            raise ReviewStoreUnavailable("Review persistence unavailable") from error

    def _save(self, conn: ExaConnection, consultation_id: int, finding_id: int,
              command: ReviewRequest, audit_id: int, fingerprint: str) -> ReviewResult:
        replay = _replay(conn, audit_id, fingerprint)
        if replay is not None:
            return replay
        finding = conn.execute(
            "SELECT f.FINDING_ID FROM MEDGUARD.FINDING f "
            "JOIN MEDGUARD.CONSULTATION c ON c.CONSULT_ID = f.CONSULT_ID "
            "JOIN MEDGUARD.PATIENT p ON p.PATIENT_ID = c.PATIENT_ID "
            "WHERE f.FINDING_ID = {finding_id!d} AND f.CONSULT_ID = {consultation_id!d} AND p.IS_SYNTHETIC = TRUE",
            {"finding_id": finding_id, "consultation_id": consultation_id},
        ).fetchall()
        if not finding:
            raise UnknownFinding()
        if _has_review(conn, finding_id):
            raise ReviewConflict("Finding already reviewed; amendments are not supported yet")
        now = datetime.now(timezone.utc)
        result = ReviewResult(review_id=finding_id, consultation_id=consultation_id,
                              finding_id=finding_id, reviewer=command.reviewer,
                              decision=command.decision, note=command.note, decided_at=now)
        detail = json.dumps({"fingerprint": fingerprint, "result": result.model_dump(mode="json")},
                            ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            "INSERT INTO MEDGUARD.CLINICIAN_REVIEW "
            "(REVIEW_ID, FINDING_ID, DECISION, REVIEWER, NOTE, DECIDED_AT) "
            "VALUES ({review_id!d}, {finding_id!d}, {decision}, {reviewer}, {note}, "
            "TO_TIMESTAMP({decided_at}, 'YYYY-MM-DD HH24:MI:SS.FF6'))",
            {"review_id": result.review_id, "finding_id": finding_id, "decision": command.decision,
             "reviewer": command.reviewer, "note": command.note,
             "decided_at": now.strftime("%Y-%m-%d %H:%M:%S.%f")},
        )
        conn.execute(
            "INSERT INTO MEDGUARD.AUDIT_LOG (AUDIT_ID, CONSULT_ID, EVENT_TYPE, DETAIL, CREATED_AT) "
            "VALUES ({audit_id!d}, {consultation_id!d}, 'REVIEW', {detail}, CURRENT_TIMESTAMP)",
            {"audit_id": audit_id, "consultation_id": consultation_id, "detail": detail},
        )
        conn.commit()
        return result
