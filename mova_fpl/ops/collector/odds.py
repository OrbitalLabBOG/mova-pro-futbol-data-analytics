"""Adapter de resultados, estadísticas y odds de football-data.co.uk."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from mova_fpl.data.sources import fetch_football_data_odds, football_data_url
from mova_fpl.ops.collector.contracts import (
    DataQualityError,
    SourceOutput,
    seal_manifest,
    sha256_bytes,
    write_atomic,
)


REQUIRED = {"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}
ODDS_GROUPS = (("B365H", "B365D", "B365A"), ("AvgH", "AvgD", "AvgA"),
               ("B365CH", "B365CD", "B365CA"), ("AvgCH", "AvgCD", "AvgCA"))


def parse_csv(payload: bytes) -> tuple[list[dict], dict, list[dict]]:
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or ())
    if not REQUIRED <= headers:
        raise DataQualityError(f"football-data sin columnas: {sorted(REQUIRED - headers)}")
    rows = [dict(row) for row in reader if row.get("HomeTeam") and row.get("AwayTeam")]
    if len(rows) > 380:
        raise DataQualityError(f"football-data reportó {len(rows)} filas; máximo esperado 380")
    odds_rows = sum(any(all(row.get(key) for key in group) for group in ODDS_GROUPS)
                    for row in rows)
    quality = {"matches": len(rows), "columns": len(headers), "matches_with_odds": odds_rows,
               "coverage_ratio": round(odds_rows / len(rows), 4) if rows else 0.0}
    checks = [
        {"name": "row_count_plausible", "passed": 1 <= len(rows) <= 380,
         "expected": {"min": 1, "max": 380}, "observed": {"count": len(rows)}},
        {"name": "odds_present", "passed": odds_rows > 0,
         "expected": {"min": 1}, "observed": {"count": odds_rows}},
    ]
    failed = [item["name"] for item in checks if not item["passed"]]
    if failed:
        raise DataQualityError(f"odds payload no cumple {failed}: {quality}")
    return rows, quality, checks


def collect(config, store, run_id: str, *, now: datetime | None = None) -> SourceOutput:
    observed_at = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    payload = fetch_football_data_odds(config.season)
    rows, quality, checks = parse_csv(payload)
    payload_sha = sha256_bytes(payload)
    stamp = observed_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    directory = config.collector_root / "raw" / "odds" / config.season / stamp
    write_atomic(directory / "E0.csv", payload)
    manifest = {
        "schema": "mova-data-source-v1", "source": "football_data_odds",
        "season": config.season, "observed_at": observed_at, "method": "GET",
        "url": football_data_url(config.season), "payload_sha256": payload_sha,
        "bytes": len(payload), "quality": quality,
        "note": "football-data may expose opening and closing columns at different times",
    }
    _, manifest_sha = seal_manifest(directory, manifest)
    artifact_id, reused = store.register_artifact(
        run_id=run_id, source="football_data_odds", season=config.season,
        observed_at=observed_at, artifact_path=str(directory), payload_sha256=payload_sha,
        manifest_sha256=manifest_sha, byte_count=len(payload), row_count=len(rows),
        quality_status="valid", quality=quality,
    )
    store.record_checks(run_id, "football_data_odds", checks)
    loaded = {"matches": 0} if reused else store.load_odds(
        artifact_id, config.season, observed_at, rows
    )
    return SourceOutput(
        source="football_data_odds", status="completed", artifact_path=directory,
        payload_sha256=payload_sha, manifest_sha256=manifest_sha, quality=quality,
        metrics={"bytes": len(payload), "payload_unchanged": reused}, rows=loaded,
    )
