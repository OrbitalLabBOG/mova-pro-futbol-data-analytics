"""Recorta a Messi y el balón de la foto elegida usando GrabCut guiado.

El objetivo no es crear un asset definitivo aislado para reutilización general,
sino una máscara suficientemente limpia para la composición vertical del cap. 5.
"""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ig" / "cap5-messi" / "assets" / "Messi-gol-2.webp"
OUT = ROOT / "ig" / "cap5-messi" / "assets" / "messi_cutout_v1.png"
PREVIEW = ROOT / "ig" / "cap5-messi" / "work" / "messi_cutout_preview_v1.png"


def line(mask, a, b, width):
    cv2.line(mask, a, b, cv2.GC_FGD, width, cv2.LINE_AA)


def preview_cutout():
    bgra = cv2.imread(str(OUT), cv2.IMREAD_UNCHANGED)
    if bgra is None or bgra.shape[2] != 4:
        raise RuntimeError("El recorte no contiene canal alpha")
    bgr, alpha = bgra[:, :, :3], bgra[:, :, 3]
    checker = np.full_like(bgr, (110, 35, 110))
    a = alpha.astype(np.float32)[:, :, None] / 255
    preview = (bgr * a + checker * (1 - a)).astype(np.uint8)
    cv2.imwrite(str(PREVIEW), preview)


def main_rembg():
    """Segmentación principal; U2-Net resuelve huecos entre brazos y piernas."""
    from rembg import remove

    result = remove(
        SOURCE.read_bytes(),
        alpha_matting=True,
        alpha_matting_foreground_threshold=235,
        alpha_matting_background_threshold=15,
        alpha_matting_erode_size=8,
    )
    OUT.write_bytes(result)
    preview_cutout()
    print(f"→ {OUT.relative_to(ROOT)}")
    print(f"→ {PREVIEW.relative_to(ROOT)}")


def main():
    bgr = cv2.imread(str(SOURCE), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(SOURCE)
    h, w = bgr.shape[:2]

    # Arrancamos con fondo probable y guiamos el algoritmo con la silueta real.
    mask = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)
    mask[:, :235] = cv2.GC_BGD
    mask[:, 790:] = cv2.GC_BGD
    mask[575:, :245] = cv2.GC_BGD
    mask[585:, 790:] = cv2.GC_BGD

    # Zona completa donde viven jugador y balón.
    mask[0:598, 255:770] = cv2.GC_PR_FGD

    # Semillas inequívocas de primer plano: cabeza, torso, brazos, shorts,
    # ambas piernas y el balón. Las líneas gruesas siguen el eje de cada miembro.
    cv2.ellipse(mask, (538, 65), (45, 64), 0, 0, 360, cv2.GC_FGD, -1)
    cv2.fillConvexPoly(
        mask,
        np.array([(461, 108), (596, 96), (642, 285), (475, 325), (424, 190)]),
        cv2.GC_FGD,
    )
    line(mask, (462, 145), (326, 225), 27)
    line(mask, (604, 145), (720, 225), 25)
    cv2.fillConvexPoly(
        mask,
        np.array([(466, 286), (641, 278), (628, 395), (455, 400)]),
        cv2.GC_FGD,
    )
    line(mask, (486, 370), (346, 526), 45)
    line(mask, (590, 371), (520, 548), 48)
    line(mask, (347, 524), (309, 557), 28)
    line(mask, (520, 548), (520, 585), 29)
    cv2.circle(mask, (676, 536), 37, cv2.GC_FGD, -1)

    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, None, bg_model, fg_model, 12, cv2.GC_INIT_WITH_MASK)

    alpha = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)

    # Cerrar poros pequeños, suavizar un píxel y conservar cabellos/bordes finos.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel, iterations=1)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.65)

    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = alpha
    cv2.imwrite(str(OUT), bgra)
    preview_cutout()
    print(f"→ {OUT.relative_to(ROOT)}")
    print(f"→ {PREVIEW.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main_rembg()
    except (ImportError, ModuleNotFoundError) as exc:
        print(f"rembg no disponible ({exc}); usando GrabCut guiado")
        main()
