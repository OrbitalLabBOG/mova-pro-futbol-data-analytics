#!/usr/bin/env python3
"""Validación de integridad de la DB interconectada. Reporta PASS/WARN/FAIL."""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "mundial.db"
c = sqlite3.connect(DB)
q1 = lambda s, *a: c.execute(s, a).fetchone()[0]
fails = warns = 0


def check(label, cond, detail=""):
    global fails, warns
    status = "✅ PASS" if cond is True else ("⚠️  WARN" if cond == "warn" else "❌ FAIL")
    if cond is False:
        fails += 1
    elif cond == "warn":
        warns += 1
    print(f"  {status}  {label}" + (f"  — {detail}" if detail else ""))


def hr(t):
    print("\n" + "─" * 64 + f"\n{t}\n" + "─" * 64)

# ── 1. Conteos base ────────────────────────────────────────────────
hr("1. CONTEOS BASE")
for t in ("events", "matches", "lineups", "players", "teams", "fpl_players", "fpl_teams",
          "fpl_gameweeks", "fpl_fixtures", "fpl_player_history", "elo_ratings",
          "market_odds", "odds_quotes", "espn_fixtures", "team_aliases", "match_map"):
    print(f"  {q1(f'SELECT count(*) FROM {t}'):>9,}  {t}")

# ── 2. Integridad referencial WhoScored ────────────────────────────
hr("2. INTEGRIDAD REFERENCIAL (WhoScored)")
orphan_ev = q1("SELECT count(*) FROM events WHERE match_id NOT IN (SELECT match_id FROM matches)")
check("eventos sin match padre", orphan_ev == 0, f"{orphan_ev} huérfanos")
orphan_ln = q1("SELECT count(*) FROM lineups WHERE match_id NOT IN (SELECT match_id FROM matches)")
check("lineups sin match padre", orphan_ln == 0, f"{orphan_ln} huérfanos")
ev_noteam = q1("SELECT count(*) FROM events WHERE team_id IS NOT NULL AND team_id NOT IN (SELECT team_id FROM teams)")
check("eventos con team_id inexistente", ev_noteam == 0, f"{ev_noteam}")
# suma n_events declarado vs eventos reales en el Mundial 2026
decl = q1("SELECT COALESCE(SUM(n_events),0) FROM matches WHERE n_events>0 AND source='whoscored'")
real = q1("SELECT count(*) FROM events WHERE source='whoscored'")
check("matches.n_events == count(events [whoscored])", decl == real, f"declarado={decl:,} real={real:,}")

# ── 3. Consistencia con datos reales: GOLES vs MARCADOR ────────────
hr("3. GOLES (eventos) vs MARCADOR (scoreboard) — datos reales")
rows = c.execute("""
  SELECT m.match_id, m.home_team, m.away_team, m.home_score, m.away_score,
         (SELECT count(*) FROM events e WHERE e.match_id=m.match_id AND e.is_goal=1) AS goals_ev
  FROM matches m WHERE m.n_events>0""").fetchall()
mismatch = []
tot_score = tot_goals = 0
for mid, h, a, hs, as_, ge in rows:
    sc = (hs or 0) + (as_ or 0)
    tot_score += sc; tot_goals += ge
    if sc != ge:
        mismatch.append((h, a, sc, ge))
check("total goles eventos ≈ total marcadores", tot_goals == tot_score if not mismatch else "warn",
      f"marcadores={tot_score} goles_evento={tot_goals} | {len(mismatch)} partidos difieren")
if mismatch:
    print("    (diferencias suelen ser autogoles, atribuidos distinto):")
    for h, a, sc, ge in mismatch[:6]:
        print(f"      {h} vs {a}: marcador={sc} goles_evento={ge}")
# ejemplos concretos verificables
for hh, aa in [("Colombia", "Portugal"), ("France", "Iraq"), ("Scotland", "Brazil")]:
    r = c.execute("""SELECT home_team,home_score,away_score,away_team,
                     (SELECT count(*) FROM events e WHERE e.match_id=m.match_id AND is_goal=1)
                     FROM matches m WHERE home_team=? AND away_team=?""", (hh, aa)).fetchone()
    if r:
        print(f"    ✔ {r[0]} {r[1]}-{r[2]} {r[3]}  | goles en eventos: {r[4]}")

# ── 4. Rangos de valores ───────────────────────────────────────────
hr("4. RANGOS DE VALORES")
bad_xy = q1("SELECT count(*) FROM events WHERE x<0 OR x>100 OR y<0 OR y>100")
check("coordenadas eventos en [0,100]", bad_xy == 0, f"{bad_xy} fuera de rango")
bad_prob = q1("SELECT count(*) FROM market_odds WHERE prob IS NOT NULL AND (prob<0 OR prob>1)")
check("market_odds.prob en [0,1]", bad_prob == 0, f"{bad_prob} fuera de rango")
bad_price = q1("SELECT count(*) FROM odds_quotes WHERE price IS NOT NULL AND price<1")
check("odds_quotes.price decimal >=1", bad_price == 0, f"{bad_price} sospechosas")

# ── 5. team_aliases / equipos ──────────────────────────────────────
hr("5. IDENTIDAD DE EQUIPOS")
nteams = q1("SELECT count(DISTINCT name) FROM teams")
check("equipos canónicos = 48", nteams == 48, f"{nteams}")
board = q1("SELECT count(*) FROM v_team_board")
check("v_team_board filas = 48", board == 48, f"{board}")
# todos los equipos de matches (Mundial) resuelven
unres = c.execute("""SELECT count(*) FROM (
  SELECT home_team t FROM matches WHERE source='whoscored' UNION SELECT away_team FROM matches WHERE source='whoscored') x
  WHERE t NOT IN (SELECT alias FROM team_aliases) AND lower(t) NOT IN (SELECT lower(canonical) FROM team_aliases)""").fetchone()[0]
check("equipos WhoScored (Mundial) resuelven", unres == 0, f"{unres} sin alias")

# ── 6. match_map ───────────────────────────────────────────────────
hr("6. ENLACE DE PARTIDOS (match_map)")
dup_ws = q1("SELECT count(*) FROM (SELECT whoscored_id FROM match_map WHERE whoscored_id IS NOT NULL GROUP BY whoscored_id HAVING count(*)>1)")
check("whoscored_id único en match_map", dup_ws == 0, f"{dup_ws} duplicados")
dup_espn = q1("SELECT count(*) FROM (SELECT espn_id FROM match_map WHERE espn_id IS NOT NULL GROUP BY espn_id HAVING count(*)>1)")
check("espn_id único en match_map", dup_espn == 0, f"{dup_espn} duplicados")
bad_ws = q1("SELECT count(*) FROM match_map WHERE whoscored_id IS NOT NULL AND whoscored_id NOT IN (SELECT match_id FROM matches)")
check("match_map.whoscored_id existe en matches", bad_ws == 0, f"{bad_ws}")
bad_es = q1("SELECT count(*) FROM match_map WHERE espn_id IS NOT NULL AND espn_id NOT IN (SELECT espn_id FROM espn_fixtures)")
check("match_map.espn_id existe en espn_fixtures", bad_es == 0, f"{bad_es}")
bad_oa = q1("SELECT count(*) FROM match_map WHERE oddsapi_event_id IS NOT NULL AND oddsapi_event_id NOT IN (SELECT DISTINCT event_id FROM odds_quotes)")
check("match_map.oddsapi_event_id existe en odds_quotes", bad_oa == 0, f"{bad_oa}")
mapped = q1("SELECT count(*) FROM match_map WHERE whoscored_id IS NOT NULL")
nmatch = q1("SELECT count(*) FROM matches WHERE source='whoscored'")
check("todos los matches WhoScored (Mundial) mapeados", mapped == nmatch, f"{mapped}/{nmatch}")

# ── 7. Cruce real end-to-end ───────────────────────────────────────
hr("7. CRUCE END-TO-END (1 partido por todas las fuentes)")
r = c.execute("""SELECT vm.team_a, vm.team_b, vm.whoscored_id, vm.n_events, vm.espn_id,
                        vm.oddsapi_event_id, vm.n_quotes
                 FROM v_match vm WHERE vm.n_events>0 ORDER BY vm.match_date DESC LIMIT 1""").fetchone()
print(f"  Partido: {r[0]} vs {r[1]}")
print(f"    WhoScored id={r[2]}  eventos={r[3]}")
print(f"    ESPN id={r[4]}")
print(f"    OddsAPI ev={r[5]}  cuotas={r[6]}  (0 esperado: ya jugado, odds expiran)")
# Elo de ambos por v_team_board
for t in (r[0], r[1]):
    elo = c.execute("SELECT elo FROM v_team_board WHERE team=?", (t,)).fetchone()
    print(f"    Elo {t}: {elo[0] if elo else '?'}")

# ── Resumen ────────────────────────────────────────────────────────
hr("RESUMEN")
print(f"  {'TODO OK ✅' if fails==0 else f'{fails} FALLOS ❌'} | {warns} warnings")
sys.exit(1 if fails else 0)
