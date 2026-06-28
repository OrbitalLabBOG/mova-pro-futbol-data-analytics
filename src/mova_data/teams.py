"""Identidad canónica de equipos y resolver de aliases entre fuentes.

Canónico = nombre de WhoScored (backbone de event data). Resolución:
1) exacto por alias normalizado (lower, sin acentos/puntuación/espacios)
2) overrides explícitos para casos que la normalización no cubre.
"""
from __future__ import annotations

import unicodedata

# Aliases que la normalización NO resuelve (difieren en palabras, no en formato).
OVERRIDES = {
    "Cape Verde": "Cabo Verde",
    "Congo DR": "DR Congo",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "United States": "USA",
    "US": "USA",                 # código eloratings
    "USMNT": "USA",
    "Turkey": "Turkiye",         # nombre martj42
    "Czech Republic": "Czechia",  # nombre martj42
    "South Korea": "South Korea",
    "Korea Republic": "South Korea",
    "Ivory Coast": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
}

# Códigos ISO de eloratings → canónico (para resolver por código).
ISO = {
    "AR": "Argentina", "ES": "Spain", "FR": "France", "EN": "England",
    "BR": "Brazil", "PT": "Portugal", "NL": "Netherlands", "BE": "Belgium",
    "DE": "Germany", "HR": "Croatia", "CO": "Colombia", "MA": "Morocco",
    "US": "USA", "MX": "Mexico", "SN": "Senegal", "CH": "Switzerland",
    "JP": "Japan", "NO": "Norway", "EC": "Ecuador", "UY": "Uruguay",
    "KR": "South Korea", "AU": "Australia", "DZ": "Algeria", "EG": "Egypt",
    "CI": "Ivory Coast", "AT": "Austria", "SE": "Sweden", "TR": "Turkiye",
    "IR": "Iran", "PY": "Paraguay", "QA": "Qatar", "SA": "Saudi Arabia",
    "GH": "Ghana", "ZA": "South Africa", "PA": "Panama", "TN": "Tunisia",
    "SQ": "Scotland", "CA": "Canada", "CD": "DR Congo", "NZ": "New Zealand",
    "CV": "Cabo Verde", "UZ": "Uzbekistan", "JO": "Jordan", "IQ": "Iraq",
    "HT": "Haiti", "CZ": "Czechia", "BA": "Bosnia and Herzegovina", "CW": "Curacao",
}


def norm(s: str) -> str:
    """lower + sin acentos + solo alfanumérico."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def build_aliases(conn) -> dict:
    """Puebla team_aliases desde teams (WhoScored) + overrides + ISO. Idempotente."""
    canon = [r[0] for r in conn.execute("SELECT DISTINCT name FROM teams WHERE name IS NOT NULL")]
    rows: dict[str, tuple] = {}

    def add(alias, canonical, kind):
        rows[norm(alias)] = (norm(alias), alias, canonical, kind)

    for c in canon:                       # identidad
        add(c, c, "identity")
    for a, c in OVERRIDES.items():        # overrides explícitos
        add(a, c, "override")
    for iso, c in ISO.items():            # códigos ISO
        add(iso, c, "iso")

    conn.execute("DELETE FROM team_aliases")
    conn.executemany(
        "INSERT OR REPLACE INTO team_aliases (alias_norm, alias, canonical, kind) VALUES (?,?,?,?)",
        list(rows.values()),
    )
    conn.commit()
    return {"canonical": len(canon), "aliases": len(rows)}


def resolve(conn, name: str) -> str | None:
    """alias → canónico. Devuelve None si no se reconoce (para reportar)."""
    if not name:
        return None
    r = conn.execute("SELECT canonical FROM team_aliases WHERE alias_norm=?",
                     (norm(name),)).fetchone()
    return r[0] if r else None
