"""Fuentes externas. SOLO GET (REQ-S-002).

v1 es estrictamente de lectura frente a servicios externos. No existe aqui
ninguna funcion que escriba en la API de FPL: un bug no puede gastar
transferencias ni hits reales.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "fpl_seasons"

VAASTAV = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
FPL_API = "https://fantasy.premierleague.com/api"
FPL_BOOTSTRAP_URL = f"{FPL_API}/bootstrap-static/"
FPL_FIXTURES_URL = f"{FPL_API}/fixtures/"
FPL_EVENT_LIVE_URL = f"{FPL_API}/event/{{gw}}/live/"
FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281"
THE_ODDS_API = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"

USER_AGENT = "mova-fpl/0.1 (analytics; contacto: Orbital Lab)"
TIMEOUT = 100
RETRIES = 5


def _get(url: str, *, timeout: int = TIMEOUT, retries: int = RETRIES,
         safe_url: str | None = None, include_headers: bool = False):
    """Unica primitiva de red del paquete. GET, nada mas."""
    last = "unknown error"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise OSError(f"HTTP {resp.status}")
                payload = resp.read()
                if include_headers:
                    return payload, {str(key).lower(): str(value)
                                     for key, value in resp.headers.items()}
                return payload
        except Exception as exc:                      # noqa: BLE001
            # Nunca interpolar ``exc``: HTTPError puede contener la URL completa
            # y The Odds API autentica con apiKey en query string.
            if isinstance(exc, urllib.error.HTTPError):
                last = f"HTTP {exc.code}"
            elif isinstance(exc, urllib.error.URLError):
                last = f"URLError/{type(exc.reason).__name__}"
            else:
                last = type(exc).__name__
            if attempt < retries:
                time.sleep(2 ** attempt * 0.5)
    raise OSError(f"fallo GET tras {retries} intentos: {safe_url or url} ({last})")


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


def fetch_event_live(gw: int) -> bytes:
    """Estadísticas oficiales por jugador de una jornada (solo GET)."""
    event = int(gw)
    if not 1 <= event <= 38:
        raise ValueError("gw debe estar entre 1 y 38")
    return _get(FPL_EVENT_LIVE_URL.format(gw=event))


def football_data_url(season: str) -> str:
    """URL canónica de Premier League para ``YYYY-YY``."""
    start, end = season.split("-", 1)
    if len(start) != 4 or len(end) != 2 or not (start + end).isdigit():
        raise ValueError(f"temporada inválida: {season}")
    return f"{FOOTBALL_DATA}/{start[2:]}{end}/E0.csv"


def fetch_football_data_odds(season: str) -> bytes:
    """Resultados y odds publicados por football-data.co.uk (solo GET)."""
    return _get(football_data_url(season), timeout=45, retries=3)


def fetch_market_odds(api_key: str, *, regions: str = "uk,eu",
                      markets: str = "h2h,totals") -> tuple[bytes, Mapping[str, str]]:
    """Odds pre-partido EPL desde The Odds API; la credencial nunca se registra."""
    query = urllib.parse.urlencode({
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    })
    return _get(
        f"{THE_ODDS_API}?{query}", timeout=45, retries=3,
        safe_url=THE_ODDS_API, include_headers=True,
    )


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
