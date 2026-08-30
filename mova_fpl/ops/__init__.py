"""Plano de control local del operador FPL.

Este paquete coordina y observa el motor, pero no contiene lógica deportiva ni
primitivas de escritura contra FPL. Su autoridad termina en ``ops.db`` y en el
almacén de artefactos del VPS.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mova_fpl.ops.config import RuntimeConfig
    from mova_fpl.ops.db import OpsDB

__all__ = ["OpsDB", "RuntimeConfig"]


def __getattr__(name: str):
    """Preserve the public API without loading the data stack on import.

    Host-only helpers such as the browser driver must be able to import their
    pure contracts with the system Python.  The operational dependencies are
    loaded only when callers actually request them.
    """
    if name == "OpsDB":
        from mova_fpl.ops.db import OpsDB

        return OpsDB
    if name == "RuntimeConfig":
        from mova_fpl.ops.config import RuntimeConfig

        return RuntimeConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
