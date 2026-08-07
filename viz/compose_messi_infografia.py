"""Compone Cap. 5 — Messi: LA ÚLTIMA FUNCIÓN.

Base visual generada + protagonista real recortado + gráficos/valores precisos.
La salida V1 queda en work; no se promueve a final hasta aprobación editorial.
"""

from pathlib import Path
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "ig" / "cap5-messi" / "assets"
CHARTS = ROOT / "outputs" / "divulgacion" / "messi"
WORK = ROOT / "ig" / "cap5-messi" / "work"
WORK.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1920
BG = "#050D19"
CYAN = "#75AADB"
ELECTRIC = "#82DDFF"
WHITE = "#F4F8FB"
MUTED = "#7890A6"
TURQUOISE = "#25DFC4"
CORAL = "#F04B5F"
GOLD = "#E8C56A"

FONT_DIR = ROOT / "ig" / "assets" / "fonts"
REG = FONT_DIR / "Barlow-Regular.ttf"
SEMI = FONT_DIR / "Barlow-SemiBold.ttf"
COND = FONT_DIR / "BarlowCondensed-Bold.ttf"


def font(path, size):
    return ImageFont.truetype(str(path), size)


def rgba(hex_color, alpha=255):
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def set_opacity(image, opacity):
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(lambda a: int(a * opacity))
    image.putalpha(alpha)
    return image


def contain(path, box, opacity=1.0):
    image = Image.open(path).convert("RGBA")
    max_w, max_h = box
    ratio = min(max_w / image.width, max_h / image.height)
    image = image.resize(
        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
        Image.Resampling.LANCZOS,
    )
    return set_opacity(image, opacity)


def paste_center(canvas, image, box):
    x0, y0, x1, y1 = box
    x = x0 + (x1 - x0 - image.width) // 2
    y = y0 + (y1 - y0 - image.height) // 2
    canvas.alpha_composite(image, (x, y))


def glow_text(canvas, xy, text, fnt, fill, anchor="la", glow=10, glow_alpha=110):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mask = Image.new("L", canvas.size, 0)
    md = ImageDraw.Draw(mask)
    md.text(xy, text, font=fnt, fill=glow_alpha, anchor=anchor)
    blur = mask.filter(ImageFilter.GaussianBlur(glow))
    aura = Image.new("RGBA", canvas.size, rgba(fill, 0))
    aura.putalpha(blur)
    canvas.alpha_composite(aura)
    draw = ImageDraw.Draw(layer)
    draw.text(xy, text, font=fnt, fill=rgba(fill), anchor=anchor)
    canvas.alpha_composite(layer)


def draw_orbital_kpis(canvas):
    """KPIs asimétricos: reloj, récord, núcleo xT y constelación 12/18."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = random.Random(10)

    # 21 goles: arco de 21 cuerpos dorados, elevado y secundario al título.
    cx, cy, rx, ry = 882, 398, 104, 75
    d.arc((cx - rx, cy - ry, cx + rx, cy + ry), 198, 520, fill=rgba(GOLD, 105), width=2)
    for i in range(21):
        a = math.radians(198 + i * (322 / 20))
        x = cx + rx * math.cos(a)
        y = cy + ry * math.sin(a)
        r = 2 if i < 13 else 3
        d.ellipse((x - r, y - r, x + r, y + r), fill=rgba(GOLD, 120 + i * 5))
    d.text((cx, cy - 7), "21", font=font(COND, 72), anchor="mm", fill=rgba(GOLD))
    d.text((cx, cy + 43), "GOLES", font=font(SEMI, 15), anchor="mm", fill=rgba(WHITE, 220))

    # 39 años: un reloj incompleto pequeño, cerca del héroe pero sin competir.
    cx, cy, r = 920, 735, 58
    d.arc((cx - r, cy - r, cx + r, cy + r), 35, 300, fill=rgba(CYAN, 190), width=3)
    for i in range(12):
        a = math.radians(35 + i * 265 / 11)
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=rgba(ELECTRIC, 155))
    d.text((cx, cy - 4), "39", font=font(COND, 47), anchor="mm", fill=rgba(CYAN))
    d.text((cx, cy + 29), "AÑOS", font=font(SEMI, 12), anchor="mm", fill=rgba(WHITE, 210))

    # 5.40 xT: el núcleo estadístico principal, con energía y partículas.
    cx, cy = 185, 895
    for radius, alpha, width in [(105, 65, 2), (82, 85, 2), (58, 115, 3)]:
        d.arc(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            210,
            510,
            fill=rgba(TURQUOISE, alpha),
            width=width,
        )
    for _ in range(42):
        a = rng.random() * math.tau
        rr = rng.uniform(58, 118)
        x, y = cx + math.cos(a) * rr, cy + math.sin(a) * rr
        rad = rng.choice([1, 1, 2, 3])
        d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=rgba(TURQUOISE, rng.randint(65, 190)))
    d.text((cx, cy - 8), "5.40", font=font(COND, 84), anchor="mm", fill=rgba(TURQUOISE))
    d.text((cx, cy + 49), "xT", font=font(SEMI, 18), anchor="mm", fill=rgba(WHITE, 235))

    # 12/18: dieciocho puntos exactos, doce encendidos.
    cx, cy, rx, ry = 240, 1535, 145, 88
    d.arc((cx - rx, cy - ry, cx + rx, cy + ry), 175, 505, fill=rgba(CYAN, 70), width=2)
    for i in range(18):
        a = math.radians(175 + i * (330 / 17))
        x = cx + rx * math.cos(a)
        y = cy + ry * math.sin(a)
        active = i < 12
        rad = 5 if active else 3
        color = GOLD if active and i % 4 == 0 else (CYAN if active else MUTED)
        alpha = 235 if active else 90
        d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=rgba(color, alpha))
    d.text((cx, cy - 2), "12/18", font=font(COND, 65), anchor="mm", fill=rgba(WHITE))
    d.text((cx, cy + 48), "GOLES CON SU SELLO", font=font(SEMI, 14), anchor="mm", fill=rgba(CYAN, 230))

    canvas.alpha_composite(layer)


def add_shot_kpi(canvas):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((958, 1047), "8", font=font(COND, 83), anchor="mm", fill=rgba(GOLD))
    d.text((958, 1098), "GOLES", font=font(SEMI, 14), anchor="mm", fill=rgba(WHITE, 220))
    # Dos pequeñas incisiones coral refuerzan la lectura de los penales sin copy.
    for x in (937, 978):
        d.line((x - 7, 1122 - 7, x + 7, 1122 + 7), fill=rgba(CORAL, 220), width=3)
        d.line((x - 7, 1122 + 7, x + 7, 1122 - 7), fill=rgba(CORAL, 220), width=3)
    canvas.alpha_composite(layer)


def add_subject(canvas):
    source = Image.open(ASSETS / "messi_cutout_v1.png").convert("RGBA")
    bbox = source.getchannel("A").getbbox()
    subject = source.crop(bbox)
    target_h = 1005
    subject = subject.resize(
        (int(subject.width * target_h / subject.height), target_h),
        Image.Resampling.LANCZOS,
    )
    subject = ImageEnhance.Color(subject).enhance(0.92)
    subject = ImageEnhance.Contrast(subject).enhance(1.08)
    subject = ImageEnhance.Brightness(subject).enhance(0.91)
    x, y = 190, 252

    # Sombra profunda para separarlo de los mapas.
    alpha = subject.getchannel("A")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(22)).point(lambda a: int(a * 0.72))
    shadow = Image.new("RGBA", subject.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    canvas.alpha_composite(shadow, (x + 15, y + 18))

    # Rim celeste muy contenido que casa el recorte diurno con la escena nocturna.
    rim_alpha = alpha.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(8))
    rim_alpha = ImageChops.subtract(rim_alpha, alpha).point(lambda a: int(a * 0.62))
    rim = Image.new("RGBA", subject.size, rgba(ELECTRIC, 0))
    rim.putalpha(rim_alpha)
    canvas.alpha_composite(rim, (x, y))
    canvas.alpha_composite(subject, (x, y))


def add_title(canvas):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((62, 54), "MESSI · 39 AÑOS", font=font(SEMI, 18), fill=rgba(CYAN, 230))
    d.text((60, 82), "LA ÚLTIMA", font=font(COND, 58), fill=rgba(WHITE))
    canvas.alpha_composite(layer)
    glow_text(canvas, (58, 126), "FUNCIÓN", font(COND, 112), CYAN, glow=13, glow_alpha=95)
    d = ImageDraw.Draw(canvas)
    d.line((62, 247, 475, 247), fill=rgba(ELECTRIC, 115), width=2)


def add_vignette(canvas):
    # Oscurece bordes y parte inferior sin borrar la textura generada.
    mask = Image.new("L", (W, H), 0)
    px = mask.load()
    cx, cy = W * 0.56, H * 0.48
    maxd = math.hypot(max(cx, W - cx), max(cy, H - cy))
    for yy in range(H):
        for xx in range(W):
            d = math.hypot(xx - cx, yy - cy) / maxd
            edge = max(0.0, min(1.0, (d - 0.50) / 0.50))
            bottom = max(0.0, (yy / H - 0.82) / 0.18)
            px[xx, yy] = int(110 * edge * edge + 45 * bottom)
    black = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    black.putalpha(mask.filter(ImageFilter.GaussianBlur(35)))
    canvas.alpha_composite(black)


def compose():
    background = Image.open(ASSETS / "messi_orbital_background_v1.png").convert("RGB")
    background = ImageOps.fit(background, (W, H), method=Image.Resampling.LANCZOS)
    canvas = background.convert("RGBA")
    add_vignette(canvas)

    # Los mapas son paisaje: aparecen antes del protagonista para que el cuerpo
    # los tape parcialmente, como ocurría con los gráficos sobre el equipo español.
    territory = contain(CHARTS / "clean_territorio_xt.png", (710, 470), opacity=0.70)
    territory = ImageOps.mirror(territory)
    paste_center(canvas, territory, (0, 300, 715, 775))

    shots = contain(CHARTS / "clean_mapa_tiros.png", (395, 570), opacity=0.74)
    paste_center(canvas, shots, (650, 1010, 1065, 1610))

    draw_orbital_kpis(canvas)
    add_subject(canvas)
    add_shot_kpi(canvas)
    add_title(canvas)

    # Firma mínima; el copy narrativo seguirá viviendo en Instagram.
    d = ImageDraw.Draw(canvas)
    d.text((60, 1858), "MOVA MUNDIAL · CAPÍTULO 5", font=font(SEMI, 14), fill=rgba(MUTED, 155))
    d.line((60, 1838, 345, 1838), fill=rgba(ELECTRIC, 75), width=1)

    out = WORK / "infografia_messi_v4.png"
    canvas.convert("RGB").save(out, quality=96)
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    compose()
