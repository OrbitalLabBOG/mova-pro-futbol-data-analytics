"""Collector autónomo de calendario y eventos WhoScored."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.collector.contracts import (
    DataQualityError,
    SourceOutput,
    canonical_bytes,
    seal_manifest,
    sha256_bytes,
    write_atomic,
)

WHOSCORED_EPL_URL = (
    "https://www.whoscored.com/Regions/252/Tournaments/2/England-Premier-League"
)


def season_code(season: str) -> str:
    start, end = season.split("-", 1)
    if len(start) != 4 or len(end) != 2 or not (start + end).isdigit():
        raise ValueError(f"temporada inválida: {season}")
    return start[2:] + end


def schedule_file(config) -> Path:
    return config.collector_root / "cache" / "whoscored" / "schedules" / (
        f"ENG-Premier League_{season_code(config.season)}.json"
    )


def calendar_months(calendar: dict, season: str) -> list[str]:
    """Convierte la máscara WhoScored en meses YYYYMM y valida la temporada."""
    mask = calendar.get("mask")
    if not isinstance(mask, dict) or not mask:
        raise DataQualityError("wsCalendar no contiene una máscara mensual")
    start, end = season.split("-", 1)
    expected_years = {int(start), int(start[:2] + end)}
    months = []
    for year, zero_based_months in mask.items():
        try:
            numeric_year = int(year)
        except (TypeError, ValueError) as exc:
            raise DataQualityError(f"año WhoScored inválido: {year}") from exc
        if numeric_year not in expected_years or not isinstance(zero_based_months, (dict, list)):
            continue
        for month in zero_based_months:
            numeric_month = int(month) + 1
            if not 1 <= numeric_month <= 12:
                raise DataQualityError(f"mes WhoScored inválido: {month}")
            months.append(f"{numeric_year}{numeric_month:02d}")
    months = sorted(set(months))
    if not months:
        raise DataQualityError(
            f"wsCalendar no corresponde a la temporada configurada {season}"
        )
    return months


def normalize_schedule_rows(payloads: list[dict]) -> list[dict]:
    """Aplana las respuestas mensuales sin introducir una dependencia de pandas."""
    matches: dict[int, dict] = {}
    for payload in payloads:
        tournaments = payload.get("tournaments") if isinstance(payload, dict) else None
        if not isinstance(tournaments, list):
            raise DataQualityError("respuesta mensual WhoScored sin tournaments")
        for tournament in tournaments:
            for match in tournament.get("matches") or []:
                try:
                    match_id = int(match["id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise DataQualityError("partido WhoScored sin id válido") from exc
                row = dict(match)
                row.update({
                    "game_id": match_id,
                    "date": match.get("startTimeUtc"),
                    "home_team": match.get("homeTeamName"),
                    "away_team": match.get("awayTeamName"),
                })
                matches[match_id] = row
    return sorted(matches.values(), key=lambda row: (str(row.get("date")), row["game_id"]))


def discover_schedule(browser_path: Path, season: str, *, timeout_ms: int = 60000) -> list[dict]:
    """Descubre stage/calendario y consulta los meses con el browser real de Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright no está instalado en el collector") from exc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(browser_path),
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        try:
            page = browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/143.0.0.0 Safari/537.36"),
            )
            page.goto(WHOSCORED_EPL_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_function(
                "typeof wsCalendar !== 'undefined' && wsCalendar.stageId && wsCalendar.mask",
                timeout=timeout_ms,
            )
            calendar = page.evaluate("() => wsCalendar")
            stage_id = int(calendar.get("stageId") or 0)
            if not stage_id:
                raise DataQualityError("wsCalendar no contiene stageId")
            payloads = []
            for month in calendar_months(calendar, season):
                result = page.evaluate(
                    """async ({stageId, month}) => {
                      const response = await fetch(`/tournaments/${stageId}/data/?d=${month}`);
                      return {status: response.status, body: await response.text()};
                    }""",
                    {"stageId": stage_id, "month": month},
                )
                if int(result["status"]) != 200:
                    raise RuntimeError(
                        f"WhoScored calendario {stage_id}/{month}: HTTP {result['status']}"
                    )
                try:
                    payloads.append(json.loads(result["body"]))
                except json.JSONDecodeError as exc:
                    raise DataQualityError(
                        f"WhoScored calendario {stage_id}/{month} no devolvió JSON"
                    ) from exc
            return normalize_schedule_rows(payloads)
        finally:
            browser.close()


def read_schedule(config) -> list[dict]:
    path = schedule_file(config)
    if not path.is_file():
        raise FileNotFoundError(f"calendario WhoScored ausente: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise DataQualityError("calendario WhoScored no es una lista")
    return payload


def validate_schedule(rows: list[dict]) -> tuple[dict, list[dict]]:
    ids = []
    for row in rows:
        value = row.get("game_id") or row.get("game")
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            pass
    completed = sum(str(row.get("status")).upper() in {"6", "6.0", "FT"} for row in rows)
    quality = {"scheduled_matches": len(rows), "match_ids": len(ids),
               "unique_match_ids": len(set(ids)), "completed_matches": completed}
    checks = [
        {"name": "schedule_380", "passed": len(rows) == 380,
         "expected": {"count": 380}, "observed": {"count": len(rows)}},
        {"name": "schedule_ids_unique", "passed": len(ids) == len(set(ids)) == len(rows),
         "expected": {"unique": 380}, "observed": {"unique": len(set(ids))}},
    ]
    failed = [item["name"] for item in checks if not item["passed"]]
    if failed:
        raise DataQualityError(f"calendario WhoScored no cumple {failed}: {quality}")
    return quality, checks


def collect_schedule(config, store, run_id: str, *, now: datetime | None = None,
                     refresh: bool = True) -> SourceOutput:
    observed_at = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    path = schedule_file(config)
    started = time.monotonic()
    if refresh:
        rows = discover_schedule(config.collector_browser_path, config.season)
        write_atomic(path, canonical_bytes(rows))
    else:
        rows = read_schedule(config)
    quality, checks = validate_schedule(rows)
    payload = canonical_bytes(rows)
    payload_sha = sha256_bytes(payload)
    stamp = observed_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    directory = config.collector_root / "raw" / "whoscored-schedule" / config.season / stamp
    write_atomic(directory / "schedule.json", payload)
    manifest = {
        "schema": "mova-data-source-v1", "source": "whoscored_schedule",
        "season": config.season, "observed_at": observed_at,
        "method": "browser_read", "payload_sha256": payload_sha,
        "quality": quality, "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    _, manifest_sha = seal_manifest(directory, manifest)
    artifact_id, reused = store.register_artifact(
        run_id=run_id, source="whoscored_schedule", season=config.season,
        observed_at=observed_at, artifact_path=str(directory), payload_sha256=payload_sha,
        manifest_sha256=manifest_sha, byte_count=len(payload), row_count=len(rows),
        quality_status="valid", quality=quality,
    )
    store.record_checks(run_id, "whoscored_schedule", checks)
    loaded = {"scheduled_matches": 0} if reused else store.load_schedule(
        artifact_id, config.season, observed_at, rows
    )
    return SourceOutput(
        source="whoscored_schedule", status="completed", artifact_path=directory,
        payload_sha256=payload_sha, manifest_sha256=manifest_sha, quality=quality,
        metrics={"elapsed_seconds": round(time.monotonic() - started, 3),
                 "payload_unchanged": reused}, rows=loaded,
    )


def validate_match(data: dict, *, min_events: int = 1000,
                   max_events: int = 2500) -> dict:
    mcd = data.get("matchCentreData", data)
    if int(mcd.get("statusCode") or 0) != 6:
        raise DataQualityError(f"partido no finalizado: statusCode={mcd.get('statusCode')}")
    events = mcd.get("events")
    if not isinstance(events, list) or not min_events <= len(events) <= max_events:
        raise DataQualityError(
            f"eventos fuera de rango {min_events}..{max_events}: "
            f"{len(events) if isinstance(events, list) else 'missing'}"
        )
    if not (mcd.get("home") or {}).get("name") or not (mcd.get("away") or {}).get("name"):
        raise DataQualityError("partido sin equipos")
    keys = [(event.get("id"), event.get("eventId")) for event in events]
    if any(part is None for key in keys for part in key) or len(keys) != len(set(keys)):
        raise DataQualityError("IDs de eventos ausentes o (id,eventId) duplicados")
    return {
        "source_events": len(events),
        "typed_events": sum(bool((event.get("type") or {}).get("displayName"))
                            for event in events),
        "located_events": sum(event.get("x") is not None and event.get("y") is not None
                              for event in events),
        "duplicate_ws_event_ids": len(events) - len({event.get("id") for event in events}),
    }


def scrape_match(match_id: int, browser_path: Path, *, timeout_ms: int = 60000,
                 attempts: int = 2) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright no está instalado en el collector") from exc
    url = f"https://www.whoscored.com/Matches/{int(match_id)}/Live"
    last = None
    with sync_playwright() as playwright:
        for attempt in range(1, attempts + 1):
            browser = playwright.chromium.launch(
                headless=True, executable_path=str(browser_path),
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            try:
                page = browser.new_page(
                    viewport={"width": 1280, "height": 900},
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 Chrome/143.0.0.0 Safari/537.36"),
                )
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_function(
                    """typeof require !== 'undefined' && require.config &&
                    require.config.params && require.config.params['args'] &&
                    require.config.params['args'].matchCentreData""", timeout=timeout_ms,
                )
                data = page.evaluate(
                    """() => { const a=require.config.params['args']; return {
                    matchId:a.matchId,matchCentreData:a.matchCentreData,
                    matchCentreEventTypeJson:a.matchCentreEventTypeJson||null,
                    formationIdNameMappings:a.formationIdNameMappings||null}; }"""
                )
                data["matchId"] = data.get("matchId") or int(match_id)
                return data
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < attempts:
                    time.sleep(1)
            finally:
                browser.close()
    raise RuntimeError(f"WhoScored {match_id} falló tras {attempts} intentos: {last}")


def _completed_ids(rows: list[dict]) -> list[int]:
    out = []
    for row in rows:
        if str(row.get("status")).upper() not in {"6", "6.0", "FT"}:
            continue
        value = row.get("game_id") or row.get("game")
        if value is not None:
            out.append(int(value))
    return out


def collect_events(config, store, run_id: str, *, now: datetime | None = None) -> SourceOutput:
    observed_at = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    schedule = read_schedule(config)
    completed = _completed_ids(schedule)
    covered_before = store.covered_whoscored_ids(config.season)
    missing_before = [match_id for match_id in completed if match_id not in covered_before]
    selected = missing_before[:config.collector_event_batch_size]
    stamp = observed_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    audit_dir = config.collector_root / "raw" / "whoscored-events" / config.season / stamp
    audits = []
    failures = []
    inserted_events = 0
    started = time.monotonic()
    for match_id in selected:
        phase = time.monotonic()
        try:
            data = scrape_match(match_id, config.collector_browser_path)
            quality = validate_match(data)
            payload = canonical_bytes(data)
            payload_sha = sha256_bytes(payload)
            match_dir = audit_dir / str(match_id)
            write_atomic(match_dir / "match-centre.json", payload)
            manifest = {
                "schema": "mova-whoscored-match-v1", "source": "whoscored_events",
                "season": config.season, "ws_match_id": match_id,
                "observed_at": observed_at, "method": "browser_read",
                "payload_sha256": payload_sha, "bytes": len(payload), "quality": quality,
            }
            _, manifest_sha = seal_manifest(match_dir, manifest)
            artifact_id, reused = store.register_artifact(
                run_id=run_id, source="whoscored_events", season=config.season,
                observed_at=observed_at, artifact_path=str(match_dir),
                payload_sha256=payload_sha, manifest_sha256=manifest_sha,
                byte_count=len(payload), row_count=quality["source_events"],
                quality_status="valid", quality=quality,
            )
            loaded = {"events": 0} if reused else store.load_whoscored_match(
                artifact_id, config.season, observed_at, payload_sha, data, quality
            )
            inserted_events += loaded.get("events", 0)
            audits.append({"ws_match_id": match_id, "status": "completed", **quality,
                           "payload_unchanged": reused,
                           "elapsed_seconds": round(time.monotonic() - phase, 3)})
        except Exception as exc:  # noqa: BLE001 - cada partido queda aislado
            failures.append({"ws_match_id": match_id, "error_code": type(exc).__name__,
                             "error": str(exc)[:500],
                             "elapsed_seconds": round(time.monotonic() - phase, 3)})
    covered_after = covered_before | {item["ws_match_id"] for item in audits}
    missing_after = [match_id for match_id in completed if match_id not in covered_after]
    quality = {
        "completed_matches": len(completed), "covered_before": len(covered_before),
        "selected": len(selected), "collected": len(audits), "failed": len(failures),
        "covered_after": len(completed) - len(missing_after),
        "missing_after": len(missing_after), "coverage_ratio":
            round((len(completed) - len(missing_after)) / len(completed), 4)
            if completed else 1.0,
    }
    aggregate = {"schema": "mova-whoscored-batch-v1", "season": config.season,
                 "observed_at": observed_at, "selected_match_ids": selected,
                 "missing_match_ids": missing_after, "matches": audits,
                 "failures": failures, "quality": quality,
                 "elapsed_seconds": round(time.monotonic() - started, 3)}
    _, manifest_sha = seal_manifest(audit_dir, aggregate)
    payload_sha = sha256_bytes(canonical_bytes(aggregate))
    status = "degraded" if failures or missing_after else "completed"
    return SourceOutput(
        source="whoscored_events", status=status, artifact_path=audit_dir,
        payload_sha256=payload_sha, manifest_sha256=manifest_sha, quality=quality,
        metrics={"elapsed_seconds": round(time.monotonic() - started, 3),
                 "batch_limit": config.collector_event_batch_size},
        rows={"matches": len(audits), "events": inserted_events},
    )
