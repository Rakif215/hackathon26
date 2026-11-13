import json

import pytest
from pydantic import ValidationError

from hackathon26.reviews.models import ReviewRequest
from hackathon26.reviews.repository import ReviewRepository, ReviewConflict, ReviewStoreUnavailable, UnknownFinding


def command(**updates):
    return ReviewRequest(**({"idempotency_key": "review-key-001", "reviewer": "Dr. Demo",
                            "decision": "ACCEPTED", "note": "Evidence reviewed"} | updates))


class Rows:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class Connection:
    def __init__(self):
        self.audit = {}
        self.reviews = {}
        self.commits = 0
        self.rollbacks = 0
        self.finding_exists = True
        self.fail_audit = False
        self.pending_reviews = {}
        self.pending_audit = {}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params):
        if sql.startswith("SELECT DETAIL"):
            value = self.audit.get(params["audit_id"])
            return Rows([(value,)] if value else [])
        if "FROM MEDGUARD.FINDING f" in sql:
            return Rows([(params["finding_id"],)] if self.finding_exists else [])
        if sql.startswith("SELECT REVIEW_ID"):
            return Rows([(params["finding_id"],)] if params["finding_id"] in self.reviews else [])
        if sql.startswith("INSERT INTO MEDGUARD.CLINICIAN_REVIEW"):
            self.pending_reviews[params["review_id"]] = params
            return Rows([])
        if sql.startswith("INSERT INTO MEDGUARD.AUDIT_LOG"):
            if self.fail_audit: raise OSError("private write failure")
            self.pending_audit[params["audit_id"]] = params["detail"]
            return Rows([])
        raise AssertionError("Unexpected SQL")
    def commit(self):
        self.reviews.update(self.pending_reviews); self.audit.update(self.pending_audit)
        self.pending_reviews.clear(); self.pending_audit.clear(); self.commits += 1
    def rollback(self):
        self.pending_reviews.clear(); self.pending_audit.clear(); self.rollbacks += 1


def repository(conn):
    def factory(**kwargs):
        assert kwargs == {"autocommit": False}
        return conn
    return ReviewRepository(factory)


def test_review_and_audit_commit_together():
    conn = Connection()
    result = repository(conn).save(1, 9, command())
    assert result.persisted is True
    assert result.decision == "ACCEPTED"
    assert len(conn.reviews) == len(conn.audit) == conn.commits == 1
    detail = json.loads(next(iter(conn.audit.values())))
    assert detail["result"]["finding_id"] == 9


def test_identical_retry_returns_same_result_without_another_write():
    conn = Connection(); repo = repository(conn)
    first = repo.save(1, 9, command())
    assert repo.save(1, 9, command()) == first
    assert conn.commits == 1


def test_key_reuse_with_different_body_is_conflict():
    conn = Connection(); repo = repository(conn)
    repo.save(1, 9, command())
    with pytest.raises(ReviewConflict): repo.save(1, 9, command(decision="DEFERRED"))


def test_new_key_does_not_silently_overwrite_prior_review():
    conn = Connection(); repo = repository(conn)
    repo.save(1, 9, command())
    with pytest.raises(ReviewConflict): repo.save(1, 9, command(idempotency_key="another-key-001"))


def test_unknown_or_wrong_consultation_finding_is_not_written():
    conn = Connection(); conn.finding_exists = False
    with pytest.raises(UnknownFinding): repository(conn).save(1, 9, command())
    assert conn.commits == 0


def test_failed_audit_rolls_back_review_and_does_not_claim_saved():
    conn = Connection(); conn.fail_audit = True
    with pytest.raises(ReviewStoreUnavailable): repository(conn).save(1, 9, command())
    assert conn.reviews == conn.audit == {}
    assert conn.rollbacks == 1


@pytest.mark.parametrize("updates", [{"decision": "OVERRIDDEN", "note": "  "},
                                    {"reviewer": " "}, {"decision": "AUTO_ACCEPT"},
                                    {"idempotency_key": ""}])
def test_invalid_or_unexplained_review_is_rejected(updates):
    with pytest.raises(ValidationError): command(**updates)
