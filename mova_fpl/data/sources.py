"""Fuentes externas. SOLO GET (REQ-S-002).

v1 es estrictamente de lectura frente a servicios externos. No existe aqui
ninguna funcion que escriba en la API de FPL: un bug no puede gastar
transferencias ni hits reales.
"""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "fpl_seasons"

VAASTAV = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
FPL_API = "https://fantasy.premierleague.com/api"
FPL_BOOTSTRAP_URL = f"{FPL_API}/bootstrap-static/"
FPL_FIXTURES_URL = f"{FPL_API}/fixtures/"

USER_AGENT = "mova-fpl/0.1 (analytics; contacto: Orbital Lab)"
TIMEOUT = 100
RETRIES = 5


def _get(url: str, *, timeout: int = TIMEOUT, retries: int = RETRIES) -> bytes:
    """Unica primitiva de red del paquete. GET, nada mas."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise OSError(f"HTTP {resp.status}")
                return resp.read()
        except Exception as exc:                      # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(2 ** attempt * 0.5)
    raise OSError(f"fallo GET tras {retries} intentos: {url} ({last})")


def fetch_season_csv(season: str, dest_dir: Path = RAW) -> Path:
    """Descarga idempotente y atomica de merged_gw.csv de una temporada."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"merged_gw_{season}.csv"
    if out.exists() and out.stat().st_size > 0:
        return out
    payload = _get(f"{VAASTAV}/{season}/gws/merged_gw.csv")
    if b"total_points" not in payload.split(b"\n", 1)[0]:
        raise ValueError(f"cabecera inesperada para {season}: no parece merged_gw.csv")
    tmp = out.with_suffix(".csv.tmp")
    tmp.write_bytes(payload)
    tmp.replace(out)                                   # atomico: nunca deja un CSV a medias
    return out


def fetch_season_meta(season: str, name: str, dest_dir: Path = RAW) -> Path:
    """players_raw.csv, teams.csv, fixtures.csv, player_idlist.csv de una temporada."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{season}_{name}"
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(_get(f"{VAASTAV}/{season}/{name}"))
    tmp.replace(out)
    return out


def fetch_bootstrap(*, timeout: int = TIMEOUT, retries: int = RETRIES) -> bytes:
    """Estado de la temporada en curso desde la API oficial. Solo GET."""
    return _get(FPL_BOOTSTRAP_URL, timeout=timeout, retries=retries)


def fetch_fixtures() -> bytes:
    return _get(FPL_FIXTURES_URL)


# ------------------------------------------------------- estado de un equipo
# Los tres endpoints de abajo son PUBLICOS y de lectura: devuelven lo que
# cualquiera ve al abrir el perfil de un equipo en la web. No son la superficie
# de escritura de FPL —esa es `my-team` (autenticada) y `transfers` (POST)—, que
# este paquete no toca ni puede tocar: `_get` es la unica salida a red y declara
# method="GET". Ver tests/test_readonly_http.py.

def fetch_team(team_id: int) -> bytes:
    """Ficha publica de un equipo: nombre, valor, banco del ultimo deadline."""
    return _get(f"{FPL_API}/entry/{int(team_id)}/")


def fetch_team_history(team_id: int) -> bytes:
    """Historial por jornada y chips ya gastados."""
    return _get(f"{FPL_API}/entry/{int(team_id)}/history/")


def fetch_team_picks(team_id: int, gw: int) -> bytes:
    """Los quince de una jornada concreta, con banco y coste de transferencias."""
    return _get(f"{FPL_API}/entry/{int(team_id)}/event/{int(gw)}/picks/")
