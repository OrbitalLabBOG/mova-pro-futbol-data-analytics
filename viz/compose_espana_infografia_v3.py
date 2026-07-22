"""Cap 4 — v3: composición más aireada y canchas en dorado.

Conserva la base orgánica de la v2, mueve el sonar al vacío inferior izquierdo y
separa los hitos centrales. Las líneas de cancha se recolorean durante la
composición; los PNG analíticos originales permanecen intactos.

Salida:
    ig/cap4-espana/work/infografia_espana_v3.png
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from compose_espana_infografia_v2 import (
    BASE,
    GOLD,
    IG,
    OUT,
    ROOT,
    WORK,
    alpha_crop,
    cover,
    fit,
    organic_shadow,
    path_accents,
    title,
)


def golden_pitch(img: Image.Image) -> Image.Image:
    """Convierte el gris técnico de las canchas en un dorado editorial sutil."""
    arr = np.array(img.convert("RGBA"), dtype=np.uint8)
    rgb = arr[..., :3].astype(np.int32)
    ref = np.array([42, 48, 56], dtype=np.int32)  # LINE = #2a3038 en los charts v2
    dist = np.sqrt(((rgb - ref) ** 2).sum(axis=2))
    mask = (dist < 34) & (arr[..., 3] > 20)

    # Dorado menos brillante que nodos/flechas para conservar jerarquía.
    arr[mask, 0] = 184
    arr[mask, 1] = 132
    arr[mask, 2] = 42
    arr[mask, 3] = np.maximum(arr[mask, 3], 145)
    return Image.fromarray(arr)


def paste_chart(canvas: Image.Image, path: Path, box: tuple[int, int, int, int], seed: int,
                glow: float = .32, shadow: int = 195, gold_pitch: bool = False) -> None:
    organic_shadow(canvas, box, seed, alpha=shadow)
    chart = alpha_crop(Image.open(path))
    if gold_pitch:
        chart = golden_pitch(chart)
    chart, pos = fit(chart, box)

    halo = chart.filter(ImageFilter.GaussianBlur(13))
    halo.putalpha(halo.getchannel("A").point(lambda a: int(a * glow * .52)))
    canvas.alpha_composite(halo, pos)

    near = chart.filter(ImageFilter.GaussianBlur(3))
    near.putalpha(near.getchannel("A").point(lambda a: int(a * glow)))
    canvas.alpha_composite(near, pos)
    canvas.alpha_composite(chart, pos)


def main() -> None:
    canvas = cover(Image.open(BASE))

    # Red firma: arriba-derecha, con algo más de aire respecto del equipo.
    paste_chart(canvas, OUT / "v2_red_pro.png", (585, 290, 1045, 595), seed=31,
                glow=.30, shadow=185, gold_pitch=True)

    # Cubarsí y presión dejan de tocarse; cada uno ocupa un hito propio.
    paste_chart(canvas, OUT / "c_cubarsi.png", (30, 790, 500, 1095), seed=32,
                glow=.34, shadow=198, gold_pitch=True)
    paste_chart(canvas, OUT / "v2_presion.png", (545, 1000, 1045, 1325), seed=33,
                glow=.34, shadow=205, gold_pitch=True)

    # Momentum pequeño y desplazado al centro-izquierda: paso, no destino.
    paste_chart(canvas, OUT / "v2_momentum.png", (75, 1240, 660, 1418), seed=34,
                glow=.28, shadow=165)

    # El sonar ocupa el gran vacío inferior izquierdo y equilibra la Copa.
    paste_chart(canvas, OUT / "v2_sonar.png", (45, 1450, 405, 1805), seed=35,
                glow=.30, shadow=175)

    path_accents(canvas)
    title(canvas)

    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "infografia_espana_v3.png"
    canvas.convert("RGB").save(out, quality=95)
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
