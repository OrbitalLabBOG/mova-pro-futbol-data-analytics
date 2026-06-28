"""Blend modelo + mercado vía logarithmic opinion pool (media geométrica de probs)."""
from __future__ import annotations

import json

import numpy as np

from .config import BLEND_DIR, W_BLEND_DEFAULT

_W_PATH = BLEND_DIR / "weights.json"


def log_pool(p_model, p_market, w: float) -> np.ndarray:
    """p ∝ p_model^(1-w) · p_market^w, renormalizado. w = peso del mercado."""
    pm = np.clip(np.asarray(p_model, dtype=float), 1e-9, 1)
    pk = np.clip(np.asarray(p_market, dtype=float), 1e-9, 1)
    b = pm ** (1 - w) * pk ** w
    return b / b.sum()


def get_w() -> float:
    if _W_PATH.exists():
        return json.loads(_W_PATH.read_text()).get("w", W_BLEND_DEFAULT)
    return W_BLEND_DEFAULT


def save_w(w: float, extra: dict | None = None):
    BLEND_DIR.mkdir(parents=True, exist_ok=True)
    _W_PATH.write_text(json.dumps({"w": w, **(extra or {})}, indent=2))
