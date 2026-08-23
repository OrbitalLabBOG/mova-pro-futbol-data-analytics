"""Snapshots inmutables de las fuentes oficiales FPL."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data import live
from mova_fpl.data.sources import (
    FPL_BOOTSTRAP_URL,
    FPL_FIXTURES_URL,
    fetch_bootstrap,
    fetch_fixtures,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_sha() -> str:
    explicit = os.environ.get("MOVA_GIT_SHA")
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"snapshot inmutable ya existe: {path}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def load_snapshot(path: Path) -> tuple[dict, list, dict]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    boot_raw = (path / "bootstrap-static.json").read_bytes()
    fixtures_raw = (path / "fixtures.json").read_bytes()
    checks = {
        "bootstrap-static.json": (_sha(boot_raw), manifest.get("bootstrap_sha256")),
        "fixtures.json": (_sha(fixtures_raw), manifest.get("fixtures_sha256")),
    }
    bad = {name: {"actual": actual, "expected": expected}
           for name, (actual, expected) in checks.items() if actual != expected}
    if bad:
        raise ValueError(f"snapshot alterado o corrupto: {bad}")
    return json.loads(boot_raw), json.loads(fixtures_raw), manifest


def event_context(boot: dict, fixtures: list, target_gw: int) -> dict:
    """Explica si la jornada objetivo se proyecta sobre una GW ya asentada.

    FPL publica ``is_next`` antes de terminar la jornada en curso. Eso es útil
    para preparar la siguiente decisión, pero no convierte la información en
    definitiva. El contrato conserva ambas verdades para que una propuesta de
    chip no parezca madura mientras aún faltan partidos o el score no ha sido
    validado por FPL.
    """
    events = {int(event["id"]): event for event in boot.get("events", ())
              if event.get("id") is not None}
    target = events.get(int(target_gw)) or {}
    current = next((event for event in boot.get("events", ())
                    if event.get("is_current")), None)
    prior = events.get(int(target_gw) - 1)
    prior_fixtures = [fixture for fixture in fixtures
                      if fixture.get("event") == int(target_gw) - 1]
    unstarted = sum(not bool(fixture.get("started")) for fixture in prior_fixtures)
    unsettled = sum(not bool(fixture.get("finished")) for fixture in prior_fixtures)
    prior_settled = bool(prior and prior.get("finished") and prior.get("data_checked"))
    preliminary = bool(prior and not prior_settled)
    reasons = ["prior_gameweek_unsettled"] if preliminary else []
    if unstarted:
        reasons.append("prior_gameweek_has_unstarted_fixtures")
    return {
        "target_gw": int(target_gw),
        "target_is_next": bool(target.get("is_next")),
        "current_gw": int(current["id"]) if current else None,
        "prior_gw": int(prior["id"]) if prior else None,
        "prior_finished": bool(prior.get("finished")) if prior else None,
        "prior_data_checked": bool(prior.get("data_checked")) if prior else None,
        "prior_settled": prior_settled if prior else None,
        "prior_unstarted_fixtures": int(unstarted),
        "prior_unsettled_fixtures": int(unsettled),
        "preliminary": preliminary,
        "readiness_reasons": reasons,
    }


def validate(boot: dict, fixtures: list, season: str, gw: int) -> dict:
    event = next((e for e in boot.get("events", []) if int(e.get("id", -1)) == gw), None)
    if not event or not event.get("deadline_time"):
        raise ValueError(f"bootstrap sin deadline para GW{gw}")
    if len(boot.get("teams", [])) != 20:
        raise ValueError(f"se esperaban 20 clubes, llegaron {len(boot.get('teams', []))}")
    roster = live.roster(boot, fixtures, season, gw)
    partidos = [f for f in fixtures if f.get("event") == gw]
    if len(partidos) != 10:
        raise ValueError(f"se esperaban 10 partidos en GW{gw}, llegaron {len(partidos)}")
    required = ("element", "player_key", "name", "position", "team", "value",
                "opponent_team", "fixture", "disponibilidad")
    missing = {c: int(roster[c].isna().sum()) for c in required if roster[c].isna().any()}
    if missing:
        raise ValueError(f"roster con campos requeridos ausentes: {missing}")
    estados = Counter(str(x) for x in roster["estado"])
    return {
        "season": season,
        "gw": gw,
        "deadline_time": event["deadline_time"],
        "teams": int(roster["team"].nunique()),
        "players": int(len(roster)),
        "fixtures_gw": len(partidos),
        "fixtures_total": len(fixtures),
        "availability_lt_1": int((roster["disponibilidad"] < 1).sum()),
        "availability_eq_0": int((roster["disponibilidad"] == 0).sum()),
        "status_counts": dict(sorted(estados.items())),
        "event_context": event_context(boot, fixtures, gw),
    }


def capture_bytes(season: str, gw: int, out_root: Path, boot_raw: bytes,
                  fixtures_raw: bytes, *, captured_at: str | None = None) -> tuple[Path, dict]:
    captured = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    stamp = datetime.fromisoformat(captured.replace("Z", "+00:00")).strftime("%Y%m%dT%H%M%SZ")
    boot, fixtures = json.loads(boot_raw), json.loads(fixtures_raw)
    summary = validate(boot, fixtures, season, gw)
    dest = out_root / season / f"gw{gw:02d}" / stamp
    manifest = {
        "captured_at": captured,
        "source": "fantasy.premierleague.com/api (solo GET via data.sources)",
        "endpoints": [
            {"url": FPL_BOOTSTRAP_URL,
             "method": "GET", "http_status": 200, "parser": "snapshot-v1"},
            {"url": FPL_FIXTURES_URL,
             "method": "GET", "http_status": 200, "parser": "snapshot-v1"},
        ],
        "git_sha": _git_sha(),
        "bootstrap_sha256": _sha(boot_raw),
        "fixtures_sha256": _sha(fixtures_raw),
        **summary,
    }
    _write_new(dest / "bootstrap-static.json", boot_raw)
    _write_new(dest / "fixtures.json", fixtures_raw)
    _write_new(dest / "manifest.json", (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8"))
    return dest, manifest


def collect(season: str, gw: int, out_root: Path) -> tuple[Path, dict]:
    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return capture_bytes(
        season, gw, out_root, fetch_bootstrap(), fetch_fixtures(), captured_at=captured,
    )
