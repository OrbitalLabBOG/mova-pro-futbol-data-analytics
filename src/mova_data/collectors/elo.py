"""Elo de selecciones — eloratings.net/World.tsv (sin auth).

TSV de 31 columnas, sin cabecera, signo unicode '−'. Usamos col0=rank,
col2=ISO, col3=rating. El gap de Elo es el predictor #1 del modelo.
"""
from __future__ import annotations

import datetime as dt
import logging

import cloudscraper

logger = logging.getLogger("mova.elo")
URL = "https://www.eloratings.net/World.tsv"

# Código eloratings → nombre WhoScored (48 selecciones del Mundial 2026).
ISO_TO_TEAM = {
    "AR": "Argentina", "ES": "Spain", "FR": "France", "EN": "England",
    "BR": "Brazil", "PT": "Portugal", "NL": "Netherlands", "BE": "Belgium",
    "DE": "Germany", "HR": "Croatia", "CO": "Colombia", "MA": "Morocco",
    "US": "USA", "MX": "Mexico", "SN": "Senegal", "CH": "Switzerland",
    "JP": "Japan", "NO": "Norway", "EC": "Ecuador", "UY": "Uruguay",
    "KR": "South Korea", "AU": "Australia", "DZ": "Algeria", "EG": "Egypt",
    "CI": "Ivory Coast", "AT": "Austria", "SE": "Sweden", "TR": "Turkiye",
    "IR": "Iran", "PY": "Paraguay", "QA": "Qatar", "SA": "Saudi Arabia",
    "GH": "Ghana", "ZA": "South Africa", "PA": "Panama", "TN": "Tunisia",
    "SQ": "Scotland", "CA": "Canada", "CD": "DR Congo", "NZ": "New Zealand", "CV": "Cabo Verde",
    "UZ": "Uzbekistan", "JO": "Jordan", "IQ": "Iraq", "HT": "Haiti",
    "CZ": "Czechia", "BA": "Bosnia and Herzegovina", "CW": "Curacao",
}


def collect(conn) -> dict:
    r = cloudscraper.create_scraper().get(URL, timeout=30)
    r.raise_for_status()
    today = dt.date.today().isoformat()
    n = 0
    for line in r.text.strip().splitlines():
        c = line.split("\t")
        if len(c) < 4:
            continue
        try:
            rank, iso, rating = int(c[0]), c[2], int(c[3])
        except (ValueError, IndexError):
            continue
        conn.execute(
            """INSERT OR REPLACE INTO elo_ratings
               (source, snapshot_date, iso, team, rank, rating)
               VALUES ('eloratings', ?, ?, ?, ?, ?)""",
            (today, iso, ISO_TO_TEAM.get(iso), rank, rating),
        )
        n += 1
    conn.commit()
    mapped = conn.execute(
        "SELECT count(*) FROM elo_ratings WHERE snapshot_date=? AND team IS NOT NULL",
        (today,)).fetchone()[0]
    logger.info("Elo: %d selecciones (snapshot %s); %d/48 mapeadas a WC", n, today, mapped)
    return {"rows": n, "mapped_wc": mapped, "snapshot": today}
