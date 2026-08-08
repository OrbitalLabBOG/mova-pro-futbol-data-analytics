"""Identidad estable de jugador entre temporadas.

El campo `element` de FPL **se reasigna cada temporada**: el elemento 1 es David
Ospina en 2016-17 y David Raya en 2025-26. Agrupar historial por `element` a lo
largo de varias temporadas empalma jugadores distintos, que no es una feature
pobre sino un error de correctitud.

El campo `name` tampoco sirve directo porque el formato del origen cambio tres
veces:

    2016-17, 2017-18   David_Ospina          guion bajo
    2018-19, 2019-20   Petr_Cech_1           guion bajo + sufijo del element id
    2020-21 en adelante David Raya Martin    espacios y acentos

Por eso las transiciones 2017-18 -> 2018-19 y 2019-20 -> 2020-21 compartian CERO
jugadores. Con `player_key` comparten 418 y 451.
"""
from __future__ import annotations

import re
import unicodedata

_SUFIJO_ID = re.compile(r"_\d+$")
_NO_ALFA = re.compile(r"[^a-z ]")
_ESPACIOS = re.compile(r"\s+")


def player_key(name) -> str | None:
    """Nombre normalizado, estable entre temporadas.

    Quita el sufijo `_<id>`, cambia guiones bajos por espacios, elimina acentos y
    baja a minusculas.
    """
    if name is None:
        return None
    s = str(name).strip()
    if not s or s.lower() == "nan":
        return None
    s = _SUFIJO_ID.sub("", s).replace("_", " ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = _NO_ALFA.sub(" ", s)
    s = _ESPACIOS.sub(" ", s).strip()
    return s or None
