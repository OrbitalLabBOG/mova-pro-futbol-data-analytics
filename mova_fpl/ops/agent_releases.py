"""Small Git-backed registry; a version pins behavior, the image pins implementation."""
import json
from pathlib import Path


def researcher_release(version: str | None = None) -> tuple[str, dict]:
    registry = json.loads(Path(__file__).with_suffix('.json').read_text())['agents']['researcher']
    version = version or registry['active']
    if version not in registry['versions']:
        raise ValueError('versión de researcher desconocida')
    return version, registry['versions'][version]
