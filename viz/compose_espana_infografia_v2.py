"""Cap 4 — v2 orgánica de "El camino del campeón".

Los gráficos funcionan como hitos de una ruta escudo → equipo → Copa, sin grid ni
tarjetas rígidas. La base visual se genera como atmósfera; título y datos se
componen de forma determinista.

Salida:
    ig/cap4-espana/work/infografia_espana_v2.png
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
IG = ROOT / "ig"
OUT = ROOT / "outputs" / "divulgacion" / "espana"
WORK = IG / "cap4-espana" / "work"

W, H = 1080, 1920
WHITE = (246, 243, 236)
GOLD = (255, 188, 54)
RED = (236, 47, 62)
DARK = (11, 4, 5)

BASE = IG / "cap4-espana" / "assets" / "espana_camino_base_v2.png"


def cover(img: Image.Image) -> Image.Image:
    ratio = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.Resampling.LANCZOS)
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    return img.crop((left, top, left + W, top + H)).convert("RGBA")


def alpha_crop(img: Image.Image, pad: int = 8) -> Image.Image:
    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        return img
    l, t, r, b = bbox
    return img.crop((max(0, l - pad), max(0, t - pad), min(img.width, r + pad), min(img.height, b + pad)))


def fit(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int]]:
    x0, y0, x1, y1 = box
    ratio = min((x1 - x0) / img.width, (y1 - y0) / img.height)
    img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.Resampling.LANCZOS)
    return img, (x0 + (x1 - x0 - img.width) // 2, y0 + (y1 - y0 - img.height) // 2)


def organic_shadow(canvas: Image.Image, box: tuple[int, int, int, int], seed: int,
                   alpha: int = 205) -> None:
    """Oscurece de manera irregular bajo un gráfico sin crear una tarjeta."""
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rng = np.random.default_rng(seed)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bw, bh = (x1 - x0) * 1.08, (y1 - y0) * .92
    draw.ellipse((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), fill=(*DARK, alpha))
    for _ in range(3):
        ox = rng.uniform(-bw * .22, bw * .22)
        oy = rng.uniform(-bh * .18, bh * .18)
        rw = bw * rng.uniform(.35, .62)
        rh = bh * rng.uniform(.3, .55)
        draw.ellipse((cx + ox - rw / 2, cy + oy - rh / 2,
                      cx + ox + rw / 2, cy + oy + rh / 2), fill=(*DARK, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(42)))


def paste_chart(canvas: Image.Image, path: Path, box: tuple[int, int, int, int], seed: int,
                glow: float = .34, shadow: int = 205) -> None:
    organic_shadow(canvas, box, seed, alpha=shadow)
    chart, pos = fit(alpha_crop(Image.open(path)), box)

    halo = chart.filter(ImageFilter.GaussianBlur(13))
    halo.putalpha(halo.getchannel("A").point(lambda a: int(a * glow * .55)))
    canvas.alpha_composite(halo, pos)

    near = chart.filter(ImageFilter.GaussianBlur(3))
    near.putalpha(near.getchannel("A").point(lambda a: int(a * glow)))
    canvas.alpha_composite(near, pos)
    canvas.alpha_composite(chart, pos)


def title(canvas: Image.Image) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    condensed = IG / "assets" / "fonts" / "BarlowCondensed-Bold.ttf"
    semibold = IG / "assets" / "fonts" / "Barlow-SemiBold.ttf"
    small = ImageFont.truetype(str(semibold), 28)
    big = ImageFont.truetype(str(condensed), 78)

    # Alineación editorial asimétrica: dialoga con el escudo del extremo opuesto.
    x = 1010
    draw.text((x, 86), "EL CAMINO DEL", font=small, fill=WHITE, anchor="ra",
              stroke_width=2, stroke_fill=(8, 3, 3, 180))
    draw.text((x, 148), "CAMPEÓN", font=big, fill=GOLD, anchor="ra",
              stroke_width=3, stroke_fill=(8, 3, 3, 220))
    draw.line((590, 205, 1010, 205), fill=(255, 188, 54, 130), width=2)
    canvas.alpha_composite(layer)


def path_accents(canvas: Image.Image) -> None:
    """Conectores por encima de charts: pocos puntos que cosen los hitos."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rng = np.random.default_rng(26)

    # Tramos añadidos únicamente donde la ruta generada queda tapada por charts.
    segments = [
        ((815, 455), (935, 675), 42),
        ((845, 780), (715, 970), 34),
        ((540, 1080), (330, 1195), 38),
        ((300, 1390), (610, 1510), 42),
    ]
    for (x0, y0), (x1, y1), n in segments:
        for t in np.linspace(0, 1, n):
            x = x0 + (x1 - x0) * t + rng.normal(0, 4)
            y = y0 + (y1 - y0) * t + 12 * np.sin(t * np.pi * 2) + rng.normal(0, 4)
            r = rng.uniform(.8, 2.6)
            col = GOLD if rng.random() > .42 else RED
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(*col, int(rng.uniform(75, 190))))

    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(4)))
    canvas.alpha_composite(layer)


def main() -> None:
    canvas = cover(Image.open(BASE))

    # Hitos alternados alrededor del equipo. Los solapes son deliberados.
    paste_chart(canvas, OUT / "v2_red_pro.png", (565, 280, 1050, 610), seed=1, glow=.30, shadow=190)
    paste_chart(canvas, OUT / "v2_sonar.png", (735, 655, 1050, 965), seed=2, glow=.28, shadow=175)
    paste_chart(canvas, OUT / "c_cubarsi.png", (30, 775, 510, 1100), seed=3, glow=.34, shadow=205)
    paste_chart(canvas, OUT / "v2_presion.png", (520, 980, 1045, 1330), seed=4, glow=.34, shadow=210)

    # Momentum deja de ser una banda dominante: es el penúltimo hito del camino.
    paste_chart(canvas, OUT / "v2_momentum.png", (45, 1285, 680, 1485), seed=5, glow=.30, shadow=180)

    path_accents(canvas)
    title(canvas)

    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "infografia_espana_v2.png"
    canvas.convert("RGB").save(out, quality=95)
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
