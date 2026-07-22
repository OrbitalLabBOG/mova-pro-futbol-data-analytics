"""Cap 4 — primera composición editorial de "El camino del campeón".

Combina una base fotográfica/atmosférica con gráficos reproducibles de España.
La IA no interviene en texto ni en datos: título y charts se componen por código.

Salida:
    ig/cap4-espana/work/infografia_espana_v1.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
IG = ROOT / "ig"
OUT = ROOT / "outputs" / "divulgacion" / "espana"

W, H = 1080, 1920
WHITE = (246, 243, 236)
GOLD = (255, 187, 54)

BASE = IG / "cap4-espana" / "assets" / "espana_equipo_base_v1.png"
WORK = IG / "cap4-espana" / "work"
WORK.mkdir(parents=True, exist_ok=True)


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Escala y recorta al centro para cubrir el lienzo."""
    tw, th = size
    ratio = max(tw / img.width, th / img.height)
    img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.Resampling.LANCZOS)
    left = (img.width - tw) // 2
    top = (img.height - th) // 2
    return img.crop((left, top, left + tw, top + th))


def alpha_crop(img: Image.Image, pad: int = 8) -> Image.Image:
    """Elimina aire transparente sin cortar halos ni etiquetas del gráfico."""
    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        return img
    l, t, r, b = bbox
    return img.crop((max(0, l - pad), max(0, t - pad), min(img.width, r + pad), min(img.height, b + pad)))


def fit(img: Image.Image, box: tuple[int, int, int, int], inset: int = 18) -> tuple[Image.Image, tuple[int, int]]:
    """Ajusta un PNG transparente dentro de una caja y devuelve imagen + posición."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0 - 2 * inset, y1 - y0 - 2 * inset
    ratio = min(bw / img.width, bh / img.height)
    img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.Resampling.LANCZOS)
    x = x0 + (x1 - x0 - img.width) // 2
    y = y0 + (y1 - y0 - img.height) // 2
    return img, (x, y)


def paste_neon(canvas: Image.Image, path: Path, box: tuple[int, int, int, int], inset: int = 18,
               glow_strength: float = 0.42) -> None:
    """Pega un chart transparente con doble halo, preservando sus píxeles."""
    chart = alpha_crop(Image.open(path))
    chart, pos = fit(chart, box, inset=inset)

    wide = chart.filter(ImageFilter.GaussianBlur(14))
    wide.putalpha(wide.getchannel("A").point(lambda a: int(a * glow_strength * 0.55)))
    canvas.alpha_composite(wide, pos)

    close = chart.filter(ImageFilter.GaussianBlur(4))
    close.putalpha(close.getchannel("A").point(lambda a: int(a * glow_strength)))
    canvas.alpha_composite(close, pos)
    canvas.alpha_composite(chart, pos)


def title_layer() -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    condensed = IG / "assets" / "fonts" / "BarlowCondensed-Bold.ttf"
    regular = IG / "assets" / "fonts" / "Barlow-SemiBold.ttf"
    f_small = ImageFont.truetype(str(regular), 30)
    f_big = ImageFont.truetype(str(condensed), 92)

    # La transición foto→datos queda libre de caras y funciona como masthead.
    kicker = "EL CAMINO DEL"
    main = "CAMPEÓN"
    y0 = 655
    draw.text((W // 2, y0), kicker, font=f_small, fill=WHITE, anchor="mm",
              stroke_width=2, stroke_fill=(10, 5, 5, 190))
    draw.text((W // 2, y0 + 72), main, font=f_big, fill=GOLD, anchor="mm",
              stroke_width=3, stroke_fill=(10, 5, 5, 220))

    # Línea fina: gesto editorial, no una caja.
    draw.line((155, y0 + 126, W - 155, y0 + 126), fill=(255, 182, 45, 105), width=2)
    return layer


def main() -> None:
    canvas = cover(Image.open(BASE).convert("RGBA"), (W, H))

    # Cajas que el fondo reservó. Se dejan márgenes amplios para lectura móvil.
    boxes = {
        "red": (88, 825, 528, 1103),
        "sonar": (552, 825, 992, 1103),
        "cubarsi": (88, 1120, 528, 1405),
        "presion": (552, 1120, 992, 1405),
        "momentum": (82, 1435, 998, 1762),
    }

    paste_neon(canvas, OUT / "v2_red_pro.png", boxes["red"], inset=8, glow_strength=.34)
    paste_neon(canvas, OUT / "v2_sonar.png", boxes["sonar"], inset=16, glow_strength=.28)
    paste_neon(canvas, OUT / "c_cubarsi.png", boxes["cubarsi"], inset=10, glow_strength=.32)
    paste_neon(canvas, OUT / "v2_presion.png", boxes["presion"], inset=8, glow_strength=.34)
    paste_neon(canvas, OUT / "v2_momentum.png", boxes["momentum"], inset=24, glow_strength=.35)

    canvas.alpha_composite(title_layer())

    out = WORK / "infografia_espana_v1.png"
    canvas.convert("RGB").save(out, quality=95)
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
