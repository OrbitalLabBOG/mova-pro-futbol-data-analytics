"""Estado vivo de la temporada en curso desde la API oficial. Solo lectura.

Normaliza `bootstrap-static` y `fixtures` al MISMO formato que produce
`Store.roster()`, para que la decision en vivo y el backtest consuman
exactamente la misma forma de dato y `decide()` no sepa de donde vino.

La red se toca unicamente a traves de `data/sources.py`, que es la unica
primitiva GET del paquete (REQ-S-002). Aqui no hay ni un `urlopen`.

Disponibilidad
--------------
`bootstrap` trae algo que el historico no tiene: el parte medico. `status` y
`chance_of_playing_next_round` son informacion PRE-deadline —el manager los ve
antes de decidir— y omitirlos seria alinear lesionados. Se traducen a un factor
en [0, 1] que multiplica la probabilidad de jugar.

Es un ajuste que el backtest NO tiene, porque el historico no conserva el parte
medico de cada jornada. Queda declarado: la decision en vivo usa una senal que
las cifras del harness no incluyen.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from mova_fpl.data.identity import player_key
from mova_fpl.data.schema import ALL_COLUMNS
from mova_fpl.data.sources import (fetch_bootstrap, fetch_element_summary,
                                   fetch_event_live, fetch_fixtures, fetch_team,
                                   fetch_team_history, fetch_team_picks)

POSICIONES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

#: traduccion del campo `status` de FPL a factor de disponibilidad
ESTADO = {
    "a": 1.00,   # available
    "d": None,   # doubtful -> manda chance_of_playing_next_round
    "i": 0.00,   # injured
    "s": 0.00,   # suspended
    "u": 0.00,   # unavailable (cedido, fuera del club)
    "n": 0.00,   # not in squad
}


def bootstrap() -> dict:
    return json.loads(fetch_bootstrap())


def fixtures() -> list:
    return json.loads(fetch_fixtures())


def event_live(gw: int) -> dict:
    """Estadísticas oficiales asentadas de una jornada. Solo GET."""
    return json.loads(fetch_event_live(gw))


def settled_gws(boot: dict, target_gw: int) -> tuple[int, ...]:
    """Jornadas anteriores verificadas por FPL y aptas para inferencia causal."""
    return tuple(sorted(
        int(item["id"])
        for item in boot.get("events", ())
        if int(item.get("id", 0)) < int(target_gw)
        and item.get("finished") and item.get("data_checked")
    ))


def historical_team_mismatches(boot: dict, fx: list,
                               payloads: dict[int, dict]) -> tuple[int, ...]:
    """IDs cuyo fixture histórico no contiene el club que bootstrap muestra hoy."""
    catalog = {int(item["id"]): item for item in boot.get("elements", ())}
    fixtures = {int(item["id"]): item for item in fx}
    mismatches = set()
    for payload in payloads.values():
        for observed in payload.get("elements", ()):
            item = catalog.get(int(observed["id"]))
            if item is None:
                continue
            for explanation in observed.get("explain") or ():
                fixture = fixtures.get(int(explanation["fixture"]))
                if fixture is None:
                    continue
                participants = {int(fixture["team_h"]), int(fixture["team_a"])}
                if int(item["team"]) not in participants:
                    mismatches.add(int(observed["id"]))
    return tuple(sorted(mismatches))


def element_summary(element: int) -> dict:
    """Historial oficial individual de temporada. Solo GET."""
    return json.loads(fetch_element_summary(element))


def closed_history(boot: dict, fx: list, payloads: dict[int, dict],
                   season: str, target_gw: int,
                   element_summaries: dict[int, dict] | None = None,
                   ) -> tuple[pd.DataFrame, dict]:
    """Normaliza ``event-live`` a historia causal del modelo.

    La API entrega una estadística agregada por jugador y GW. Una doble jornada
    no se reparte artificialmente entre fixtures: se rechaza hasta disponer de
    un origen por partido. Las jornadas simples conservan estadísticas, rival,
    localía y marcador con la forma del almacén canónico.
    """
    expected = settled_gws(boot, target_gw)
    received = tuple(sorted(int(gw) for gw in payloads))
    if received != expected:
        raise ValueError(
            f"event-live incompleto: asentadas={list(expected)} recibidas={list(received)}"
        )
    clubs = teams(boot)
    catalog = {int(item["id"]): item for item in boot.get("elements", ())}
    fixture_by_gw_team: dict[tuple[int, int], list[dict]] = {}
    fixture_by_id = {}
    for item in fx:
        event = item.get("event")
        if event is None or int(event) not in payloads:
            continue
        fixture_by_id[int(item["id"])] = item
        for side in ("team_h", "team_a"):
            fixture_by_gw_team.setdefault(
                (int(event), int(item[side])), [],
            ).append(item)

    rows = []
    skipped = 0
    skipped_team_mismatch = 0
    repaired_team_mismatch = 0
    summaries = element_summaries or {}
    for gw, payload in sorted(payloads.items()):
        for observed in payload.get("elements", ()):
            element = int(observed["id"])
            item = catalog.get(element)
            if item is None:
                skipped += 1
                continue
            explained = [
                int(record["fixture"])
                for record in (observed.get("explain") or ())
            ]
            if len(set(explained)) > 1:
                raise ValueError(
                    f"GW{gw} contiene DGW para element={element}; "
                    "event-live agregado no se puede desagregar"
                )
            current_team_id = int(item["team"])
            options = fixture_by_gw_team.get((int(gw), current_team_id), [])
            if len(options) != 1:
                raise ValueError(
                    f"calendario ambiguo GW{gw} team={current_team_id}: {len(options)} fixtures"
                )
            fixture = fixture_by_id.get(explained[0]) if explained else options[0]
            if fixture is None:
                raise ValueError(f"fixture explicado ausente para element={element}")
            participants = {int(fixture["team_h"]), int(fixture["team_a"])}
            team_id = current_team_id
            historical_home = None
            if explained and current_team_id not in participants:
                # El jugador cambió de club después de esta jornada. Bootstrap
                # solo conserva su club actual. element-summary sí conserva el
                # fixture y la localía observada; sin esa evidencia se omite.
                history_rows = (summaries.get(element) or {}).get("history") or ()
                historical = next((
                    record for record in history_rows
                    if int(record.get("round", -1)) == int(gw)
                    and int(record.get("fixture", -1)) == int(fixture["id"])
                ), None)
                if historical is None:
                    skipped_team_mismatch += 1
                    continue
                historical_home = bool(historical.get("was_home"))
                team_id = int(fixture["team_h"] if historical_home else fixture["team_a"])
                repaired_team_mismatch += 1
            home = historical_home if historical_home is not None else (
                team_id == int(fixture["team_h"])
            )
            opponent = int(fixture["team_a"] if home else fixture["team_h"])
            name = f"{item.get('first_name', '')} {item.get('second_name', '')}".strip()
            row = {column: np.nan for column in ALL_COLUMNS}
            row.update({
                "season": season, "gw": int(gw), "element": element,
                "fixture": int(fixture["id"]),
                "player_key": player_key(name) or player_key(item.get("web_name", "")),
                "name": name or item.get("web_name", ""),
                "opponent_team": opponent, "was_home": int(home),
                "kickoff_time": fixture.get("kickoff_time"), "round": int(gw),
                # FPL event-live no conserva el precio pasado. El estado histórico
                # del modelo no lo consume; el precio objetivo sí viene del roster.
                "value": int(item["now_cost"]),
                "position": POSICIONES.get(int(item["element_type"])),
                "team": clubs.get(team_id, str(team_id)),
                "team_h_score": fixture.get("team_h_score"),
                "team_a_score": fixture.get("team_a_score"),
            })
            for key, value in (observed.get("stats") or {}).items():
                if key in row:
                    row[key] = value
            rows.append(row)
    frame = pd.DataFrame(rows, columns=ALL_COLUMNS)
    if not frame.empty and int(frame["gw"].max()) >= int(target_gw):
        raise ValueError("event-live contiene la jornada objetivo o futura")
    quality = {
        "rows": int(len(frame)),
        "players": int(frame["player_key"].nunique()),
        "gws": sorted(int(value) for value in frame["gw"].unique()),
        "skipped_missing_current_catalog": int(skipped),
        "skipped_historical_team_mismatch": int(skipped_team_mismatch),
        "repaired_historical_team_mismatch": int(repaired_team_mismatch),
        "duplicate_keys": int(frame.duplicated(
            ["season", "gw", "element", "fixture"],
        ).sum()),
    }
    if quality["gws"] != list(expected) or quality["duplicate_keys"]:
        raise ValueError(f"historia viva inválida: {quality}")
    return frame, quality


def disponibilidad(elemento: dict) -> float:
    """Factor en [0,1]. `status` manda; si es dudoso, el porcentaje declarado."""
    base = ESTADO.get(str(elemento.get("status", "a")).lower(), 1.0)
    if base is not None:
        return float(base)
    pct = elemento.get("chance_of_playing_next_round")
    return 0.5 if pct is None else max(0.0, min(1.0, float(pct) / 100.0))


def teams(boot: dict) -> dict:
    """id -> nombre de club de la temporada en curso."""
    return {int(t["id"]): str(t["name"]) for t in boot["teams"]}


def deadline(boot: dict, gw: int) -> str | None:
    for e in boot["events"]:
        if int(e["id"]) == int(gw):
            return e.get("deadline_time")
    return None


def roster(boot: dict, fx: list, season: str, gw: int) -> pd.DataFrame:
    """Catalogo pre-deadline de una jornada, con la forma de `Store.roster()`.

    Una fila por jugador. En doble jornada se conserva el primer partido, igual
    que hace el almacen; el multiplicador de partidos lo aplica el horizonte.
    """
    clubes = teams(boot)
    partidos = [f for f in fx if f.get("event") == int(gw)]
    if not partidos:
        raise ValueError(f"la API no reporta partidos para la gw {gw}")

    # club -> (id_de_partido, rival, local, hora)
    calendario: dict = {}
    for f in partidos:
        h, a = int(f["team_h"]), int(f["team_a"])
        calendario.setdefault(h, []).append((int(f["id"]), a, 1, f.get("kickoff_time")))
        calendario.setdefault(a, []).append((int(f["id"]), h, 0, f.get("kickoff_time")))

    filas = []
    for e in boot["elements"]:
        tipo = POSICIONES.get(int(e["element_type"]))
        if tipo is None:                       # element_type 5 = manager, fuera de alcance
            continue
        club = int(e["team"])
        if club not in calendario:             # jornada en blanco para ese club
            continue
        pid, rival, local, hora = calendario[club][0]
        nombre = f"{e.get('first_name', '')} {e.get('second_name', '')}".strip()
        filas.append({
            "season": season, "gw": int(gw), "element": int(e["id"]),
            "player_key": player_key(nombre) or player_key(e.get("web_name", "")),
            "name": nombre or e.get("web_name", ""),
            "position": tipo, "team": clubes.get(club, str(club)),
            "value": int(e["now_cost"]), "opponent_team": rival, "was_home": local,
            "fixture": pid, "kickoff_time": hora,
            "disponibilidad": disponibilidad(e),
            "estado": str(e.get("status", "a")),
            "parte": (e.get("news") or "").strip(),
            "propiedad": float(e.get("selected_by_percent") or 0.0),
        })
    return pd.DataFrame(filas)


def team_schedule(fx: list, boot: dict, gw_desde: int, gw_hasta: int) -> dict:
    """{(club, gw): numero de partidos}. Calendario publicado, no resultados."""
    clubes = teams(boot)
    conteo: dict = {}
    for f in fx:
        g = f.get("event")
        if g is None or not (gw_desde <= int(g) <= gw_hasta):
            continue
        for lado in ("team_h", "team_a"):
            clave = (clubes.get(int(f[lado]), str(f[lado])), int(g))
            conteo[clave] = conteo.get(clave, 0) + 1
    return conteo


def fixture_schedule(fx: list, boot: dict, gw_desde: int, gw_hasta: int) -> pd.DataFrame:
    """Calendario vivo con una fila por club y fixture, sin resultados.

    Es la forma equivalente a ``Store.team_fixtures`` para que el mismo
    proyector causal pueda usarse en backtest y en sombra. El rival conserva su
    id anual de FPL; el par de filas del partido permite traducirlo al nombre de
    club sin depender de ids históricos.
    """
    clubes = teams(boot)
    rows = []
    for item in fx:
        event = item.get("event")
        if event is None or not (int(gw_desde) <= int(event) <= int(gw_hasta)):
            continue
        fixture = int(item["id"])
        home, away = int(item["team_h"]), int(item["team_a"])
        kickoff = item.get("kickoff_time")
        rows.extend((
            {
                "season": None, "gw": int(event), "fixture": fixture,
                "team": clubes.get(home, str(home)), "opponent_team": away,
                "was_home": 1, "kickoff_time": kickoff,
            },
            {
                "season": None, "gw": int(event), "fixture": fixture,
                "team": clubes.get(away, str(away)), "opponent_team": home,
                "was_home": 0, "kickoff_time": kickoff,
            },
        ))
    columns = (
        "season", "gw", "fixture", "team", "opponent_team", "was_home",
        "kickoff_time",
    )
    return pd.DataFrame(rows, columns=columns)


def aplicar_disponibilidad(proba, factores) -> "pd.DataFrame":
    """Reasigna masa de probabilidad de jugar hacia `no juega`, sin inventar nada.

    Un jugador con 25% de probabilidad de estar disponible mantiene la FORMA de
    su distribucion de minutos —si juega, juega como suele jugar— pero con un
    cuarto de la masa. El resto va a P(0 minutos).
    """
    import numpy as np
    p = np.asarray(proba, dtype=float).copy()
    f = np.clip(np.asarray(factores, dtype=float), 0.0, 1.0).reshape(-1, 1)
    p[:, 1:] *= f
    p[:, 0] = 1.0 - p[:, 1:].sum(axis=1)
    return p


# --------------------------------------------------------- estado del equipo

#: nombres de chip en la API -> nombres del motor
CHIP_API = {
    "wildcard": "wildcard",
    "freehit": "free_hit",
    "bboost": "bench_boost",
    "3xc": "triple_captain",
}


def team(team_id: int) -> dict:
    return json.loads(fetch_team(team_id))


def team_history(team_id: int) -> dict:
    return json.loads(fetch_team_history(team_id))


def team_picks(team_id: int, gw: int) -> dict:
    return json.loads(fetch_team_picks(team_id, gw))


def chips_used(history: dict) -> tuple:
    """Chips ya gastados, con su jornada, en el formato del motor.

    Los que la API reporta y el catalogo vigente no reconoce se ignoran en
    silencio a proposito: el `assistant manager` de 2024/25 ya no existe y
    tropezarse con el no debe romper una decision.
    """
    from mova_fpl.rules.chips import ChipUse
    out = []
    for c in history.get("chips") or ():
        nombre = CHIP_API.get(str(c.get("name", "")).lower())
        if nombre:
            out.append(ChipUse(gw=int(c["event"]), chip=nombre))
    return tuple(sorted(out, key=lambda u: u.gw))


def free_transfers(history: dict, gw: int, rules: dict, usados: tuple) -> int:
    """Transferencias libres al abrir `gw`, reconstruidas jornada a jornada.

    La API publica no expone el saldo: solo `/api/my-team/`, que exige
    autenticacion y este paquete no toca. Se deriva replicando la regla desde la
    GW1 con el numero de transferencias de cada jornada, que si es publico.

    Con wildcard o free hit las libres NO se consumen: el wildcard hace ilimitadas
    las transferencias y el free hit no toca la plantilla real.
    """
    from mova_fpl.rules.market import accumulate_free_transfers
    sin_coste = {u.gw for u in usados if u.chip in ("wildcard", "free_hit")}
    libres = 1
    for fila in history.get("current") or ():
        g = int(fila.get("event", 0))
        if g < 1 or g >= int(gw):
            continue
        if g == 1:
            libres = 1                              # la plantilla inicial no consume
            continue
        hechas = 0 if g in sin_coste else int(fila.get("event_transfers", 0) or 0)
        libres = accumulate_free_transfers(libres, hechas, rules["max_free_transfers"])
    return max(1, min(int(libres), rules["max_free_transfers"]))


def squad_from_picks(picks: dict, roster: "pd.DataFrame", boot: dict):
    """Plantilla vigente a partir de los quince de la ultima jornada jugada.

    Un jugador cuyo club NO disputa la jornada que se decide no tiene fila en el
    `roster` —esa es la definicion de jornada en blanco— pero SIGUE en la
    plantilla. Sus atributos se leen del bootstrap, que lista a todo el mundo
    juegue o no. Descartarlo dejaria una plantilla de menos de quince y el
    optimizador la reconstruiria como si el jugador no existiera.

    Limitacion declarada (H-LIVE-01): el precio de COMPRA solo lo expone el
    endpoint autenticado, asi que se asume el precio corriente. El presupuesto de
    venta queda ligeramente sobreestimado para jugadores que subieron de precio.
    """
    from mova_fpl.rules.base import Position, Squad, SquadPlayer
    por_id = {int(r["element"]): r for _, r in roster.iterrows()}
    clubes = teams(boot)
    catalogo = {int(e["id"]): e for e in boot["elements"]}

    jugadores, en_blanco = [], []
    for p in picks.get("picks") or ():
        e = int(p["element"])
        r = por_id.get(e)
        if r is not None:
            jugadores.append(SquadPlayer(element=e, position=Position.parse(r["position"]),
                                         team=str(r["team"]), price=float(r["value"]) / 10.0))
            continue
        el = catalogo.get(e)
        if el is None:                              # ni siquiera existe: dato corrupto
            raise ValueError(f"el elemento {e} de la plantilla no esta en el bootstrap")
        en_blanco.append(e)
        jugadores.append(SquadPlayer(
            element=e, position=Position.parse(POSICIONES[int(el["element_type"])]),
            team=clubes.get(int(el["team"]), str(el["team"])),
            price=float(el["now_cost"]) / 10.0))

    hist = picks.get("entry_history") or {}
    banco = float(hist.get("bank", 0) or 0) / 10.0
    return Squad(players=tuple(jugadores), bank=banco), en_blanco


def squad_from_private(payload: dict, roster: "pd.DataFrame", boot: dict):
    """Plantilla pre-deadline con precio de compra real del estado autenticado."""
    from mova_fpl.rules.base import Position, Squad, SquadPlayer

    por_id = {int(r["element"]): r for _, r in roster.iterrows()}
    clubes = teams(boot)
    catalogo = {int(e["id"]): e for e in boot["elements"]}
    jugadores, en_blanco = [], []
    for pick in payload.get("picks") or ():
        element = int(pick["element"])
        row = por_id.get(element)
        item = catalogo.get(element)
        if item is None:
            raise ValueError(f"el elemento {element} privado no está en bootstrap")
        if row is None:
            en_blanco.append(element)
            position = POSICIONES[int(item["element_type"])]
            team_name = clubes.get(int(item["team"]), str(item["team"]))
            current_price = int(item["now_cost"])
        else:
            position = str(row["position"])
            team_name = str(row["team"])
            current_price = int(row["value"])
        jugadores.append(SquadPlayer(
            element=element,
            position=Position.parse(position),
            team=team_name,
            price=current_price / 10.0,
            purchase_price=int(pick["purchase_price"]) / 10.0,
        ))
    bank = int(payload["transfers"]["bank"]) / 10.0
    return Squad(players=tuple(jugadores), bank=bank), en_blanco


def private_team_state(payload: dict, team_id: int, gw: int, roster: "pd.DataFrame",
                       rules: dict, boot: dict) -> dict:
    """Estado exacto pre-deadline; el historial público conserva chips ya usados."""
    from mova_fpl.data.private_state import validate as validate_private

    normalized, quality = validate_private(payload, expected_team_id=team_id)
    if int(normalized["event"]["id"]) != int(gw):
        raise ValueError(
            f"snapshot privado es GW{normalized['event']['id']}; se solicitó GW{gw}"
        )
    squad, en_blanco = squad_from_private(normalized, roster, boot)
    if len(squad.players) != rules["size"]:
        raise ValueError(f"la plantilla privada tiene {len(squad.players)} jugadores")
    usados = chips_used(team_history(team_id))
    return {
        "squad": squad,
        "bank": squad.bank,
        "free_transfers": quality["free_transfers"],
        "chips_used": usados,
        "chips_available": tuple(quality["available_chips"]),
        "en_blanco": en_blanco,
        "ultima_gw": gw,
        "source": "authenticated_api",
        "fingerprint": quality["fingerprint"],
        "current_picks": tuple(normalized["picks"]),
    }


def team_state(team_id: int, gw: int, roster: "pd.DataFrame", rules: dict,
               boot: dict) -> dict:
    """Todo lo que hace falta para decidir la `gw` con el equipo real.

    Devuelve plantilla, banco, transferencias libres y chips gastados. Tres GET
    publicos, ninguna escritura.
    """
    hist = team_history(team_id)
    usados = chips_used(hist)
    libres = free_transfers(hist, gw, rules, usados)

    jugadas = [int(f["event"]) for f in (hist.get("current") or ())
               if int(f.get("event", 0)) < int(gw)]
    if not jugadas:
        # equipo sin jornadas jugadas: es un arranque en frio de verdad
        return {"squad": None, "bank": 0.0, "free_transfers": 1,
                "chips_used": usados, "en_blanco": [], "ultima_gw": None}

    ultima = max(jugadas)
    picks = team_picks(team_id, ultima)
    squad, en_blanco = squad_from_picks(picks, roster, boot)
    if len(squad.players) != rules["size"]:
        raise ValueError(f"la plantilla leida tiene {len(squad.players)} jugadores, "
                         f"se esperaban {rules['size']}")
    return {"squad": squad, "bank": squad.bank, "free_transfers": libres,
            "chips_used": usados, "en_blanco": en_blanco, "ultima_gw": ultima,
            "current_picks": tuple(sorted(
                picks.get("picks") or (), key=lambda item: int(item.get("position", 0))
            ))}
