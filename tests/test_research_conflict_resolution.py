"""Supervised resolution preserves evidence, controls and idempotency."""
import json
from pathlib import Path

import pytest

from mova_fpl.ops.strategy import StrategicContextService
from test_research_evidence import SOURCE, _fetcher, _v2_result
from test_strategic_context import _runtime, _plan


@pytest.fixture
def resolution(tmp_path):
    config, db, _, cycle_id = _runtime(tmp_path)
    service = StrategicContextService(config, db, evidence_fetcher=_fetcher(config.research_root))
    service.activate_plan(_plan(), actor="test", reason="fixture")
    queued = service.enqueue(force=True, actor="test", reason="fixture",
                             idempotency_key="resolution-fixture")
    run = db.research_run(queued["research_run_id"])
    request = json.loads(Path(run["request_path"]).read_text())
    result = _v2_result(run, cycle_id, request["manifest"]["research_summary"]["focus"])
    result["conflicts"] = [{"subject": "Player One", "claim_type": "availability",
                            "description": "Prior appearance vs current doubt",
                            "source_urls": [SOURCE], "status": "unresolved"}]
    out = config.research_root / "outbox" / f"{run['research_run_id']}.result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result))
    assert service.import_ready()["results"][0]["status"] == "imported"
    with db.connect(readonly=True) as con:
        conflict = dict(con.execute("SELECT * FROM research_conflicts").fetchone())
        doc = dict(con.execute("SELECT * FROM research_documents").fetchone())
    kwargs = dict(cycle_id=cycle_id, document_ids=[doc["document_id"]], actor="operator",
                  reason="The prior appearance is not clearance for the next fixture.",
                  idempotency_key="resolve:test")
    return db, conflict, doc, kwargs


def test_resolution_is_atomic_audited_idempotent_and_does_not_promote(resolution):
    db, conflict, doc, kwargs = resolution
    with db.connect(readonly=True) as con:
        controls = list(con.execute("SELECT * FROM runtime_controls"))
        signals = list(con.execute("SELECT * FROM research_signals"))
    result = db.resolve_research_conflict(conflict["conflict_id"], **kwargs)
    assert result["status"] == "resolved" and result["requires_new_decision"]
    assert not result["fpl_state_mutated"]
    replay = db.resolve_research_conflict(conflict["conflict_id"], **kwargs)
    assert replay["status"] == "reused" and replay["event_id"] == result["event_id"]
    with db.connect(readonly=True) as con:
        assert list(con.execute("SELECT * FROM runtime_controls")) == controls
        assert list(con.execute("SELECT * FROM research_signals")) == signals
        audit = con.execute("SELECT payload_json FROM audit_events WHERE event_id=?",
                            (result["event_id"],)).fetchone()
        payload = json.loads(audit[0])
        assert payload["before"]["status"] == "unresolved"
        assert payload["evidence"][0]["artifact_sha256"] == doc["artifact_sha256"]
    with pytest.raises(ValueError, match="otro contenido"):
        db.resolve_research_conflict(conflict["conflict_id"], **(kwargs | {"reason": "changed"}))
    with pytest.raises(ValueError, match="ya resuelto"):
        db.resolve_research_conflict(conflict["conflict_id"], **(kwargs | {"idempotency_key": "other"}))


@pytest.mark.parametrize("failure", ["missing_actor", "wrong_cycle", "wrong_document",
                                    "no_documents", "tampered_artifact", "unverified", "excerpt"])
def test_resolution_fails_closed(resolution, failure):
    db, conflict, doc, kwargs = resolution
    if failure == "missing_actor":
        kwargs["actor"] = None
    elif failure == "wrong_cycle":
        kwargs["cycle_id"] = "another-cycle"
    elif failure == "wrong_document":
        kwargs["document_ids"] = ["missing"]
    elif failure == "no_documents":
        kwargs["document_ids"] = []
    elif failure == "tampered_artifact":
        Path(doc["artifact_path"]).write_text("tampered")
    else:
        with db.transaction() as con:
            if failure == "unverified":
                con.execute("UPDATE research_documents SET fetch_status='failed'")
            else:
                con.execute("UPDATE research_documents SET excerpt='changed'")
    with pytest.raises(ValueError):
        db.resolve_research_conflict(conflict["conflict_id"], **kwargs)
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT status FROM research_conflicts").fetchone()[0] == "unresolved"
        assert con.execute("SELECT count(*) FROM audit_events WHERE "
                           "event_type='research_conflict_resolved'").fetchone()[0] == 0
