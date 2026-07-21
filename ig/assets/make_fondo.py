"""Generador de fondos serie IG (1080x1920) — v3 'olas vivas'.

Estilo: base oscura profunda + olas organicas en dos capas (tono medio + gradiente vivo)
ancladas en esquinas opuestas (arriba-derecha y abajo-izquierda), centro libre para contenido,
grano fotografico sutil.

Uso: python ig/assets/make_fondo.py [cap]   (1..6)
Salida: ig/assets/fondos/fondo_cap{N}.png
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

W, H = 1080, 1920
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ig" / "assets" / "fondos"
OUT.mkdir(parents=True, exist_ok=True)

# base, capa media (oscura), gradiente vivo (c1 -> c2)
CAPS = {
    1: dict(name="ciencia-datos", base=(4, 16, 12),  mid=(10, 92, 56),
            c1=(16, 200, 100), c2=(120, 255, 170)),                    # verde esmeralda vivo
    2: dict(name="matematicas",  base=(24, 8, 4),    mid=(140, 40, 16),
            c1=(255, 90, 40), c2=(255, 160, 60)),                      # naranja vivo
    3: dict(name="insights",     base=(22, 4, 16),   mid=(140, 16, 90),
            c1=(255, 45, 150), c2=(255, 130, 210)),                    # fucsia vivo
    4: dict(name="espana",       base=(24, 4, 6),    mid=(150, 20, 30),
            c1=(240, 40, 55), c2=(255, 170, 40)),                      # rojo→gualda
    5: dict(name="messi",        base=(6, 14, 24),   mid=(40, 90, 140),
            c1=(110, 190, 240), c2=(200, 235, 255)),                   # celeste albiceleste
    6: dict(name="tactica",      base=(12, 6, 26),   mid=(70, 30, 150),
            c1=(140, 70, 255), c2=(200, 150, 255)),                    # violeta electrico
}


def corner_blob(cx, cy, R, amp, freqs, seed):
    """Mascara booleana de blob organico anclado en (cx, cy): r(theta) suave."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = x - cx, y - cy
    d = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    rng = np.random.default_rng(seed)
    r = np.full_like(th, R)
    for k in freqs:
        r += amp * rng.uniform(.4, 1.0) * np.sin(k * th + rng.uniform(0, 2 * np.pi))
    return d < r


def lin_gradient(c1, c2, angle_deg=45):
    """Gradiente lineal RGB en toda la lamina."""
    ang = np.deg2rad(angle_deg)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    t = (x * np.cos(ang) + y * np.sin(ang))
    t = (t - t.min()) / (t.max() - t.min())
    g = np.zeros((H, W, 3), dtype=np.float32)
    for i in range(3):
        g[..., i] = c1[i] + (c2[i] - c1[i]) * t
    return g


def make(cap=1):
    cfg = CAPS[cap]
    arr = np.zeros((H, W, 3), dtype=np.float32)
    arr[:] = cfg["base"]

    grad = lin_gradient(cfg["c1"], cfg["c2"], 40)

    # ---- ola superior derecha (capa media detras + viva delante)
    m_mid = corner_blob(W + 140, -160, 880, 130, (2, 3, 5), seed=11)
    m_viv = corner_blob(W + 140, -160, 740, 120, (2, 3, 5), seed=23)
    # ---- ola inferior izquierda
    m_mid2 = corner_blob(-140, H + 160, 860, 130, (2, 3, 5), seed=31)
    m_viv2 = corner_blob(-140, H + 160, 700, 115, (2, 3, 5), seed=47)

    for m in (m_mid, m_mid2):
        arr[m] = cfg["mid"]
    for m in (m_viv, m_viv2):
        arr[m] = grad[m]

    # suavizar bordes de las olas apenas (anti-alias organico)
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(2.2))
    arr = np.array(img, dtype=np.float32)

    # glow sutil del color vivo hacia el centro (que la luz "sangre" de las olas)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    for (cx, cy, rad) in [(W - 120, 120, 1150), (120, H - 140, 1100)]:
        d = np.hypot(x - cx, y - cy) / rad
        glow = np.clip(1 - d, 0, 1) ** 2 * 0.10
        for i in range(3):
            arr[..., i] += glow * cfg["c1"][i]

    # grano
    rng = np.random.default_rng(7)
    arr += rng.normal(0, 5, (H, W, 1))

    out = OUT / f"fondo_cap{cap}.png"
    Image.fromarray(arr.clip(0, 255).astype(np.uint8)).save(out)
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    make(cap)
