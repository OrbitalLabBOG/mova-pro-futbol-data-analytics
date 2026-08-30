"""Capa de datos: fuentes, ingesta y almacén con contrato temporal."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mova_fpl.data.store import LeakageError, Store, assert_causal, feature_columns

__all__ = ["Store", "LeakageError", "assert_causal", "feature_columns"]


def __getattr__(name: str):
    """Load the dataframe-backed store only for callers that request it."""
    if name in __all__:
        from mova_fpl.data import store

        return getattr(store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
