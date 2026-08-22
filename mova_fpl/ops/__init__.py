"""Plano de control local del operador FPL.

Este paquete coordina y observa el motor, pero no contiene lógica deportiva ni
primitivas de escritura contra FPL. Su autoridad termina en ``ops.db`` y en el
almacén de artefactos del VPS.
"""

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB

__all__ = ["OpsDB", "RuntimeConfig"]
