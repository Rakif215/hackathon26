import json
import pytest

from hackathon26.replay.models import AdvanceReplay, StartReplay
from hackathon26.replay.repository import ReplayRepository, ReplayConflict, ReplayStoreUnavailable, UnknownReplay


class Rows:
    def __init__(self, rows): self.rows=rows
    def fetchall(self): return self.rows


class Connection:
    def __init__(self):
        self.audit={}; self.pending={}; self.commits=0; self.fail_write=False
        self.script=[(11,1,"DOCTOR","What tablets do you take?",0),
                     (12,2,"PATIENT","I take the long white one.",1000)]
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def execute(self,sql,params):
        if "FROM MEDGUARD.CONSULTATION c" in sql:
            return Rows([(1,"Dr. Demo","2026-11-13 09:00:00","synthetic scenario")])
        if "FROM MEDGUARD.UTTERANCE" in sql: return Rows(self.script)
        if sql.startswith("SELECT EVENT_TYPE"):
            event=self.audit.get(params["audit_id"])
            return Rows([event] if event else [])
        if sql.startswith("SELECT DETAIL"):
            return Rows([(event[2],) for event in self.audit.values() if event[0]=="REPLAY_STEP" and event[1]==params["consultation_id"]])
        if sql.startswith("SELECT AUDIT_ID"):
            return Rows([(audit_id,event[2]) for audit_id,event in self.audit.items() if event[0]=="REPLAY_STEP" and event[1]==params["consultation_id"]])
        if sql.startswith("INSERT INTO MEDGUARD.AUDIT_LOG"):
            if self.fail_write: raise OSError("private write details")
            if params["audit_id"] in self.audit: raise ValueError("duplicate ID")
            self.pending[params["audit_id"]]=(params["event_type"],params["consultation_id"],params["detail"])
            return Rows([])
        raise AssertionError("Unexpected SQL")
    def commit(self): self.audit.update(self.pending); self.pending.clear(); self.commits+=1
    def rollback(self): self.pending.clear()


def repo(conn):
    def factory(**kwargs):
        assert kwargs=={"autocommit":False}
        return conn
    return ReplayRepository(factory)


def start(store): return store.start(1,StartReplay(idempotency_key="start-key-001"))


def test_start_retry_and_restore_are_durable_without_advancing():
    conn=Connection(); store=repo(conn)
    first=start(store)
    assert first.sequence==0 and first.status=="READY"
    assert start(store)==first
    assert store.get(1,first.replay_id)==first
    assert conn.commits==1


def test_advance_retries_and_listener_snapshot():
    conn=Connection(); store=repo(conn); session=start(store)
    command=AdvanceReplay(idempotency_key="advance-key-001",expected_sequence=0)
    step=store.advance(1,session.replay_id,command)
    assert step.sequence==1 and len(step.utterances)==1
    assert store.advance(1,session.replay_id,command)==step
    final=store.advance(1,session.replay_id,AdvanceReplay(idempotency_key="advance-key-002",expected_sequence=1))
    assert final.status=="COMPLETED"
    assert final.last_analysis.mentions[0].raw_text=="the long white one"
    assert final.last_analysis.persisted is False
    assert store.get(1,session.replay_id)==final
    assert conn.commits==3


def test_stale_sequence_and_reused_key_are_conflicts():
    conn=Connection(); store=repo(conn); session=start(store)
    store.advance(1,session.replay_id,AdvanceReplay(idempotency_key="advance-key-001",expected_sequence=0))
    with pytest.raises(ReplayConflict):
        store.advance(1,session.replay_id,AdvanceReplay(idempotency_key="advance-key-other",expected_sequence=0))
    with pytest.raises(ReplayConflict):
        store.advance(1,session.replay_id,AdvanceReplay(idempotency_key="advance-key-001",expected_sequence=1))


def test_changed_script_is_not_reinterpreted_as_the_old_replay():
    conn=Connection(); store=repo(conn); session=start(store)
    conn.script[1]=(12,2,"PATIENT","Changed text.",1000)
    with pytest.raises(ReplayConflict): store.get(1,session.replay_id)


def test_wrong_consultation_cannot_resume_a_replay():
    conn=Connection(); store=repo(conn); session=start(store)
    with pytest.raises(UnknownReplay): store.get(2,session.replay_id)


def test_write_failure_never_returns_a_saved_cursor():
    conn=Connection(); store=repo(conn); session=start(store); conn.fail_write=True
    with pytest.raises(ReplayStoreUnavailable):
        store.advance(1,session.replay_id,AdvanceReplay(idempotency_key="advance-key-001",expected_sequence=0))
    assert store.get(1,session.replay_id).sequence==0


def test_bad_script_gap_is_reported_as_unavailable():
    conn=Connection(); conn.script[1]=(12,3,"PATIENT","text",1000)
    with pytest.raises(ReplayStoreUnavailable): start(repo(conn))


def test_malformed_start_event_is_controlled_storage_failure():
    conn=Connection(); store=repo(conn); session=start(store)
    conn.audit[session.replay_id]=("REPLAY_STARTED",1,"[]")
    with pytest.raises(ReplayStoreUnavailable): store.get(1,session.replay_id)


@pytest.mark.parametrize("sequence",[True,1])
def test_noncanonical_progress_identity_or_boolean_sequence_is_rejected(sequence):
    conn=Connection(); store=repo(conn); session=start(store)
    conn.audit[42]=("REPLAY_STEP",1,json.dumps({"v":1,"replay_id":session.replay_id,"sequence":sequence,"key":"advance-key-001"}))
    with pytest.raises(ReplayStoreUnavailable): store.get(1,session.replay_id)


def test_blank_script_is_rejected_before_any_progress_is_committed():
    conn=Connection(); conn.script[0]=(11,1,"DOCTOR","   ",0)
    with pytest.raises(ReplayStoreUnavailable): start(repo(conn))
    assert conn.commits==0


def test_identical_concurrent_step_before_insert_is_replayed():
    conn=Connection(); store=repo(conn); session=start(store)
    original=conn.execute
    def race(sql,params):
        if sql.startswith("SELECT EVENT_TYPE") and params["audit_id"]!=session.replay_id and params["audit_id"] not in conn.audit:
            conn.audit[params["audit_id"]]=("REPLAY_STEP",1,json.dumps({"v":1,"replay_id":session.replay_id,"sequence":1,"key":"advance-key-001"}))
        return original(sql,params)
    conn.execute=race
    result=store.advance(1,session.replay_id,AdvanceReplay(idempotency_key="advance-key-001",expected_sequence=0))
    assert result.sequence==1
    assert conn.commits==1
