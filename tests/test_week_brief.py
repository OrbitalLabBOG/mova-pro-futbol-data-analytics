"""`mova week brief|acta`: nunca cae por datos faltantes y no crea ops.db."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mova_fpl.ops.cli import main
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.week_brief import SECTIONS, build_week_brief, derive_open_decisions, run_acta

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs/contracts/week-brief-v1.schema.json").read_text())
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
DEADLINE = "2026-11-27T18:30:00Z"


def validate(value, schema, root=SCHEMA, path="$"):
    """Validador mínimo del subconjunto JSON Schema usado por el contrato."""
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate(value, target, root, path)
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        checks = {"object": dict, "array": list, "string": str, "boolean": bool,
                  "null": type(None)}
        ok = any((t == "integer" and isinstance(value, int) and not isinstance(value, bool))
                 or (t in checks and isinstance(value, checks[t])) for t in allowed)
        assert ok, f"{path}: tipo {type(value).__name__} no es {allowed}"
    if "const" in schema:
        assert value == schema["const"], f"{path}: {value!r} != const"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: {value!r} fuera de enum"
    if "minimum" in schema:
        assert value >= schema["minimum"], path
    if "maximum" in schema:
        assert value <= schema["maximum"], path
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            assert key in value, f"{path}: falta {key}"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            assert not extra, f"{path}: propiedades extra {extra}"
        for key, item in value.items():
            if key in props:
                validate(item, props[key], root, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate(item, schema["items"], root, f"{path}[{index}]")


def _config(tmp_path: Path, **extra) -> RuntimeConfig:
    return RuntimeConfig(ops_db=tmp_path / "db" / "ops.db", artifact_root=tmp_path / "art",
                         analytics_root=tmp_path / "analytics",
                         canonical_db=tmp_path / "canonical.db",
                         postgres_credential_file=tmp_path / "no-secret", **extra)


def _picks(captain=5, vice=10):
    return [{"element": element, "position": element, "multiplier": 2 if element == captain
             else 1 if element <= 11 else 0, "is_captain": element == captain,
             "is_vice_captain": element == vice} for element in range(1, 16)]


def _boot():
    return {
        "teams": [{"id": 1, "short_name": "AAA"}],
        "events": [
            {"id": 11, "deadline_time": "2026-11-21T11:00:00Z", "finished": True,
             "data_checked": True, "is_current": True, "is_next": False},
            {"id": 12, "deadline_time": DEADLINE, "finished": False, "data_checked": False,
             "is_current": False, "is_next": True},
        ],
        "elements": [
            {"id": element, "web_name": f"P{element}", "team": 1,
             "element_type": 1 if element in (1, 12) else 2 if element < 5 else 3,
             "status": "i" if element == 7 else "s" if element == 13 else "a",
             "chance_of_playing_next_round": 0 if element in (7, 13) else None,
             "news": "Knee" if element == 7 else "", "now_cost": 55}
            for element in range(1, 21)
        ],
    }


class FakeFPL:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def bootstrap(self):
        self.calls.append("bootstrap")
        if self.fail:
            raise OSError("fallo GET tras 2 intentos")
        return _boot()

    def history(self, team_id):
        self.calls.append(("history", team_id))
        return {"chips": [{"name": "wildcard", "event": 3}]}

    def picks(self, team_id, gw):
        self.calls.append(("picks", team_id, gw))
        return {"picks": _picks(), "active_chip": None,
                "entry_history": {"bank": 14, "value": 1011}}


def _seed(config: RuntimeConfig) -> OpsDB:
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(config.season, 12, DEADLINE, phase="preparation")
    job_id, _ = db.start_job("team_state", "team_state:test", "corr_test", cycle_id=cycle_id)
    db.add_team_state(job_id=job_id, cycle_id=cycle_id, observed_at="2026-11-25T11:30:00+00:00",
                      source_name="fpl_private", squad=_picks(), free_transfers=2,
                      bank_tenths=14, chips=[{"name": "bboost", "status_for_entry": "available"}],
                      fingerprint="f" * 64, artifact_path=str(config.artifact_root / "ts"),
                      manifest_sha256="a" * 64)
    return db


def _candidates(path: Path, *, transfers=False, chip=None):
    decision = {"season": "2026-27", "gw": 12, "squad_15": list(range(1, 16)),
                "starters": list(range(1, 12)), "captain": 5, "vice_captain": 10,
                "bench_order": [12, 13, 14, 15], "transfers_in": [16] if transfers else [],
                "transfers_out": [13] if transfers else [], "hits": 0, "chip": chip,
                "expected_points": 61.2, "total_cost": 100.0, "bank_after": 1.4,
                "policy": "milp", "notes": [], "fingerprint": "d" * 64}
    payload = {"schema": "mova-live-decision-candidates-v1", "season": "2026-27", "gw": 12,
               "selected_candidate_key": "milp_baseline",
               "candidates": [
                   {"candidate_key": "do_nothing", "label": "x",
                    "decision": {**decision, "transfers_in": [], "transfers_out": []},
                    "violations": []},
                   {"candidate_key": "milp_baseline", "label": "MILP", "decision": decision,
                    "violations": []},
               ],
               "team_state": {"source": "public_api"}, "event_context": {}, "engine": {},
               "report_artifact": {"path": "acta.md", "sha256": "0" * 64}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _runner(*, transfers=False, chip=None, returncode=0, calls=None):
    def run(argv, *, env, cwd, timeout):
        if calls is not None:
            calls.append(argv)
        if returncode == 0:
            _candidates(Path(argv[argv.index("--json-out") + 1]), transfers=transfers, chip=chip)
        # stdout con progreso arbitrario: el wrapper nunca lo parsea
        return SimpleNamespace(returncode=returncode, stdout="[1/5] {no json",
                               stderr="Traceback: boom owner@example.com")
    return run


def test_db_inexistente_sin_red_ni_acta_es_empty_y_no_crea_nada(tmp_path):
    config = _config(tmp_path)
    brief = build_week_brief(config, OpsDB(config.ops_db), gw=12, now=NOW, network=False,
                             run_acta_flag=False)
    validate(brief, SCHEMA)
    assert brief["overall"] == "empty"
    assert brief["inputs"]["ops_db_present"] is False
    assert brief["sections"]["acta"]["status"] == "skipped"
    for name in ("cycle", "authority", "squad", "projections", "strategy_reasons",
                 "research_signals", "lessons", "execution"):
        assert brief["sections"][name]["needs_vps"] is True, name
        assert name in brief["missing_on_vps"]
    assert not (tmp_path / "db").exists() and not (tmp_path / "art").exists()


def test_cli_brief_sin_ops_db(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOVA_OPS_DB", str(tmp_path / "empty" / "ops.db"))
    assert main(["week", "brief", "--gw", "12", "--json", "--no-network", "--no-acta"]) == 0
    payload = json.loads(capsys.readouterr().out)
    validate(payload, SCHEMA)
    assert payload["overall"] == "empty"
    assert main(["week", "brief", "--gw", "12", "--no-network", "--no-acta"]) == 0
    assert "# MOVA · brief GW12" in capsys.readouterr().out
    assert not (tmp_path / "empty").exists()


def test_reconstruccion_publica_llena_ciclo_flags_y_plantilla(tmp_path):
    config = _config(tmp_path)
    fake = FakeFPL()
    brief = build_week_brief(config, None, gw=12, now=NOW, fetcher=fake, run_acta_flag=False)
    validate(brief, SCHEMA)
    s = brief["sections"]
    assert s["cycle"]["status"] == "ok" and s["cycle"]["data"]["preliminary"] is False
    assert s["squad"]["status"] == "degraded" and s["squad"]["source"] == "public_reconstruction"
    assert s["squad"]["data"]["picks_gw"] == 11 and s["squad"]["data"]["free_transfers"] == "unknown"
    assert ("picks", 3609854, 11) in fake.calls
    flagged = {item["element"] for item in s["flags"]["data"]["flagged"]}
    assert flagged == {7, 13}
    codes = {item["code"]: item["severity"] for item in s["open_decisions"]["data"]}
    assert codes["starter_flagged"] == "decide" and codes["bench_flagged"] == "info"
    assert "private_state_missing" in codes
    assert brief["overall"] == "partial"


def test_fallo_de_red_no_rompe_el_brief(tmp_path):
    brief = build_week_brief(_config(tmp_path), None, gw=12, now=NOW,
                             fetcher=FakeFPL(fail=True), run_acta_flag=False)
    validate(brief, SCHEMA)
    assert brief["inputs"]["network_error"].startswith("OSError")
    assert brief["sections"]["flags"]["status"] == "missing"


def test_db_sembrada_da_squad_privado_ok(tmp_path):
    config = _config(tmp_path)
    db = _seed(config)
    brief = build_week_brief(config, db, gw=12, now=NOW, fetcher=FakeFPL(),
                             run_acta_flag=False)
    validate(brief, SCHEMA)
    squad = brief["sections"]["squad"]
    assert squad["status"] == "ok" and squad["source"] == "private_team_state"
    assert squad["data"]["free_transfers"] == 2 and squad["data"]["chips_available"] == ["bboost"]
    assert squad["data"]["players"][4]["name"] == "P5"
    assert brief["sections"]["cycle"]["data"]["phase"] == "preparation"
    assert "squad" not in brief["missing_on_vps"]
    codes = {item["code"] for item in brief["sections"]["open_decisions"]["data"]}
    assert "private_state_missing" not in codes


def test_acta_con_runner_inyectado_parsea_solo_el_json(tmp_path):
    config = _config(tmp_path)
    calls = []
    brief = build_week_brief(config, None, gw=12, now=NOW, fetcher=FakeFPL(),
                             acta_runner=_runner(transfers=True, chip="bboost", calls=calls))
    validate(brief, SCHEMA)
    acta = brief["sections"]["acta"]
    assert acta["status"] == "ok"
    assert acta["data"]["selected"]["captain"] == 5
    assert [alt["candidate_key"] for alt in acta["data"]["alternatives"]] == [
        "do_nothing", "milp_baseline"]
    argv = calls[0]
    assert argv[1:3] == ["-m", "mova_fpl.cli.live"] and "--dry-run" in argv
    assert argv[argv.index("--team-id") + 1] == "3609854"
    assert Path(argv[argv.index("--out") + 1]).name == "acta.md"
    codes = {item["code"] for item in brief["sections"]["open_decisions"]["data"]}
    assert {"transfers_proposed", "chip_proposed"} <= codes
    # el candidato entrante también se revisa en flags
    assert brief["sections"]["flags"]["data"]["checked"] == 16


def test_acta_que_falla_no_rompe_el_brief_y_sanea_stderr(tmp_path):
    config = _config(tmp_path)
    brief = build_week_brief(config, None, gw=12, now=NOW, fetcher=FakeFPL(),
                             acta_runner=_runner(returncode=1))
    validate(brief, SCHEMA)
    acta = brief["sections"]["acta"]
    assert acta["status"] == "error"
    assert "example.com" not in acta["data"]["stderr_tail"]
    codes = {item["code"] for item in brief["sections"]["open_decisions"]["data"]}
    assert "acta_unavailable" in codes


def test_run_acta_sin_artefactos_reporta_lo_que_falta(tmp_path):
    payload = run_acta(_config(tmp_path), None, gw=12, now=NOW)
    assert payload["status"] == "missing" and payload["needs_vps"] is True
    assert any(path.endswith("canonical.db") for path in payload["missing"])
    assert any(path.endswith("points-1.1.0.joblib") for path in payload["missing"])
    assert payload["trace_written"] is False


def test_open_decisions_es_determinista_y_marca_preliminar(tmp_path):
    boot = _boot()
    boot["events"][0]["data_checked"] = False

    class Preliminary(FakeFPL):
        def bootstrap(self):
            return boot

    brief = build_week_brief(_config(tmp_path), None, gw=12, now=NOW, fetcher=Preliminary(),
                             run_acta_flag=False)
    first = derive_open_decisions(brief["sections"], gw=12)
    assert first == derive_open_decisions(brief["sections"], gw=12)
    assert first[0]["code"] == "preliminary_gw" and first[0]["severity"] == "blocker"
    assert set(brief["sections"]) == set(SECTIONS)


def test_margen_estrecho_de_capitan(tmp_path):
    sections = {name: {"status": "missing", "data": None} for name in SECTIONS}
    sections["acta"] = {"status": "ok", "data": {"selected": {
        "captain": 5, "vice_captain": 10, "starters": [], "transfers_in": []}}}
    sections["projections"] = {"status": "ok", "data": {"player_xp": {"5": 6.1, "10": 5.9}}}
    codes = [item["code"] for item in derive_open_decisions(sections, gw=12)]
    assert "captain_margin_tight" in codes


@pytest.mark.parametrize("gw", [0, 39])
def test_gw_fuera_de_rango(tmp_path, gw):
    with pytest.raises(ValueError):
        build_week_brief(_config(tmp_path), None, gw=gw, network=False, run_acta_flag=False)


# --- ADR-022 iter1: procedencia, snapshot explícito, timeout, research ------------------

def _sealed_state(config: RuntimeConfig, *, observed="2026-11-25T11:58:00Z", gw=12,
                  label=None):
    from mova_fpl.data.private_state import seal

    kinds = [1, 1] + [2] * 5 + [3] * 5 + [4] * 3
    payload = {
        "schema": "mova-fpl-private-team-state-v1", "observed_at": observed,
        "team_id": config.team_id, "event": {"id": gw, "deadline_time": DEADLINE},
        "picks_last_updated": None,
        "picks": [{"element": i, "element_type": k, "position": i,
                   "multiplier": 2 if i == 5 else 1 if i <= 11 else 0,
                   "is_captain": i == 5, "is_vice_captain": i == 10,
                   "purchase_price": 55, "selling_price": 55}
                  for i, k in enumerate(kinds, start=1)],
        "transfers": {"bank": 14, "value": 1000, "limit": 1, "made": 0, "cost": 0,
                      "status": ""},
        "chips": [],
    }
    path, _, _ = seal(payload, config.season, config.artifact_root / "team_state",
                      expected_team_id=config.team_id, source_label=label)
    return path


def test_acta_sin_estado_privado_lo_dice_claro(tmp_path):
    config = _config(tmp_path, team_id=424242)
    payload = run_acta(config, None, gw=12, now=NOW, runner=_runner())
    assert payload["status"] == "ok"
    assert payload["state_source"] == "public_reconstruction" and payload["state_age_h"] is None
    assert "sin estado privado" in payload["state_note"]
    assert payload["private_team_state"] is None


def test_snapshot_importado_explicito_no_pasa_por_la_cadencia(tmp_path):
    """Un import de hace 20 min se usa aunque la cadencia (5 min cerca del deadline) lo rechace."""
    config = _config(tmp_path, team_id=424242)
    db = _seed(config)  # ciclo GW12 con deadline en 2 días... forzamos cerca del deadline:
    near = datetime(2026, 11, 27, 18, 20, tzinfo=timezone.utc)  # 10 min antes
    path = _sealed_state(config, observed="2026-11-27T18:00:00Z", label="operator_import")
    calls = []
    # por la vía normal (sin ruta explícita) el snapshot de 20 min no cuenta
    implicit = run_acta(config, db, gw=12, now=near, runner=_runner(calls=calls))
    assert implicit["state_source"] == "public_reconstruction"
    assert "--private-team-state" not in calls[0]
    # con la ruta explícita sí se usa, y se reporta como import con su edad
    explicit = run_acta(config, db, gw=12, now=near, runner=_runner(calls=calls),
                        private_state_path=str(path))
    argv = calls[1]
    assert argv[argv.index("--private-team-state") + 1] == str(path)
    assert explicit["state_source"] == "import" and explicit["state_age_h"] == 0.33
    assert explicit["state_stale"] is False


def test_captura_se_reporta_como_capture(tmp_path):
    config = _config(tmp_path, team_id=424242)
    path = _sealed_state(config)
    payload = run_acta(config, None, gw=12, now=NOW, runner=_runner(),
                       private_state_path=str(path))
    assert payload["state_source"] == "capture" and payload["state_age_h"] == 0.03


def test_snapshot_explicito_de_otra_gw_es_error(tmp_path):
    config = _config(tmp_path, team_id=424242)
    path = _sealed_state(config, gw=11)
    payload = run_acta(config, None, gw=12, now=NOW, runner=_runner(),
                       private_state_path=str(path))
    assert payload["status"] == "error" and "GW11" in payload["detail"]


def test_require_private_state_falla_sin_estado_o_vencido(tmp_path):
    config = _config(tmp_path, team_id=424242)
    calls = []
    payload = run_acta(config, None, gw=12, now=NOW, runner=_runner(calls=calls),
                       require_private_state=True)
    assert payload["status"] == "error" and not calls
    old = _sealed_state(config, observed="2026-11-20T00:00:00Z")
    payload = run_acta(config, None, gw=12, now=NOW, runner=_runner(calls=calls),
                       private_state_path=str(old), require_private_state=True)
    assert payload["status"] == "error" and payload["state_stale"] is True and not calls


def test_brief_reporta_state_source_y_pasa_interventions(tmp_path):
    config = _config(tmp_path, team_id=424242)
    path = _sealed_state(config)
    calls = []
    document = {"gw": 12, "source": "agent:noticias", "rationale": "rueda de prensa",
                "adjustments": [{"element": 7, "p_play": 0.0}]}
    brief = build_week_brief(config, None, gw=12, now=NOW, fetcher=FakeFPL(),
                             acta_runner=_runner(calls=calls),
                             acta_options={"private_state_path": str(path),
                                           "interventions": document})
    assert brief["state"]["state_source"] == "capture"
    argv = calls[0]
    iv_path = Path(argv[argv.index("--interventions") + 1])
    assert json.loads(iv_path.read_text())["adjustments"][0]["element"] == 7


def test_timeout_kills_process_group(tmp_path):
    """El runner por defecto mata hijo Y nietos (cbc) al vencer, sin colgar la suite."""
    import subprocess
    import sys
    import time

    from mova_fpl.ops.week_brief import _default_runner

    pidfile = tmp_path / "grandchild.pid"
    child = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"open({str(pidfile)!r},'w').write(str(p.pid));time.sleep(60)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _default_runner([sys.executable, "-c", child], env=dict(__import__("os").environ),
                        cwd=tmp_path, timeout=2)
    assert time.monotonic() - started < 15
    pid = int(pidfile.read_text())
    import os
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:  # pragma: no cover
        os.kill(pid, 9)
        pytest.fail("el nieto sobrevivió al timeout")


def test_default_timeout_is_600():
    from mova_fpl.ops.week_brief import ACTA_TIMEOUT_SECONDS
    assert ACTA_TIMEOUT_SECONDS == 600


def test_cli_acta_acepta_flags_nuevos():
    from mova_fpl.ops.cli import parser

    args = parser().parse_args(["week", "acta", "--gw", "12", "--timeout", "30",
                                "--private-state-path", "/x", "--interventions", "/y",
                                "--intervention-from-notes", "--require-private-state"])
    assert args.timeout == 30 and args.require_private_state and args.intervention_from_notes


def test_brief_private_state_path_feeds_squad_and_keeps_zero_age(tmp_path):
    config = _config(tmp_path, team_id=424242)
    path = _sealed_state(config, observed="2026-11-25T12:00:00Z", label="operator_import")
    brief = build_week_brief(config, None, gw=12, now=NOW, fetcher=FakeFPL(),
                             acta_runner=_runner(),
                             acta_options={"private_state_path": str(path)})
    squad = brief["sections"]["squad"]
    assert squad["status"] == "ok" and squad["data"]["state_source"] == "import"
    assert squad["data"]["state_age_h"] == 0.0
    assert brief["sections"]["acta"]["data"]["state_age_h"] == 0.0
    assert brief["state"] == {"state_source": "import", "state_age_h": 0.0, "used_by": "acta"}
