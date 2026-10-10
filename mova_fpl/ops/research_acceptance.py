"""ADR-011: immutable preregistration, first-run selection, fail-closed acceptance.

The historical report is intentionally unchanged. This module grants no authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.agent_releases import researcher_release
from mova_fpl.ops.db import canonical_json, sha256_json, utcnow

POLICY = {"version": "research-prospective-2026.10.1", "minimum_measured_gameweeks": 3,
          "minimum_coverage_ratio": 0.90, "minimum_evidence_ratio": 0.80,
          "maximum_unresolved_conflicts": 0}


def _time(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("acceptance requires timezone")
    return parsed.astimezone(timezone.utc)


def current_contract(config) -> dict:
    """Pin runtime behavior, not a Git SHA that changes on documentation edits."""
    version, release = researcher_release()
    assets = json.loads(Path(__file__).with_name("research_acceptance_assets.json").read_text())
    sources = ("strategy.py", "research_evidence.py", "research_quality.py",
               "research_acceptance.py", "agent_releases.json", "agent_attempts.py",
               "db.py", "schema.py", "schedule.py")
    implementation = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in sources}
    return {"agent_version": version, "release": release,
            "provider": config.research_provider, "model": config.research_model,
            "reasoning_effort": config.research_reasoning_effort,
            "implementation": implementation, "worker_assets": assets,
            "budget": config.agent_budget_policy(),
            "selection": "first_operational_queued_in_window",
            "max_attempts": 2, "abandonment": "any_failed_or_uncertain_attempt_blocks",
            "historical_signals": "context_only_require_fresh_independent_evidence",
            "policy": POLICY}


def register_cohort(db, config, manifest, *, actor, reason, idempotency_key) -> dict:
    if not all(isinstance(v, str) and v.strip() for v in (actor, reason, idempotency_key)):
        raise ValueError("acceptance requires actor, reason, idempotency_key")
    if manifest.get("schema") != "mova-research-acceptance-manifest-v1":
        raise ValueError("invalid acceptance manifest schema")
    if manifest.get("contract") != current_contract(config):
        raise ValueError("acceptance contract drift")
    slots = manifest.get("slots")
    if not isinstance(slots, list) or len(slots) < 3 or len(slots) > 38:
        raise ValueError("acceptance requires at least three predeclared GWs")
    season = manifest.get("season")
    if not isinstance(season, str) or len(season) != 7:
        raise ValueError("invalid season")
    gws = [slot.get("gw") for slot in slots]
    if any(type(gw) is not int or not 1 <= gw <= 38 for gw in gws) or len(set(gws)) != len(gws):
        raise ValueError("duplicate or invalid GWs")
    digest = sha256_json(manifest)
    cohort_id = "acceptance_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
    now = utcnow()
    with db.transaction() as con:
        existing = con.execute("SELECT * FROM research_acceptance_cohorts WHERE idempotency_key=?",
                               (idempotency_key,)).fetchone()
        if existing:
            if existing["manifest_sha256"] != digest or existing["actor"] != actor or existing["reason"] != reason:
                raise ValueError("acceptance idempotency conflict")
            return {"cohort_id": existing["cohort_id"], "manifest_sha256": digest, "reused": True}
        # Each subsequent cohort needs its own explicit owner approval reference.
        if not manifest.get("approval_reference"):
            raise ValueError("approval_reference required")
        for slot in slots:
            start, end = _time(slot["opens_at"]), _time(slot["deadline_at"])
            if not _time(now) <= start < end:
                raise ValueError("acceptance window must be future")
            cycle_id = f"{season}-gw{slot['gw']:02d}"
            if slot.get("cycle_id") != cycle_id:
                raise ValueError("cycle_id disagrees with season/GW")
            cycle = con.execute("SELECT deadline_at FROM gameweek_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
            if cycle and _time(cycle[0]) != end:
                raise ValueError("deadline disagrees with observed cycle")
            if con.execute("SELECT 1 FROM research_runs WHERE cycle_id=? LIMIT 1", (cycle_id,)).fetchone():
                raise ValueError("acceptance cannot enroll a previously inferred GW")
            # Overlapping cohorts permit picking winners after results; reject them.
            for row in con.execute("SELECT manifest_json FROM research_acceptance_cohorts"):
                if any(s["cycle_id"] == cycle_id for s in json.loads(row[0])["slots"]):
                    raise ValueError("GW already preregistered")
        con.execute("INSERT INTO research_acceptance_cohorts VALUES(?,?,?,?,?,?,?)",
                    (cohort_id, idempotency_key, canonical_json(manifest), digest, now, actor, reason))
        db.append_audit("research_acceptance_registered", actor=actor, subject_type="research_acceptance",
                        subject_id=cohort_id, payload={"reason": reason, "manifest_sha256": digest,
                        "idempotency_key": idempotency_key, "approval_reference": manifest["approval_reference"]}, con=con)
    return {"cohort_id": cohort_id, "manifest_sha256": digest, "registered_at": now, "reused": False}


def bind_first_run(con, payload, *, now):
    """Called in the queue transaction, before publishing a worker request."""
    if payload.get("experiment"):
        return
    for row in con.execute("SELECT * FROM research_acceptance_cohorts ORDER BY registered_at,cohort_id"):
        manifest = json.loads(row["manifest_json"])
        for slot in manifest["slots"]:
            if slot["cycle_id"] != payload["cycle_id"]:
                continue
            # Even a run outside the window is selected and fails, never silently skipped.
            con.execute("INSERT OR IGNORE INTO research_acceptance_slots VALUES(?,?,?,?,?)",
                        (row["cohort_id"], payload["cycle_id"], payload["research_run_id"],
                         sha256_json(payload.get("acceptance_contract")), now))


def acceptance_report(db, config=None) -> dict:
    historical = db.research_coverage()
    now = datetime.now(timezone.utc)
    cohorts = []
    with db.connect(readonly=True) as con:
        for row in con.execute("SELECT * FROM research_acceptance_cohorts ORDER BY registered_at,cohort_id"):
            manifest = json.loads(row["manifest_json"])
            slots = []
            drift = config is None or manifest["contract"] != current_contract(config)
            for slot in manifest["slots"]:
                reasons = []
                bound = con.execute("SELECT * FROM research_acceptance_slots WHERE cohort_id=? AND cycle_id=?",
                                    (row["cohort_id"], slot["cycle_id"])).fetchone()
                run = con.execute("SELECT * FROM research_runs WHERE research_run_id=?", (bound["research_run_id"],)).fetchone() if bound else None
                expired = now > _time(slot["deadline_at"])
                if drift:
                    reasons.append("contract_drift_or_unverified")
                if not run:
                    status = "failed" if expired or drift else "pending"
                    reasons.append("not_executed" if expired else "not_yet_executed")
                else:
                    if bound["contract_sha256"] != sha256_json(manifest["contract"]):
                        reasons.append("run_contract_drift")
                    if not _time(row["registered_at"]) <= _time(run["queued_at"]) or not _time(slot["opens_at"]) <= _time(run["queued_at"]) < _time(slot["deadline_at"]):
                        reasons.append("run_outside_preregistered_window")
                    cycle = con.execute("SELECT deadline_at FROM gameweek_cycles WHERE cycle_id=?", (slot["cycle_id"],)).fetchone()
                    if not cycle or _time(cycle[0]) != _time(slot["deadline_at"]):
                        reasons.append("cycle_deadline_drift")
                    events = list(con.execute("SELECT * FROM agent_worker_attempt_events WHERE subject_type='research' AND subject_id=?", (run["research_run_id"],)))
                    starts = [e for e in events if e["event_type"] == "started"]
                    finishes = [e for e in events if e["event_type"] == "finished"]
                    if len(starts) > manifest["contract"]["max_attempts"]:
                        reasons.append("attempt_limit_exceeded")
                    if any(e["status"] == "failed" for e in finishes):
                        reasons.append("failed_attempt")
                    if any(e["model"] != manifest["contract"]["model"] or e["request_sha256"] != run["request_sha256"] or not _time(row["registered_at"]) <= _time(e["occurred_at"]) < _time(slot["deadline_at"]) for e in events):
                        reasons.append("attempt_contract_or_causality_drift")
                    conflicts = con.execute("SELECT COUNT(*) FROM research_conflicts WHERE research_run_id=? AND status='unresolved'", (run["research_run_id"],)).fetchone()[0]
                    reservation = con.execute("SELECT * FROM agent_budget_reservations WHERE subject_id=?", (run["research_run_id"],)).fetchone()
                    if run["status"] == "imported":
                        if run["result_schema"] != manifest["contract"]["release"]["output_schema"]:
                            reasons.append("result_schema_drift")
                        if run["coverage_status"] not in {"complete", "partial"} or float(run["coverage_ratio"] or 0) < .9 or float(run["evidence_ratio"] or 0) < .8 or conflicts:
                            reasons.append("quality_thresholds_failed")
                        if not starts or {e["attempt_id"] for e in starts} != {e["attempt_id"] for e in finishes} or any(e["input_tokens"] is None or e["output_tokens"] is None for e in finishes) or not reservation or reservation["accounting_mode"] != "exact" or reservation["status"] != "settled" or reservation["actual_tokens"] is None:
                            reasons.append("attempt_or_usage_unproven")
                        elif reservation["actual_tokens"] > manifest["contract"]["budget"]["job_tokens"]:
                            reasons.append("budget_exceeded")
                        status = "failed" if reasons else "passed"
                    elif run["status"] in {"rejected", "failed"} or expired or reasons:
                        status = "failed"
                        reasons.append("run_" + run["status"])
                    else:
                        status = "pending"
                slots.append({**slot, "status": status, "reasons": reasons,
                              "research_run_id": run["research_run_id"] if run else None})
            state = "failed" if any(s["status"] == "failed" for s in slots) else "passed" if all(s["status"] == "passed" for s in slots) else "in_progress"
            cohorts.append({"cohort_id": row["cohort_id"], "manifest_sha256": row["manifest_sha256"],
                            "registered_at": row["registered_at"], "actor": row["actor"],
                            "status": state, "slots": slots})
    # Latest approved preregistration is authoritative, never the best passing cohort.
    active = cohorts[-1] if cohorts else None
    slots = active["slots"] if active else []
    return {"schema": "mova-research-acceptance-report-v1", "policy": POLICY,
            "status": active["status"] if active else "not_registered",
            "measured_gameweeks": sum(s["research_run_id"] is not None for s in slots),
            "passing_gameweeks": sum(s["status"] == "passed" for s in slots),
            "active": active, "cohorts": cohorts, "historical": historical}
