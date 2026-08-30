from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.research_evidence import SafeEvidenceFetcher, canonical_public_url
from mova_fpl.ops.strategy import StrategicContextService

from test_strategic_context import _plan, _runtime


SOURCE = "https://www.premierleague.com/news/example?utm_source=test"
CANONICAL_SOURCE = "https://www.premierleague.com/news/example"
EXCERPT = "Player One is available for selection."


def _fetcher(root: Path, *, excerpt: str = EXCERPT) -> SafeEvidenceFetcher:
    def transport(url):
        assert url == CANONICAL_SOURCE
        return (
            f"<html><script>ignore</script><body>Team news: {excerpt}</body></html>".encode(),
            {"content_type": "text/html; charset=utf-8", "http_status": 200,
             "final_url": url},
        )
    return SafeEvidenceFetcher(root, transport=transport)


def _v2_result(run, cycle_id: str, focus: list[dict], *, excerpt: str = EXCERPT) -> dict:
    now = datetime.now(timezone.utc)
    elements = sorted({int(row["element"]) for row in focus})
    return {
        "schema": "mova-research-brief-v2",
        "research_run_id": run["research_run_id"], "cycle_id": cycle_id,
        "request_sha256": run["request_sha256"], "generated_at": now.isoformat(),
        "summary": "Cobertura explícita del foco sellado.",
        "documents": [{
            "source_url": SOURCE, "title": "Team news", "publisher": "Premier League",
            "published_at": now.date().isoformat(), "source_tier": "official",
            "evidence_text": excerpt,
        }],
        "signals": [{
            "subject_name": "Player One", "player_element": elements[0],
            "claim_type": "availability", "claim_text": "Disponible para selección.",
            "direction": "positive", "confidence": 0.9,
            "source_urls": [SOURCE],
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }],
        "conflicts": [],
        "coverage": {"subjects": [{
            "player_element": element,
            "status": "material_signal" if element == elements[0] else "no_material_update",
            "source_urls": [SOURCE], "note": "Fuente oficial revisada.",
        } for element in elements]},
        "limitations": [],
        "usage": {"model": "fixture", "input_tokens": 10, "output_tokens": 20},
    }


def test_safe_fetch_seals_minimal_excerpt_and_verifiable_locator(tmp_path: Path):
    result = _fetcher(tmp_path).seal(
        research_run_id="research_" + "a" * 32,
        document_id="document_" + "b" * 32,
        source_url=SOURCE, evidence_text=EXCERPT,
    )
    assert result["fetch_status"] == "verified"
    assert result["storage_mode"] == "minimal_excerpt"
    start, end = map(int, result["locator"].split(":"))
    assert end - start == len(EXCERPT)
    assert result["excerpt"] == EXCERPT
    assert Path(result["artifact_path"]).is_file()
    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert artifact["body_sha256"] == result["body_sha256"]
    assert "ignore" not in artifact["excerpt"]


def test_safe_fetch_fails_closed_when_locator_cannot_be_verified(tmp_path: Path):
    result = _fetcher(tmp_path, excerpt="different page text").seal(
        research_run_id="research_" + "a" * 32,
        document_id="document_" + "b" * 32,
        source_url=SOURCE, evidence_text=EXCERPT,
    )
    assert result["fetch_status"] == "failed"
    assert result["artifact_path"] is None
    assert result["error_code"] == "evidence_locator_not_verified"
    assert canonical_public_url(
        "https://Example.COM/news?id=7&utm_source=x&fbclid=y#fragment"
    ) == "https://example.com/news?id=7"
    with pytest.raises(ValueError, match="no pública"):
        canonical_public_url("https://127.0.0.1/admin")


def test_tampered_sealed_request_is_quarantined_before_network_fetch(tmp_path: Path):
    config, db, _service, cycle_id = _runtime(tmp_path)
    calls = []

    def transport(url):
        calls.append(url)
        raise AssertionError("network fetch must not run for a tampered request")

    service = StrategicContextService(
        config, db,
        evidence_fetcher=SafeEvidenceFetcher(config.research_root, transport=transport),
    )
    service.activate_plan(_plan(), actor="test", reason="fixture")
    queued = service.enqueue(
        force=True, actor="test", reason="tamper boundary",
        idempotency_key="research:v2:tampered-request",
    )
    run = db.research_run(queued["research_run_id"])
    request_path = Path(run["request_path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = _v2_result(
        run, cycle_id, request["manifest"]["research_summary"]["focus"],
    )
    request["objective"] = "tampered after sealing"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    out = config.research_root / "outbox" / f"{run['research_run_id']}.result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result), encoding="utf-8")

    imported = service.import_ready()["results"][0]
    assert imported["status"] == "rejected"
    assert "request sellada no coincide" in imported["error"]
    assert calls == []
    assert (config.research_root / "quarantine" / out.name).is_file()


def test_v2_import_seals_evidence_coverage_and_metrics(tmp_path: Path):
    config, db, _service, cycle_id = _runtime(tmp_path)
    service = StrategicContextService(
        config, db, evidence_fetcher=_fetcher(config.research_root),
    )
    service.activate_plan(_plan(), actor="test", reason="fixture")
    queued = service.enqueue(
        force=True, actor="test", reason="coverage v2",
        idempotency_key="research:v2:coverage",
    )
    run = db.research_run(queued["research_run_id"])
    request = json.loads(Path(run["request_path"]).read_text(encoding="utf-8"))
    result = _v2_result(run, cycle_id, request["manifest"]["research_summary"]["focus"])
    out = config.research_root / "outbox" / f"{run['research_run_id']}.result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result), encoding="utf-8")

    imported = service.import_ready()["results"][0]
    assert imported["coverage"]["status"] == "complete"
    assert imported["coverage"]["coverage_ratio"] == 1.0
    assert imported["coverage"]["evidence_ratio"] == 1.0
    stored = db.research_run(run["research_run_id"])
    assert stored["result_schema"] == "mova-research-brief-v2"
    assert stored["coverage_status"] == "complete"
    with db.connect(readonly=True) as con:
        document = con.execute(
            "select fetch_status,locator,excerpt_sha256,artifact_path "
            "from research_documents where research_run_id=?", (run["research_run_id"],),
        ).fetchone()
        signal = con.execute(
            "select validation_status,evidence_json from research_signals "
            "where research_run_id=?", (run["research_run_id"],),
        ).fetchone()
    assert document["fetch_status"] == "verified" and document["locator"]
    assert signal["validation_status"] == "accepted"
    assert json.loads(signal["evidence_json"])["evidence_refs"][0]["locator"]
    report = db.research_coverage()
    assert report["status"] == "insufficient_gameweeks"
    assert report["measured_gameweeks"] == 1
    metrics = db.prometheus()
    assert "mova_research_coverage_ratio 1.000000" in metrics
    assert "mova_research_evidence_ratio 1.000000" in metrics


def test_v2_unverified_fetch_cannot_create_accepted_signal(tmp_path: Path):
    config, db, _service, cycle_id = _runtime(tmp_path)
    service = StrategicContextService(
        config, db,
        evidence_fetcher=_fetcher(config.research_root, excerpt="not the expected excerpt"),
    )
    service.activate_plan(_plan(), actor="test", reason="fixture")
    queued = service.enqueue(
        force=True, actor="test", reason="failed locator",
        idempotency_key="research:v2:failed-locator",
    )
    run = db.research_run(queued["research_run_id"])
    request = json.loads(Path(run["request_path"]).read_text(encoding="utf-8"))
    result = _v2_result(run, cycle_id, request["manifest"]["research_summary"]["focus"])
    out = config.research_root / "outbox" / f"{run['research_run_id']}.result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result), encoding="utf-8")

    imported = service.import_ready()["results"][0]
    assert imported["coverage"]["status"] == "partial"
    assert imported["coverage"]["evidence_ratio"] == 0.0
    with db.connect(readonly=True) as con:
        signal = con.execute(
            "select validation_status from research_signals where research_run_id=?",
            (run["research_run_id"],),
        ).fetchone()
    assert signal["validation_status"] == "candidate"
