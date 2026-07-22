"""Cap 4 — v4 final de "El camino del campeón".

Ajustes de cierre: título compacto, sonar con anillos dorados, momentum más
estrecho y sonar desplazado hacia abajo/centro.

Salidas:
    ig/cap4-espana/work/infografia_espana_v4.png
    ig/cap4-espana/final/el_camino_del_campeon.png
"""

from PIL import Image, ImageDraw, ImageFont

from compose_espana_infografia_v2 import BASE, IG, OUT, WORK, cover, path_accents
from compose_espana_infografia_v3 import paste_chart


W, H = 1080, 1920
WHITE = (246, 243, 236)
GOLD = (255, 188, 54)


def title_compact(canvas: Image.Image) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    condensed = IG / "assets" / "fonts" / "BarlowCondensed-Bold.ttf"
    semibold = IG / "assets" / "fonts" / "Barlow-SemiBold.ttf"
    small = ImageFont.truetype(str(semibold), 28)
    big = ImageFont.truetype(str(condensed), 78)

    x = 1010
    draw.text((x, 82), "EL CAMINO DEL", font=small, fill=WHITE, anchor="rt",
              stroke_width=2, stroke_fill=(8, 3, 3, 180))
    draw.text((x, 116), "CAMPEÓN", font=big, fill=GOLD, anchor="rt",
              stroke_width=3, stroke_fill=(8, 3, 3, 220))
    draw.line((590, 198, 1010, 198), fill=(255, 188, 54, 130), width=2)
    canvas.alpha_composite(layer)


def main() -> None:
    canvas = cover(Image.open(BASE))

    paste_chart(canvas, OUT / "v2_red_pro.png", (585, 290, 1045, 595), seed=41,
                glow=.30, shadow=185, gold_pitch=True)
    paste_chart(canvas, OUT / "c_cubarsi.png", (30, 790, 500, 1095), seed=42,
                glow=.34, shadow=198, gold_pitch=True)
    paste_chart(canvas, OUT / "v2_presion.png", (545, 1000, 1045, 1325), seed=43,
                glow=.34, shadow=205, gold_pitch=True)

    # Momentum más angosto: termina antes de la presión y queda contenido.
    paste_chart(canvas, OUT / "v2_momentum.png", (75, 1260, 505, 1425), seed=44,
                glow=.28, shadow=155)

    # Sonar más abajo y hacia el centro; sus anillos comparten el dorado de las canchas.
    paste_chart(canvas, OUT / "v2_sonar.png", (150, 1510, 485, 1840), seed=45,
                glow=.30, shadow=170, gold_pitch=True)

    path_accents(canvas)
    title_compact(canvas)

    WORK.mkdir(parents=True, exist_ok=True)
    final_dir = IG / "cap4-espana" / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    work = WORK / "infografia_espana_v4.png"
    final = final_dir / "el_camino_del_campeon.png"
    rgb = canvas.convert("RGB")
    rgb.save(work, quality=95)
    rgb.save(final, quality=95)
    print(f"→ {work.relative_to(IG.parent)}")
    print(f"→ {final.relative_to(IG.parent)}")


if __name__ == "__main__":
    main()
