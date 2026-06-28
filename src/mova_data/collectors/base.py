"""Interfaz común de collectors — para enchufar nuevas fuentes sin tocar el resto.

Un collector hace dos cosas:
  - discover()      → lista de referencias de partido (dicts con al menos 'match_id')
  - fetch(match_id) → descarga el raw de un partido y lo cachea en disco; devuelve la ruta

El loader (separado) lee el raw cacheado y lo normaliza a SQLite. Así desacoplamos
descarga de parseo: re-parsear no re-descarga, y agregar una fuente = nuevo collector + loader.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseCollector(ABC):
    #: identificador de la fuente, se persiste en la columna `source`
    source: str = "base"

    def __init__(self, raw_dir: Path):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def discover(self) -> list[dict]:
        """Devuelve la lista de partidos disponibles (con metadata de fixture)."""

    @abstractmethod
    def fetch(self, match_id: int, force: bool = False) -> Path | None:
        """Descarga y cachea el raw de un partido. Idempotente salvo force=True."""

    def is_cached(self, match_id: int) -> bool:
        return (self.raw_dir / f"{match_id}.json").exists()
