"""Briefing as-of para el agente, construido desde el State del simulador.

Disciplina as-of (la misma del motor):
- historial: solo gw < GW (pts/min/titularidades/tarjetas de las ultimas 4);
- snapshot de la GW (precio, transfers_balance, fixture): campos pre-deadline;
- cuotas: APERTURA Pinnacle del partido de la GW (betting.db, mirror football-data).
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAPA_EQUIPOS = {"Man Utd": "Man United", "Spurs": "Tottenham"}
TEMPORADA_ODDS = {"2025-26": "2526", "2024-25": "2425"}


class Briefer:
    def __init__(self, season: str):
        self.season = season
        self.can = sqlite3.connect(ROOT / "data/processed/fpl_canonical.db")
        self.can.row_factory = sqlite3.Row
        self.bet = sqlite3.connect(ROOT / "data/betting.db")
        self.bet.row_factory = sqlite3.Row

    def _historial(self, gw: int) -> dict:
        h = defaultdict(list)
        for r in self.can.execute(
                "SELECT element, total_points, minutes, starts, yellow_cards, red_cards"
                " FROM player_gameweek WHERE season=? AND gw<? AND gw>=? ORDER BY gw",
                (self.season, gw, gw - 4)):
            h[r["element"]].append(dict(r))
        return h

    def _snapshot(self, gw: int) -> dict:
        return {r["element"]: dict(r) for r in self.can.execute(
            "SELECT element, name, position, team, value, selected, transfers_balance,"
            " opponent_team, was_home FROM player_gameweek WHERE season=? AND gw=?",
            (self.season, gw))}

    def _precios_previos(self, gw: int) -> dict:
        return {r["element"]: r["value"] for r in self.can.execute(
            "SELECT element, value FROM player_gameweek WHERE season=? AND gw=?",
            (self.season, max(1, gw - 2)))}

    def _cuotas(self, gw: int) -> dict:
        k = self.can.execute(
            "SELECT MIN(kickoff_time), MAX(kickoff_time) FROM player_gameweek"
            " WHERE season=? AND gw=?", (self.season, gw)).fetchone()
        if not k or not k[0]:
            return {}
        cuotas = {}
        for r in self.bet.execute(
                "SELECT home_team, away_team, PSH, PSD, PSA FROM club_matches"
                " WHERE league='premier-league' AND season=? AND match_date BETWEEN ? AND ?",
                (TEMPORADA_ODDS.get(self.season, ""), k[0][:10], k[1][:10])):
            inv = lambda x: 1.0 / x if x else 0.0
            tot = inv(r["PSH"]) + inv(r["PSD"]) + inv(r["PSA"]) or 1.0
            cuotas[r["home_team"]] = round(inv(r["PSH"]) / tot, 2)
            cuotas[r["away_team"]] = round(inv(r["PSA"]) / tot, 2)
        return cuotas

    def _fila(self, e: int, snap, hist, prev, cuotas) -> dict | None:
        s = snap.get(e)
        if s is None:
            return None
        h = hist.get(e, [])
        equipo_odds = MAPA_EQUIPOS.get(s["team"], s["team"])
        return {
            "id": e, "nombre": s["name"], "pos": s["position"], "equipo": s["team"],
            "precio": s["value"] / 10,
            "delta_precio_2gw": round((s["value"] - prev.get(e, s["value"])) / 10, 1),
            "pts_ult4": [x["total_points"] for x in h],
            "min_ult4": [x["minutes"] for x in h],
            "titular_ult4": [int(x["starts"] or 0) for x in h],
            "tarjetas_ult4": [f'{x["yellow_cards"]}A/{x["red_cards"]}R' for x in h],
            "transfers_balance_gw": s["transfers_balance"],
            "rival": s["opponent_team"], "casa": bool(s["was_home"]),
            "p_victoria_equipo": cuotas.get(equipo_odds),
        }

    def build(self, state, memoria_texto: str = "") -> str:
        gw = state.gw
        snap, hist = self._snapshot(gw), self._historial(gw)
        prev, cuotas = self._precios_previos(gw), self._cuotas(gw)

        plantilla_ids = [p.element for p in state.squad.players] if state.squad else []
        plantilla = [f for e in plantilla_ids if (f := self._fila(e, snap, hist, prev, cuotas))]

        # mercado: candidatos del optimizador fuera de la plantilla, top-40 por forma
        fuera = [c.element for c in state.candidates if c.element not in set(plantilla_ids)]
        forma = sorted(fuera, key=lambda e: -sum(x["total_points"] for x in hist.get(e, [])))
        mercado = [f for e in forma[:40] if (f := self._fila(e, snap, hist, prev, cuotas))]

        chips_gastados = [f"{u.chip}@GW{u.gw}" for u in state.chips_used]
        doc = {
            "temporada": self.season, "gw": gw,
            "tu_plantilla": plantilla,
            "banco_M": round(state.bank, 1),
            "transferencias_libres": state.free_transfers,
            "chips_gastados": chips_gastados,
            "mercado_destacado": mercado,
        }
        cuerpo = json.dumps(doc, ensure_ascii=False, indent=1)
        return (memoria_texto + "\nBRIEFING:\n" + cuerpo) if memoria_texto else ("\nBRIEFING:\n" + cuerpo)
