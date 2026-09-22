"""Conservative, deterministic checks for research evidence at import time."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta


TOPIC_WORDS = {
    "availability": ("available", "fit", "injur", "out", "doubt", "return", "squad", "disponib", "baja"),
    "injury": ("injur", "hamstring", "muscle", "knee", "ankle", "calf", "groin", "sidelined", "lesion"),
    "suspension": ("suspend", "ban", "red card", "yellow card", "sancion", "expuls"),
    "expected_minutes": ("minute", "start", "bench", "substitut", "rest", "rotation", "titular"),
    "starting_role": ("start", "lineup", "line-up", " xi ", "midfield", "wing", "forward", "defence", "role", "posicion"),
    "set_pieces": ("penalt", "corner", "free-kick", "free kick", "set-piece", "balon parado", "falta"),
    "transfer": ("transfer", "sign", "join", "loan", "depart", "fich", "cesion"),
    "fixture_context": ("fixture", "match", "opponent", "home", "away", "vs ", "calendario", "partido"),
    "manager_comment": ("manager", "coach", "said", "press conference", "entrenador", "declaro"),
}


def _normal(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def subject_in_excerpt(name: str, excerpt: str) -> bool:
    """Require an explicit player name; a generic team article is not coverage."""
    text = _normal(excerpt)
    tokens = re.findall(r"[a-z0-9]+", _normal(name))
    candidates = [" ".join(tokens)] if len(tokens) > 1 else []
    if tokens and len(tokens[-1]) >= 4:
        candidates.append(tokens[-1])
    return any(re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text)
               for token in candidates)


def claim_supported(*, name: str, claim_type: str, excerpt: str, quality_policy: str | None = None) -> bool:
    if not subject_in_excerpt(name, excerpt):
        return False
    terms = TOPIC_WORDS.get(claim_type)
    if quality_policy in {"research-claim-2026.09.3", "research-claim-2026.09.4", "research-claim-2026.09.5"} and claim_type == "starting_role":
        terms = (*terms, "bench", "substitut", "suplente", "banquillo")
    if quality_policy in {"research-claim-2026.09.4", "research-claim-2026.09.5"} and claim_type == "injury":
        terms = (*terms, "neck issue", "neck problem")
    if quality_policy == "research-claim-2026.09.5":
        if claim_type == "starting_role":
            terms = (*terms, "line up", "lines up")
        elif claim_type == "set_pieces":
            terms = (*terms, "pk duties", "on pks", "pk taker", "pk role")
    if not terms:
        return False
    text = _normal(excerpt)
    return any(term in text for term in terms)


def claim_fresh(*, claim_type: str, published_at: str, observed: datetime) -> bool:
    """A dated historical match is not automatically a current role or fitness signal."""
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if published.tzinfo is None:
        return False
    max_age = timedelta(days=3 if claim_type in {
        "availability", "injury", "suspension", "expected_minutes",
    } else 7 if claim_type in {"starting_role", "set_pieces", "manager_comment"}
        else 30 if claim_type == "transfer" else 7)
    return observed - max_age <= published <= observed
