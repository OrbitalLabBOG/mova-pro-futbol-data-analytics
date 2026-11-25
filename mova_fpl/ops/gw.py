"""`mova gw close`: cierra una GW con picks públicos + nota de decisión + puntos oficiales.

No usa `review settle-auto` ni exige ejecución verificada (A2/A3, `web_executions`,
`record-manual`): en el copiloto la evidencia es pública (picks de la entrada
oficial, `event/live` asentado) más la nota `decision` guardada en memoria. Solo
GET públicos (fetcher inyectable); la única escritura es una nota `post_mortem`
en memoria con actor/razón/idempotency. No toca FPL.
"""
from __future__ import annotations

from mova_fpl.ops.memory import add_note

SCHEMA = "mova-gw-close-v1"
UNSETTLED_EXIT = 2


class GWNotSettled(RuntimeError):
    """La GW no se puede cerrar todavía (no terminó, sin puntos o sin picks)."""


def _name_index(boot: dict) -> dict:
    index = {}
    for el in boot.get("elements") or ():
        for key in ("web_name", "second_name"):
            if el.get(key):
                index.setdefault(str(el[key]).strip().lower(), int(el["id"]))
    return index


def _resolve(ref, names: dict, unresolved: list) -> int | None:
    """Id de jugador desde un id, un id como texto o un nombre (web_name)."""
    if isinstance(ref, bool):
        unresolved.append(ref)
        return None
    if isinstance(ref, int):
        return ref
    text = str(ref).strip()
    if text.isdigit():
        return int(text)
    found = names.get(text.lower())
    if found is None:
        unresolved.append(ref)
    return found


def _decision_note(db, season: str, gw: int) -> dict | None:
    if db is None:
        return None
    try:
        notes = db.strategy_notes(season=season, gw=gw, kinds=("decision",))
    except Exception:  # noqa: BLE001 - sin tabla no hay nota; se reporta como ausente
        return None
    live = [n for n in notes if not n.get("superseded")]
    return live[0] if live else None


def _points(live: dict) -> dict:
    return {int(el["id"]): int((el.get("stats") or {}).get("total_points") or 0)
            for el in live.get("elements") or ()}


def compute_close(*, gw: int, team_id: int, boot: dict, picks_doc: dict, live: dict,
                  note: dict | None) -> dict:
    """Métricas exactas del cierre. Puro: sin red ni DB."""
    event = next((e for e in boot.get("events") or () if int(e["id"]) == int(gw)), None)
    if not event:
        raise GWNotSettled(f"GW{gw} no existe en bootstrap-static")
    if not (event.get("finished") and event.get("data_checked")):
        raise GWNotSettled(f"GW{gw} todavía no está finished + data_checked")
    picks = picks_doc.get("picks") or []
    entry = picks_doc.get("entry_history") or {}
    points = _points(live)
    if len(picks) != 15 or not points or entry.get("points") is None:
        raise GWNotSettled(f"datos oficiales incompletos: picks={len(picks)} "
                           f"live={len(points)} points={entry.get('points')}")
    actual = sum(points.get(int(p["element"]), 0) * int(p["multiplier"]) for p in picks)
    official = int(entry["points"])
    cost = int(entry.get("event_transfers_cost") or 0)
    actual_captain = next((int(p["element"]) for p in picks if p.get("is_captain")), None)
    out = {
        "schema": SCHEMA, "gw": int(gw), "team_id": int(team_id),
        "official_points": official, "transfers_cost": cost,
        "official_net_points": official - cost,
        "actual_xi_points_recomputed": actual,
        # Distinto a `official` si hubo auto-subs que los multiplicadores del
        # pick no reflejan; se declara en vez de forzarlo.
        "reconciled": actual == official,
        "actual_captain": actual_captain,
        "actual_captain_points": points.get(actual_captain, 0) if actual_captain else None,
        "actual_chip": picks_doc.get("active_chip"),
        "actual_transfers": entry.get("event_transfers"),
        "points_on_bench": entry.get("points_on_bench"),
        "decision_note_found": note is not None,
    }
    if note is None:
        out["decision"] = None
        return out
    players = note.get("players") or {}
    names, unresolved = _name_index(boot), []
    xi = [_resolve(r, names, unresolved) for r in players.get("xi") or ()]
    xi = [e for e in xi if e is not None]
    captain = _resolve(players["captain"], names, unresolved) if players.get("captain") else None
    chip = players.get("chip")
    actual_xi = {int(p["element"]) for p in picks if int(p["multiplier"]) > 0}
    decided = None
    if len(xi) == 11:
        mult = 3 if chip == "3xc" else 2
        decided = sum(points.get(e, 0) for e in xi)
        if captain in xi:
            decided += (mult - 1) * points.get(captain, 0)
    out["decision"] = {
        "note_id": note.get("note_id"), "unresolved_players": unresolved,
        "decided_xi_points": decided,
        "delta_decided_minus_actual": None if decided is None else decided - actual,
        "xi_overlap": len(set(xi) & actual_xi) if len(xi) == 11 else None,
        "xi_missing_from_actual": sorted(set(xi) - actual_xi) if len(xi) == 11 else None,
        "decided_captain": captain,
        "decided_captain_points": points.get(captain, 0) if captain else None,
        "captain_match": (captain == actual_captain) if captain else None,
        "decided_chip": chip, "chip_match": (chip == picks_doc.get("active_chip")
                                              if chip else picks_doc.get("active_chip") is None),
        "decided_hits": players.get("hits"),
        "decided_transfers": len(players.get("transfers_in") or ()),
    }
    return out


def close_gw(config, db, *, gw: int, fetcher, actor: str, reason: str,
             idempotency_key: str, write: bool = True) -> dict:
    """Cierra la GW y escribe la nota `post_mortem` (salvo `write=False`)."""
    boot = fetcher.bootstrap()
    event = next((e for e in boot.get("events") or () if int(e["id"]) == int(gw)), None)
    if not event or not (event.get("finished") and event.get("data_checked")):
        raise GWNotSettled(f"GW{gw} todavía no está finished + data_checked")
    picks_doc = fetcher.picks(config.team_id, int(gw))
    live = fetcher.event_live(int(gw))
    note = _decision_note(db, config.season, int(gw))
    result = compute_close(gw=int(gw), team_id=config.team_id, boot=boot,
                           picks_doc=picks_doc, live=live, note=note)
    result.update({"status": "settled", "settle_auto_used": False, "fpl_mutated": False,
                   "runtime_mutated": False, "post_mortem": None})
    if write:
        text = (f"GW{gw} cerrada: {result['official_points']} pts oficiales "
                f"(-{result['transfers_cost']} hits)"
                + ("" if note is None else
                   f"; decidido {result['decision']['decided_xi_points']} vs "
                   f"real {result['actual_xi_points_recomputed']}")
                + ("" if note else "; sin nota decision") + ".")
        written = add_note(db, season=config.season, gw=int(gw), kind="post_mortem",
                           text=text, players=result, source="assistant", actor=actor,
                           reason=reason, idempotency_key=idempotency_key)
        result["post_mortem"] = {"status": written.get("status"),
                                 "note_id": (written.get("note") or {}).get("note_id")}
        result["runtime_mutated"] = True
    return result
