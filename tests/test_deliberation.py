import hashlib
import json
from pathlib import Path

import pytest

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.deliberation import DecisionDeliberationService, normalize_result


def _request(*, blockers=()):
    body = {
        "schema": "mova-decision-deliberation-request-v1",
        "deliberation_id": "deliberation_" + "a" * 32,
        "cycle_id": "2026-27-gw03",
        "season": "2026-27",
        "gw": 3,
        "envelope_id": "envelope_" + "b" * 24,
        "manifest_id": "manifest_" + "c" * 32,
        "manifest_sha256": "d" * 64,
        "requested_at": "2026-09-04T15:00:00+00:00",
        "provider": "fixture",
        "envelope": {
            "candidates": [
                {"candidate_key": key, "decision": {"squad_15": list(range(1, 16))}}
                for key in ("do_nothing", "milp_baseline", "primary_alternative")
            ],
            "validation": {"blocking_codes": list(blockers)},
        },
        "cycle_context": {},
        "owned_player_elements": list(range(1, 16)),
        "allowed_player_elements": list(range(1, 20)),
        "guardrails": {"advisory_only": True},
    }
    return {**body, "request_sha256": sha256_json(body)}


def _result(request, *, verdict="accept", risks=None, intervention=None):
    keys = [row["candidate_key"] for row in request["envelope"]["candidates"]]
    return {
        "schema": "mova-decision-deliberation-v1",
        "deliberation_id": request["deliberation_id"],
        "cycle_id": request["cycle_id"],
        "envelope_id": request["envelope_id"],
        "request_sha256": request["request_sha256"],
        "generated_at": "2026-09-04T15:01:00+00:00",
        "strategist": {
            "summary": "Comparación conservadora de los tres escenarios.",
            "preferred_candidate_key": "do_nothing",
            "confidence": 0.7,
            "horizon_assessment": ["Conservar flexibilidad para la siguiente jornada."],
            "tradeoffs": [
                {"candidate_key": key, "advantages": ["Ventaja explícita"],
                 "disadvantages": ["Costo de oportunidad"]}
                for key in keys
            ],
            "intervention": intervention or {
                "gw": 3, "author": "strategist", "rationale": "",
                "xp_multiplier": {}, "allow_chips": [], "block_chips": [],
                "lock_in": [], "lock_out": [], "risk_lambda": None,
            },
        },
        "critic": {
            "verdict": verdict,
            "summary": "Los gates deterministas conservan precedencia.",
            "confidence": 0.9,
            "risks": risks or [],
            "challenged_assumptions": ["La ganancia esperada depende del horizonte."],
            "required_followups": ["Asentar la jornada previa."] if verdict == "block" else [],
        },
        "limitations": ["No se introdujeron hechos posteriores al manifest."],
        "usage": {"model": "fixture", "input_tokens": 10, "output_tokens": 20},
    }


def test_staged_envelope_accepts_advisory_deliberation_without_applying_intervention():
    request = _request()
    intervention = {
        "gw": 3, "author": "strategist", "rationale": "Duda ya sellada",
        "xp_multiplier": [{"player_element": 1, "factor": 0.8}],
        "allow_chips": [], "block_chips": [], "lock_in": [], "lock_out": [],
        "risk_lambda": None,
    }
    normalized = normalize_result(_result(request, intervention=intervention), request)

    assert normalized["status"] == "accepted"
    assert normalized["strategist"]["intervention"]["shadow_only"] is True
    assert normalized["strategist"]["intervention"]["applied"] is False
    assert normalized["strategist"]["intervention"]["xp_multiplier"] == {"1": 0.8}


def test_critic_must_preserve_every_deterministic_blocker():
    request = _request(blockers=("PRIOR_GAMEWEEK_SETTLED",))

    with pytest.raises(ValueError, match="omitió blockers"):
        normalize_result(_result(request, verdict="block"), request)


def test_blocked_envelope_requires_block_verdict_and_matching_risk():
    request = _request(blockers=("PRIOR_GAMEWEEK_SETTLED",))
    risk = {
        "code": "PRIOR_GAMEWEEK_SETTLED", "severity": "block",
        "candidate_key": None, "claim": "La GW previa no está asentada.",
        "mitigation": "Esperar finished y data_checked.",
    }
    normalized = normalize_result(_result(request, verdict="block", risks=[risk]), request)

    assert normalized["status"] == "blocked"
    assert normalized["critic"]["risks"][0]["severity"] == "block"


def test_intervention_cannot_reference_player_outside_sealed_context():
    request = _request()
    intervention = {
        "gw": 3, "author": "strategist", "rationale": "Jugador externo",
        "xp_multiplier": {"999": 0.0}, "allow_chips": [], "block_chips": [],
        "lock_in": [], "lock_out": [], "risk_lambda": None,
    }

    with pytest.raises(ValueError, match="fuera del contexto sellado"):
        normalize_result(_result(request, intervention=intervention), request)


def test_deliberation_request_receives_sealed_strategic_memory(tmp_path: Path):
    envelope_id = "envelope_" + "b" * 24
    manifest_id = "manifest_" + "c" * 32
    manifest_sha = "d" * 64
    content_sha = "e" * 64
    envelope = {
        "envelope_id": envelope_id,
        "content_sha256": content_sha,
        "manifest": {"content_sha256": manifest_sha},
        "candidates": [
            {"candidate_key": key, "decision": {"squad_15": list(range(1, 16))}}
            for key in ("do_nothing", "milp_baseline", "primary_alternative")
        ],
    }
    artifact = tmp_path / "envelope.json"
    artifact.write_text(json.dumps(envelope), encoding="utf-8")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    memory = {
        "schema": "mova-strategic-memory-v1",
        "status": "ready",
        "content_sha256": "f" * 64,
        "lessons": [{"lesson_id": "lesson_prior", "status": "validated"}],
    }

    class FakeDB:
        queued = None

        def migrate(self):
            return [14]

        def deliberation_source(self):
            return {
                "envelope_id": envelope_id, "content_sha256": content_sha,
                "manifest_sha256": manifest_sha, "artifact_path": str(artifact),
                "artifact_sha256": artifact_sha, "manifest_id": manifest_id,
                "cycle_id": "2026-27-gw03", "season": "2026-27", "gw": 3,
            }

        def decision_deliberation_for_envelope(self, _envelope_id):
            return None

        def latest_cycle_manifest(self, _cycle_id):
            return {
                "manifest_id": manifest_id, "phase": "preflight",
                "deadline_at": "2026-09-04T17:30:00+00:00",
                "analytics_manifest": {"status": "approved"},
                "research_summary": {"previous_active_signals": []},
                "memory_summary": memory,
            }

        def active_season_plan(self, _season):
            return {"plan_id": "plan_current", "revision": 2}

        def queue_decision_deliberation(self, payload):
            self.queued = payload
            return {"status": "queued", **payload}

    fake_db = FakeDB()
    config = RuntimeConfig(research_root=tmp_path / "research")
    queued = DecisionDeliberationService(config, fake_db).enqueue()
    request = json.loads(Path(queued["request_path"]).read_text(encoding="utf-8"))

    assert request["cycle_context"]["strategic_memory"] == memory
    assert request["cycle_context"]["season_plan"]["revision"] == 2
    assert request["guardrails"]["no_new_facts"] is True
    assert fake_db.queued["request_sha256"] == request["request_sha256"]


def test_deliberation_persistence_records_risks_intervention_and_cost(tmp_path: Path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        "2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight"
    )
    job_id, _ = db.start_job("tick", "tick:deliberation", "corr_deliberation",
                             cycle_id=cycle_id)
    envelope_id = "envelope_" + "b" * 24
    manifest_id = "manifest_" + "c" * 32
    decision_id = "decision_" + "e" * 24
    with db.transaction() as con:
        con.execute(
            """INSERT INTO cycle_manifests(
            manifest_id,cycle_id,revision,as_of_at,deadline_at,phase,team_state_id,plan_id,
            source_manifest_json,analytics_manifest_json,research_summary_json,artifact_path,
            content_sha256,created_at) VALUES(?,?,1,?,?,?,?,?,'[]','{}','{}',?,?,?)""",
            (manifest_id, cycle_id, "2026-09-04T15:00:00+00:00",
             "2026-09-04T17:30:00+00:00", "preflight", None, None,
             "manifest.json", "d" * 64, "2026-09-04T15:00:00+00:00"),
        )
        con.execute(
            """INSERT INTO decision_runs(
            decision_id,job_id,cycle_id,revision,mode,policy_version,status,expected_points,
            chip,fingerprint,manifest_sha256,artifact_path,created_at)
            VALUES(?,?,?,1,'shadow','fixture','staged',50,NULL,'fingerprint',?,?,?)""",
            (decision_id, job_id, cycle_id, "d" * 64, "envelope.json",
             "2026-09-04T15:00:00+00:00"),
        )
        con.execute(
            """INSERT INTO decision_envelopes(
            envelope_id,job_id,cycle_id,decision_id,manifest_id,schema_version,
            policy_version,status,selected_candidate_key,content_sha256,artifact_path,
            artifact_sha256,created_at)
            VALUES(?,?,?,?,?,'mova-decision-envelope-v1','fixture','staged',
            'milp_baseline',?,?,?,?)""",
            (envelope_id, job_id, cycle_id, decision_id, manifest_id, "f" * 64,
             "envelope.json", "a" * 64, "2026-09-04T15:00:00+00:00"),
        )
    request = _request()
    db.queue_decision_deliberation({
        "deliberation_id": request["deliberation_id"], "cycle_id": cycle_id,
        "envelope_id": envelope_id, "manifest_id": manifest_id, "provider": "fixture",
        "request_path": "request.json", "request_sha256": request["request_sha256"],
    })
    risk = {
        "code": "MODEL_HORIZON_RISK", "severity": "warning",
        "candidate_key": "milp_baseline", "claim": "Horizonte corto.",
        "mitigation": "Comparar seis jornadas.",
    }
    normalized = normalize_result(_result(request, verdict="revise", risks=[risk]), request)
    imported = db.import_decision_deliberation(
        request["deliberation_id"], normalized,
        result_path="result.json", result_sha256="9" * 64,
    )

    assert imported["status"] == "review_required"
    assert imported["intervention_applied"] is False
    with db.connect(readonly=True) as con:
        stored = con.execute(
            "SELECT intervention_json FROM decision_deliberations"
        ).fetchone()
        assert json.loads(stored["intervention_json"])["applied"] is False
        assert con.execute(
            "SELECT COUNT(*) FROM decision_deliberation_risks"
        ).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM intervention_runs").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM cost_ledger").fetchone()[0] == 1
