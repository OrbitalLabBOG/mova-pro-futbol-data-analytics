"""Mockup de distribución S1 (portada cap 1) — placeholders sobre el fondo real."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
IG = ROOT / "ig"
W, H = 1080, 1920
GREEN = (16, 200, 100)
MINT = (120, 255, 170)
INK = (240, 244, 240)
MUTED = (150, 165, 155)

img = Image.open(IG / "assets" / "fondos" / "fondo_cap1.png").convert("RGBA")
d = ImageDraw.Draw(img)

F = IG / "assets" / "fonts"
f_title = ImageFont.truetype(str(F / "BarlowCondensed-Bold.ttf"), 128)
f_big = ImageFont.truetype(str(F / "BarlowCondensed-Bold.ttf"), 56)
f_sub = ImageFont.truetype(str(F / "Barlow-Regular.ttf"), 33)
f_note = ImageFont.truetype(str(F / "Barlow-SemiBold.ttf"), 26)

# ---- TITULO apilado a la izquierda
x0 = 70
d.text((x0, 290), "EL MUNDIAL", font=f_title, fill=INK)
d.text((x0, 420), "DE LA CIENCIA", font=f_title, fill=GREEN)
d.text((x0, 550), "DE DATOS", font=f_title, fill=GREEN)

# ---- COPA fantasma (placeholder: silueta simple wireframe)
cx, cy = 560, 1100
trophy = Image.new("RGBA", (W, H), (0, 0, 0, 0))
td = ImageDraw.Draw(trophy)
# silueta muy basica de copa (solo para ver proporcion/posicion)
td.ellipse([cx - 200, cy - 420, cx + 200, cy - 60], outline=(*GREEN, 60), width=3)
td.polygon([(cx - 150, cy - 120), (cx + 150, cy - 120), (cx + 60, cy + 160), (cx - 60, cy + 160)], outline=(*GREEN, 60))
td.rectangle([cx - 120, cy + 160, cx + 120, cy + 260], outline=(*GREEN, 60), width=3)
for gy in range(cy - 420, cy + 260, 28):
    td.line([(cx - 220, gy), (cx + 220, gy)], fill=(*GREEN, 14), width=1)
img.alpha_composite(trophy)
d.text((cx, cy + 300), "[ COPA WIREFRAME — placeholder ]", font=f_note, fill=(*GREEN, 140), anchor="mm")

# ---- 3 TARJETAS bullet (escalonadas)
cards = [
    (90,  760, "16 CÁMARAS · 50 CAPTURAS/SEG", "computer vision convierte cada jugada en datos", "CAM"),
    (150, 1030, "UN SENSOR A 500HZ EN EL BALÓN", "detecta cada toque · la base del offside automático", "BAL"),
    (90,  1300, "IA GENERATIVA PARA LAS 48", "análisis táctico consultable en segundos", "IA"),
]
for x, y, big, sub, tag in cards:
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cw, ch = 880, 210
    cd.rounded_rectangle([x, y, x + cw, y + ch], radius=26, fill=(10, 24, 18, 215),
                         outline=(*GREEN, 90), width=2)
    # icono placeholder
    cd.ellipse([x + 28, y + 45, x + 148, y + 165], outline=(*MINT, 200), width=3)
    cd.text((x + 88, y + 105), tag, font=f_note, fill=MINT, anchor="mm")
    img.alpha_composite(card)
    d.text((x + 180, y + 72), big, font=f_big, fill=INK)
    d.text((x + 180, y + 138), sub, font=f_sub, fill=MUTED)

# ---- zonas de silencio marcadas (solo en el mockup)
for y0, y1, lab in [(120, 250, "zona libre — UI IG / username"),
                    (1560, 1700, "zona libre — TU TEXTO IG (remate)"),
                    (1700, 1900, "zona libre — UI IG")]:
    d.rectangle([20, y0, W - 20, y1], outline=(255, 255, 255, 60), width=1)
    d.text((W // 2, (y0 + y1) // 2), lab, font=f_note, fill=(255, 255, 255, 90), anchor="mm")

out = IG / "cap1-ciencia-datos" / "work" / "mockup_s1.png"
img.convert("RGB").save(out)
print(f"→ {out.relative_to(ROOT)}")
