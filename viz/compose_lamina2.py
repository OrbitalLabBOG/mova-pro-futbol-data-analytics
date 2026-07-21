"""Cap 3 — Lámina 2: dependencia + redes compuestas por código sobre el fondo fucsia.

Los charts se pegan SIN degradación (máscara de bordes desvanecidos + glow + conectores).
Salida: ig/cap3-insights-torneo/work/lamina2_v1.png (1080x1920)
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
IG = ROOT / "ig"
EXP = ROOT / "outputs" / "divulgacion" / "experiments"
W, H = 1080, 1920
FUCSIA = (255, 45, 150)
ROSA = (255, 130, 210)

base = Image.open(IG / "assets" / "fondos" / "fondo_cap3.png").convert("RGBA")


def feathered(img, radius=26, feather=22):
    """Devuelve (imagen, máscara) con esquinas redondeadas y borde desvanecido."""
    m = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([feather, feather, img.width - feather, img.height - feather],
                        radius=radius, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(feather * 0.9))
    return img, m


def glow_patch(size, color, peak=0.5):
    y, x = np.ogrid[:size[1], :size[0]]
    cx, cy = size[0] / 2, size[1] / 2
    d = np.sqrt(((x - cx) / (size[0] * 0.62)) ** 2 + ((y - cy) / (size[1] * 0.62)) ** 2)
    a = (np.clip(1 - d, 0, 1) ** 2.4 * peak * 255).astype(np.uint8)
    layer = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    layer[..., 0], layer[..., 1], layer[..., 2] = color
    layer[..., 3] = a
    return Image.fromarray(layer)


def paste_chart(path, target_w, cy):
    """Pega un chart centrado en x, con glow detras y bordes fundidos. Devuelve (top, bottom)."""
    ch = Image.open(path).convert("RGBA")
    r = target_w / ch.width
    ch = ch.resize((target_w, int(ch.height * r)), Image.LANCZOS)
    x0 = (W - target_w) // 2
    y0 = int(cy - ch.height / 2)
    g = glow_patch((ch.width + 160, ch.height + 160), FUCSIA, peak=0.16)
    base.alpha_composite(g, (x0 - 80, y0 - 80))
    img, m = feathered(ch)
    base.paste(img, (x0, y0), m)
    return y0, y0 + ch.height


# --- bloque 1: dependencia (strip 1x4) ---
top1, bot1 = paste_chart(EXP / "dependencia_strip.png", 1040, 400)

# --- bloque 2: redes (3x2) ---
top2, bot2 = paste_chart(EXP / "redes_vertical.png", 800, 1215)

# --- conector punteado + particulas ---
fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(fx)
rng = np.random.default_rng(11)
ys = np.linspace(bot1 - 30, top2 + 25, 22)
xs = 540 + 28 * np.sin(np.linspace(0, 2.4, 22))
for (px, py) in zip(xs, ys):
    d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(*ROSA, 210))
for _ in range(26):
    px = rng.uniform(80, W - 80)
    py = rng.choice([rng.uniform(top1 - 60, top1 + 30), rng.uniform(bot1 - 20, top2 + 40),
                     rng.uniform(bot2 - 30, bot2 + 60)])
    r = rng.uniform(1.2, 3.2)
    d.ellipse([px - r, py - r, px + r, py + r], fill=(*ROSA, int(rng.uniform(60, 150))))
halo = fx.filter(ImageFilter.GaussianBlur(4))
base.alpha_composite(halo)
base.alpha_composite(fx)

out = IG / "cap3-insights-torneo" / "work" / "lamina2_v1.png"
base.convert("RGB").save(out)
print(f"→ {out.relative_to(ROOT)}")
