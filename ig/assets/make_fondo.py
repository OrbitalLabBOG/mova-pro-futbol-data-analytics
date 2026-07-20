"""Generador del fondo-plantilla de la serie IG (1080x1920).

Sistema: dark constante + grid de puntos (tracking) + grano + glow del color del capítulo.
Zonas de silencio: ~25% superior y ~15% inferior con el grid desvanecido (ahí va el texto IG).

Uso: python ig/assets/make_fondo.py [cap]   (cap: 1..6, default 1)
Salida: ig/assets/fondos/fondo_cap{N}.png
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ig" / "assets" / "fondos"
OUT.mkdir(parents=True, exist_ok=True)

CAPS = {
    1: dict(accent=(0, 212, 163), name="ciencia-datos"),      # teal radar
    2: dict(accent=(255, 92, 57), name="matematicas"),        # naranja
    3: dict(accent=(255, 209, 102), name="insights"),         # dorado
    4: dict(accent=(228, 53, 63), name="espana"),             # rojo
    5: dict(accent=(124, 192, 232), name="messi"),            # celeste
    6: dict(accent=(46, 139, 87), name="tactica"),            # verde pizarra
}

BASE = (10, 10, 12)
DOT = (58, 66, 82)


def radial_glow(size, center, radius, color, peak):
    """Capa RGBA con glow radial suave."""
    y, x = np.ogrid[:size[1], :size[0]]
    d = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2) / radius
    alpha = np.clip(1 - d, 0, 1) ** 2.2 * peak
    layer = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    layer[..., 0], layer[..., 1], layer[..., 2] = color
    layer[..., 3] = (alpha * 255).astype(np.uint8)
    return Image.fromarray(layer, "RGBA")


def make(cap=1):
    accent = CAPS[cap]["accent"]

    # base con gradiente vertical sutil (centro apenas mas claro)
    yy = np.linspace(0, 1, H)[:, None]
    lift = (1 - np.abs(yy - 0.52) * 2.1).clip(0, 1) * 9     # +5 niveles max en el centro
    base = np.zeros((H, W, 3), dtype=np.float32)
    for i, c in enumerate(BASE):
        base[..., i] = c + lift
    img = Image.fromarray(base.astype(np.uint8), "RGB").convert("RGBA")

    # grid de puntos con mascara vertical (se desvanece en zonas de silencio)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(grid)
    step, r = 44, 1.3
    for gy in range(step // 2, H, step):
        # opacidad por fila: plena en el centro, tenue arriba (texto IG) y abajo
        t = gy / H
        if t < 0.24: fade = 0.25 + 0.75 * (t / 0.24) ** 1.5
        elif t > 0.86: fade = 0.25 + 0.75 * ((1 - t) / 0.14) ** 1.5
        else: fade = 1.0
        a = int(255 * fade)
        for gx in range(step // 2, W, step):
            d.ellipse([gx - r, gy - r, gx + r, gy + r], fill=(*DOT, a))
    img.alpha_composite(grid)

    # glow del capitulo: uno principal abajo-centro + un eco arriba-izquierda, muy sutiles
    img.alpha_composite(radial_glow((W, H), (540, 1520), 760, accent, peak=0.17))
    img.alpha_composite(radial_glow((W, H), (140, 260), 480, accent, peak=0.08))

    # linea de horizonte tenue del acento (ancla visual, bajo la zona media)
    hor = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dh = ImageDraw.Draw(hor)
    dh.line([(60, 1656), (W - 60, 1656)], fill=(*accent, 90), width=2)
    hor = hor.filter(ImageFilter.GaussianBlur(0.6))
    img.alpha_composite(hor)

    # vineta suave (esquinas mas oscuras)
    y, x = np.ogrid[:H, :W]
    dist = np.sqrt(((x - W / 2) / (W * 0.75)) ** 2 + ((y - H / 2) / (H * 0.62)) ** 2)
    vig = np.clip(dist - 0.55, 0, 1) * 60
    arr = np.array(img.convert("RGB"), dtype=np.float32)
    arr -= vig[..., None]

    # grano fotografico
    rng = np.random.default_rng(7)
    grain = rng.normal(0, 6.5, (H, W, 1))
    arr = np.clip(arr + grain, 0, 255).astype(np.uint8)

    out = OUT / f"fondo_cap{cap}.png"
    Image.fromarray(arr, "RGB").save(out)
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    make(cap)
