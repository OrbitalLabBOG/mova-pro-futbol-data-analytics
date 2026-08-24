"""Adapter de la API oficial FPL, incluido el equipo público configurado."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data.sources import (
    FPL_BOOTSTRAP_URL,
    FPL_FIXTURES_URL,
    fetch_bootstrap,
    fetch_fixtures,
    fetch_team,
    fetch_team_history,
    fetch_team_picks,
)
from mova_fpl.ops.collector.contracts import (
    DataQualityError,
    SourceOutput,
    canonical_bytes,
    seal_manifest,
    sha256_bytes,
    write_atomic,
)


def validate_bundle(boot: dict, fixtures: list, entry: dict, history: dict,
                    team_id: int) -> tuple[dict, list[dict]]:
    observed = {
        "teams": len(boot.get("teams") or []),
        "events": len(boot.get("events") or []),
        "players": len(boot.get("elements") or []),
        "fixtures": len(fixtures),
        "entry_id": entry.get("id"),
        "history_events": len(history.get("current") or []),
    }
    checks = [
        {"name": "teams_20", "passed": observed["teams"] == 20,
         "expected": {"count": 20}, "observed": {"count": observed["teams"]}},
        {"name": "gameweeks_38", "passed": observed["events"] == 38,
         "expected": {"count": 38}, "observed": {"count": observed["events"]}},
        {"name": "players_plausible", "passed": 500 <= observed["players"] <= 800,
         "expected": {"min": 500, "max": 800},
         "observed": {"count": observed["players"]}},
        {"name": "fixtures_380", "passed": observed["fixtures"] == 380,
         "expected": {"count": 380}, "observed": {"count": observed["fixtures"]}},
        {"name": "entry_matches", "passed": observed["entry_id"] == team_id,
         "expected": {"entry_id": team_id},
         "observed": {"entry_id": observed["entry_id"]}},
    ]
    failed = [item["name"] for item in checks if not item["passed"]]
    if failed:
        raise DataQualityError(f"FPL bundle no cumple: {failed}; observed={observed}")
    return observed, checks


def collect(config, store, run_id: str, *, now: datetime | None = None) -> SourceOutput:
    observed_at = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    raw = {
        "bootstrap-static.json": fetch_bootstrap(),
        "fixtures.json": fetch_fixtures(),
        "entry.json": fetch_team(config.team_id),
        "entry-history.json": fetch_team_history(config.team_id),
    }
    boot = json.loads(raw["bootstrap-static.json"])
    fixtures = json.loads(raw["fixtures.json"])
    entry = json.loads(raw["entry.json"])
    history = json.loads(raw["entry-history.json"])
    current = list(history.get("current") or [])
    latest_gw = max((int(item.get("event") or 0) for item in current), default=0)
    picks = None
    if latest_gw:
        raw[f"picks-gw{latest_gw:02d}.json"] = fetch_team_picks(config.team_id, latest_gw)
        picks = json.loads(raw[f"picks-gw{latest_gw:02d}.json"])

    quality, checks = validate_bundle(boot, fixtures, entry, history, config.team_id)
    payload_sha = sha256_bytes(b"\n".join(raw[name] for name in sorted(raw)))
    stamp = observed_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    directory = config.collector_root / "raw" / "fpl" / config.season / stamp
    for name, payload in raw.items():
        write_atomic(directory / name, payload)
    manifest = {
        "schema": "mova-data-source-v1", "source": "fpl_official",
        "season": config.season, "observed_at": observed_at,
        "team_id": config.team_id, "method": "GET",
        "endpoints": [FPL_BOOTSTRAP_URL, FPL_FIXTURES_URL],
        "team_resources": ["public profile", "public history", "latest public picks"],
        "files": {name: {"bytes": len(payload), "sha256": sha256_bytes(payload)}
                  for name, payload in raw.items()},
        "payload_sha256": payload_sha, "quality": quality,
    }
    _, manifest_sha = seal_manifest(directory, manifest)
    artifact_id, reused = store.register_artifact(
        run_id=run_id, source="fpl_official", season=config.season,
        observed_at=observed_at, artifact_path=str(directory), payload_sha256=payload_sha,
        manifest_sha256=manifest_sha, byte_count=sum(map(len, raw.values())),
        row_count=quality["players"] + quality["fixtures"] + quality["history_events"],
        quality_status="valid", quality=quality,
    )
    store.record_checks(run_id, "fpl_official", checks)
    rows = ({"players": 0, "fixtures": 0, "history": 0, "picks": 0}
            if reused else store.load_fpl(
                artifact_id, config.season, observed_at, boot, fixtures, entry, history, picks
            ))
    return SourceOutput(
        source="fpl_official", status="completed", artifact_path=directory,
        payload_sha256=payload_sha, manifest_sha256=manifest_sha, quality=quality,
        metrics={"bytes": sum(map(len, raw.values())), "latest_public_picks_gw": latest_gw,
                 "payload_unchanged": reused}, rows=rows,
    )
