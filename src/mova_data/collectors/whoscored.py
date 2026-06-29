"""Collector de WhoScored vía CloudScraper (sin browser).

Método validado 2026-06-28: CloudScraper burla Cloudflare en whoscored.com y el
match centre vive embebido en `require.config.params["args"]` dentro del HTML.
Cada partido del Mundial trae ~1.300-1.600 eventos con coordenadas (datos Opta).

Discovery: endpoint de fixtures por stage/mes
    https://www.whoscored.com/tournaments/{stage_id}/data/?d={YYYYMM}
Partido:
    https://www.whoscored.com/matches/{match_id}/live
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import cloudscraper

from ..config import (
    WS_DELAY_SECONDS, WS_MONTHS, WS_STAGES, WS_STATUS_FINISHED, WS_TIMEOUT,
)
from .base import BaseCollector

logger = logging.getLogger("mova.whoscored")

BASE = "https://www.whoscored.com"
ANCHOR = 'require.config.params["args"]'
_TOP_KEYS = ("matchId", "matchCentreData", "matchCentreEventTypeJson",
             "formationIdNameMappings")


def _extract_args_json(html: str) -> dict | None:
    """Extrae y parsea el objeto require.config.params["args"] del HTML.

    Usa brace-matching string-aware (no regex frágil) y luego entrecomilla solo
    las claves JS top-level no quoteadas.
    """
    i = html.find(ANCHOR)
    if i == -1:
        return None
    start = html.find("{", html.find("=", i))
    if start == -1:
        return None
    depth = end = 0
    in_str = esc = False
    end = None
    for j in range(start, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end is None:
        return None
    txt = html[start:end]
    txt = re.sub(r"([{,])\s*(" + "|".join(_TOP_KEYS) + r")\s*:", r'\1"\2":', txt)
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        logger.warning("JSON decode falló: %s", e)
        return None


class WhoScoredCollector(BaseCollector):
    source = "whoscored"

    def __init__(self, raw_dir: Path, delay: float = WS_DELAY_SECONDS):
        super().__init__(raw_dir)
        self.delay = delay
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        self.scraper.headers.update({
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    # ── Discovery ──────────────────────────────────────────────────
    def discover(self) -> list[dict]:
        """Recorre todos los stages × meses y devuelve los fixtures del torneo."""
        seen: dict[int, dict] = {}
        for stage_id, stage_name in WS_STAGES.items():
            for d in WS_MONTHS:
                for m in self._fixtures(stage_id, d):
                    mid = m.get("id")
                    if mid is None or mid in seen:
                        continue
                    status = m.get("status")
                    seen[mid] = {
                        "match_id": mid,
                        "stage_id": stage_id,
                        "stage_name": stage_name,
                        "status": status,
                        "is_finished": int(status in WS_STATUS_FINISHED),
                        "start_utc": m.get("startTimeUtc") or m.get("startTime"),
                        "home_team_id": m.get("homeTeamId"),
                        "home_team": m.get("homeTeamName"),
                        "away_team_id": m.get("awayTeamId"),
                        "away_team": m.get("awayTeamName"),
                        "home_score": m.get("homeScore"),
                        "away_score": m.get("awayScore"),
                        "match_is_opta": int(bool(m.get("matchIsOpta"))),
                    }
            time.sleep(1)
        fixtures = sorted(seen.values(), key=lambda x: (x["start_utc"] or ""))
        logger.info("Discovery: %d partidos (%d finalizados)",
                    len(fixtures), sum(f["is_finished"] for f in fixtures))
        return fixtures

    def fetch_live(self) -> list[dict]:
        """Partidos de eliminación EN VIVO (status 3) con marcador + minuto actual."""
        from ..config import WS_STAGES, WS_MONTHS, WS_STATUS_LIVE
        live = []
        for stage_id, name in WS_STAGES.items():
            if not name.startswith("Final"):
                continue
            for d in WS_MONTHS:
                for m in self._fixtures(stage_id, d):
                    if m.get("status") in WS_STATUS_LIVE:
                        el = (m.get("elapsed") or "").rstrip("'")
                        try:
                            minute = int(el)
                        except ValueError:
                            minute = 45
                        live.append({
                            "home": m.get("homeTeamName"), "away": m.get("awayTeamName"),
                            "home_score": m.get("homeScore"), "away_score": m.get("awayScore"),
                            "minute": minute, "elapsed": m.get("elapsed"),
                        })
        return live

    def _fixtures(self, stage_id: int, d: str) -> list[dict]:
        url = f"{BASE}/tournaments/{stage_id}/data/?d={d}"
        try:
            r = self.scraper.get(url, timeout=WS_TIMEOUT,
                                 headers={"X-Requested-With": "XMLHttpRequest",
                                          "Referer": f"{BASE}/"})
            if r.status_code != 200:
                return []
            j = r.json()
        except Exception as e:
            logger.warning("fixtures stage=%s d=%s falló: %s", stage_id, d, e)
            return []
        tours = j.get("tournaments") or []
        return tours[0].get("matches", []) if tours else []

    # ── Fetch ──────────────────────────────────────────────────────
    def fetch(self, match_id: int, force: bool = False) -> Path | None:
        out = self.raw_dir / f"{match_id}.json"
        if out.exists() and not force:
            return out
        url = f"{BASE}/matches/{match_id}/live"
        try:
            r = self.scraper.get(url, timeout=WS_TIMEOUT)
        except Exception as e:
            logger.warning("fetch %s error: %s", match_id, e)
            return None
        if r.status_code != 200:
            logger.warning("fetch %s status %s", match_id, r.status_code)
            return None
        data = _extract_args_json(r.text)
        if not data or not data.get("matchCentreData"):
            logger.warning("fetch %s: sin matchCentreData", match_id)
            return None
        out.write_text(json.dumps(data), encoding="utf-8")
        n = len(data["matchCentreData"].get("events", []))
        logger.info("fetch %s OK (%d eventos, %d KB)", match_id, n, out.stat().st_size // 1024)
        return out
