"""Constantes y rutas de la capa de modelo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models"
OUTPUTS_DIR = ROOT / "outputs"
XG_DIR = MODELS_DIR / "xg"
DC_DIR = MODELS_DIR / "dc"
BLEND_DIR = MODELS_DIR / "blend"

# ── Geometría de cancha (metros) ───────────────────────────────────
PITCH_L = 105.0
PITCH_W = 68.0
GOAL_W = 7.32

# ── xG ─────────────────────────────────────────────────────────────
PEN_XG = 0.79                 # penal = constante (Opta)

# ── Motor de partido / blend ───────────────────────────────────────
HOME_ADV_ELO = 100.0          # ventaja de local en puntos Elo (0 si neutral)
MAX_GOALS = 10                # tope de la matriz de marcadores Dixon-Coles
W_BLEND_DEFAULT = 0.80        # peso del mercado en el log-pool (calibrable)

# ── Monte Carlo ────────────────────────────────────────────────────
N_SIM = 100_000
SEED = 42
ET_STRENGTH = 1.0 / 3.0       # prórroga = ⅓ de un partido
PK_FAV = 0.56                 # prob. del favorito en penales (≈ no es 50/50)
