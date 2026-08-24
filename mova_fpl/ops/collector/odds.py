"""Adapter de cuotas pre-partido EPL de The Odds API."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from mova_fpl.data.sources import THE_ODDS_API, fetch_market_odds
from mova_fpl.ops.collector.contracts import (
    DataQualityError,
    SourceOutput,
    canonical_bytes,
    seal_manifest,
    sha256_bytes,
    write_atomic,
)

SOURCE = "market_odds"
PROVIDER = "the_odds_api"
EXPECTED_MARKETS = {"h2h", "totals"}


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _observation_key(row: dict) -> str:
    identity = {
        "event": row["provider_event_id"], "bookmaker": row["bookmaker_key"],
        "market": row["market_key"], "outcome": row["outcome_name"],
        "description": row.get("outcome_description"), "point": row.get("point"),
    }
    return hashlib.sha256(canonical_bytes(identity)).hexdigest()


def parse_payload(payload: bytes, headers: dict[str, str] | None = None
                  ) -> tuple[list[dict], dict, list[dict]]:
    """Valida y aplana eventos/casas/mercados sin perder líneas individuales."""
    try:
        events = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataQualityError("The Odds API no devolvió JSON válido") from exc
    if not isinstance(events, list):
        raise DataQualityError("The Odds API devolvió un objeto de error, no eventos")

    rows: list[dict] = []
    event_markets: dict[str, set[str]] = {}
    bookmakers: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or not all(event.get(key) for key in (
            "id", "commence_time", "home_team", "away_team"
        )):
            raise DataQualityError("evento de odds incompleto")
        event_id = str(event["id"])
        event_markets[event_id] = set()
        for bookmaker in event.get("bookmakers") or []:
            bookmaker_key = str(bookmaker.get("key") or "")
            if not bookmaker_key:
                raise DataQualityError("bookmaker sin key")
            bookmakers.add(bookmaker_key)
            for market in bookmaker.get("markets") or []:
                market_key = str(market.get("key") or "")
                if market_key not in EXPECTED_MARKETS:
                    continue
                event_markets[event_id].add(market_key)
                for outcome in market.get("outcomes") or []:
                    try:
                        price = float(outcome["price"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise DataQualityError("selección de odds sin precio decimal") from exc
                    if price <= 1.0:
                        raise DataQualityError(f"precio decimal fuera de rango: {price}")
                    row = {
                        "provider_event_id": event_id,
                        "sport_key": str(event.get("sport_key") or "soccer_epl"),
                        "commence_time": event["commence_time"],
                        "home_team": event["home_team"], "away_team": event["away_team"],
                        "bookmaker_key": bookmaker_key,
                        "bookmaker_title": str(bookmaker.get("title") or bookmaker_key),
                        "bookmaker_last_update": bookmaker.get("last_update"),
                        "market_key": market_key,
                        "market_last_update": market.get("last_update"),
                        "outcome_name": str(outcome.get("name") or ""),
                        "outcome_description": outcome.get("description"),
                        "price": price, "point": outcome.get("point"),
                    }
                    if not row["outcome_name"]:
                        raise DataQualityError("selección de odds sin nombre")
                    row["observation_key"] = _observation_key(row)
                    rows.append(row)

    header_map = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    quota = {
        "used": _integer(header_map.get("x-requests-used")),
        "remaining": _integer(header_map.get("x-requests-remaining")),
        "last_cost": _integer(header_map.get("x-requests-last")),
    }
    event_count = len(events)
    h2h_events = sum("h2h" in markets for markets in event_markets.values())
    totals_events = sum("totals" in markets for markets in event_markets.values())
    quality = {
        "provider": PROVIDER, "events": event_count, "bookmakers": len(bookmakers),
        "market_rows": len(rows), "h2h_events": h2h_events,
        "totals_events": totals_events,
        "h2h_coverage_ratio": round(h2h_events / event_count, 4) if event_count else 0.0,
        "totals_coverage_ratio": round(totals_events / event_count, 4) if event_count else 0.0,
        "quota": quota,
    }
    checks = [
        {"name": "event_count_plausible", "passed": 1 <= event_count <= 380,
         "expected": {"min": 1, "max": 380}, "observed": {"count": event_count}},
        {"name": "bookmaker_depth", "passed": len(bookmakers) >= 5,
         "expected": {"min": 5}, "observed": {"count": len(bookmakers)}},
        {"name": "h2h_complete", "passed": h2h_events == event_count and event_count > 0,
         "expected": {"coverage": 1.0},
         "observed": {"coverage": quality["h2h_coverage_ratio"]}},
        {"name": "totals_present", "passed": totals_events > 0,
         "expected": {"min_events": 1}, "observed": {"events": totals_events}},
        {"name": "quota_observable", "passed": all(value is not None for value in quota.values()),
         "expected": {"headers": 3}, "observed": quota},
    ]
    failed = [item["name"] for item in checks if not item["passed"]]
    if failed:
        raise DataQualityError(f"The Odds API no cumple {failed}: {quality}")
    return rows, quality, checks


def _credential(config) -> str:
    try:
        key = config.odds_api_credential_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("no se pudo leer el secreto The Odds API") from exc
    if len(key) < 16:
        raise RuntimeError("el secreto The Odds API es inválido")
    return key


def collect(config, store, run_id: str, *, now: datetime | None = None) -> SourceOutput:
    observed_at = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    payload, headers = fetch_market_odds(
        _credential(config), regions=config.odds_api_regions, markets=config.odds_api_markets
    )
    rows, quality, checks = parse_payload(payload, dict(headers))
    payload_sha = sha256_bytes(payload)
    stamp = observed_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    directory = config.collector_root / "raw" / "odds" / config.season / stamp
    write_atomic(directory / "odds.json", payload)
    manifest = {
        "schema": "mova-data-source-v1", "source": SOURCE, "provider": PROVIDER,
        "season": config.season, "observed_at": observed_at, "method": "GET",
        "url": THE_ODDS_API, "sport": "soccer_epl",
        "regions": config.odds_api_regions.split(","),
        "markets": config.odds_api_markets.split(","),
        "payload_sha256": payload_sha, "bytes": len(payload), "quality": quality,
        "quota": quality["quota"],
        "note": "snapshot pre-match; one row per bookmaker/market/outcome/line",
    }
    _, manifest_sha = seal_manifest(directory, manifest)
    artifact_id, reused = store.register_artifact(
        run_id=run_id, source=SOURCE, season=config.season,
        observed_at=observed_at, artifact_path=str(directory), payload_sha256=payload_sha,
        manifest_sha256=manifest_sha, byte_count=len(payload), row_count=len(rows),
        quality_status="valid", quality=quality,
    )
    store.record_checks(run_id, SOURCE, checks)
    loaded = {"events": 0, "market_rows": 0} if reused else store.load_market_odds(
        artifact_id, config.season, observed_at, rows
    )
    return SourceOutput(
        source=SOURCE, status="completed", artifact_path=directory,
        payload_sha256=payload_sha, manifest_sha256=manifest_sha, quality=quality,
        metrics={"bytes": len(payload), "payload_unchanged": reused,
                 "quota_used": quality["quota"]["used"],
                 "quota_remaining": quality["quota"]["remaining"],
                 "request_cost": quality["quota"]["last_cost"]},
        rows=loaded,
    )
