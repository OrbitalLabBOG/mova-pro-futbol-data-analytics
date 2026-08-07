"""Collector de la API de Fantasy Premier League (FPL API).

Descarga idempotente de:
  - bootstrap-static: jugadores, equipos, gameweeks
  - fixtures: calendario FPL con FDR
  - element-summary/{id}: historial por jugador
"""
import json
import time
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.mova_data.config import (
    FPL_BOOTSTRAP_URL,
    FPL_FIXTURES_URL,
    FPL_ELEMENT_SUMMARY_URL,
    RAW_DIR,
)
from src.mova_data.collectors.base import BaseCollector


class FPLCollector(BaseCollector):
    source: str = "fpl"

    def __init__(self, raw_dir: Optional[Path] = None):
        super().__init__(raw_dir or (RAW_DIR / "fpl"))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def discover(self) -> List[Dict[str, Any]]:
        """Descarga fixtures como lista de partidos FPL."""
        fixtures_path = self.fetch_fixtures()
        if fixtures_path and fixtures_path.exists():
            with open(fixtures_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def fetch(self, match_id: int, force: bool = False) -> Optional[Path]:
        """Fetch para FPL (no usado directamente por match_id)."""
        return None

    def fetch_bootstrap(self, force: bool = False) -> Path:
        """Descarga bootstrap-static (equipos, jugadores, gameweeks)."""
        out_path = self.raw_dir / "bootstrap_static.json"
        if out_path.exists() and not force:
            return out_path

        resp = self.session.get(FPL_BOOTSTRAP_URL, timeout=30)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return out_path

    def fetch_fixtures(self, force: bool = False) -> Path:
        """Descarga calendario de fixtures FPL."""
        out_path = self.raw_dir / "fixtures.json"
        if out_path.exists() and not force:
            return out_path

        resp = self.session.get(FPL_FIXTURES_URL, timeout=30)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return out_path

    def fetch_player_summary(self, player_id: int, force: bool = False) -> Path:
        """Descarga historial de un jugador por ID."""
        player_dir = self.raw_dir / "players"
        player_dir.mkdir(parents=True, exist_ok=True)
        out_path = player_dir / f"{player_id}.json"

        if out_path.exists() and not force:
            return out_path

        url = FPL_ELEMENT_SUMMARY_URL.format(player_id=player_id)
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        time.sleep(0.1) # cortesía API
        return out_path
