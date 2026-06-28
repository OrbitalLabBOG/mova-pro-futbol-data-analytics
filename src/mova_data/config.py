"""Configuración central del pipeline de datos MOVA Mundial 2026."""
from pathlib import Path

# ── Rutas ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "mundial.db"

# ── WhoScored: FIFA World Cup 2026 ─────────────────────────────────
# Descubierto 2026-06-28 desde la página del torneo.
WS_REGION_ID = 247          # International
WS_TOURNAMENT_ID = 36       # FIFA World Cup
WS_SEASON_ID = 10498        # 2026

# stage_id → nombre legible. Grupos A-L + Final Stage (eliminatorias).
WS_STAGES = {
    23753: "Group A", 23754: "Group B", 23755: "Group C", 23756: "Group D",
    23757: "Group E", 23758: "Group F", 23759: "Group G", 23760: "Group H",
    23761: "Group I", 23762: "Group J", 23763: "Group K", 23764: "Group L",
    23752: "Final Stage",  # R32 → Final
}

# Meses (YYYYMM) en los que se juega el torneo (11 jun – 19 jul 2026).
WS_MONTHS = ["202606", "202607"]

# Códigos de estado de partido en WhoScored.
WS_STATUS_FINISHED = {3, 6}   # 3 = FT (también ET/PK), 6 visto en otras comps
WS_STATUS_SCHEDULED = {0, 1}

# ── Scraping ───────────────────────────────────────────────────────
WS_DELAY_SECONDS = 6          # cortesía entre requests de partido
WS_TIMEOUT = 45
