# Pronóstico y operación del modelo (en vivo)

> Snapshot **2026-06-29** (16vos en curso, 2/16 jugados). El modelo es **vivo**: este pronóstico se regenera con cada corrida conforme avanzan los partidos. No es final.

## Cómo regenerar (un comando)

```bash
python scripts/run_model.py --seed 42
```
Encadena: xG (reusa artefacto) → motor calibrado → features → predict → **simulate** (FT real > en vivo > mercado h2h > modelo, anclado a mercado) → insight + pick sheet.
Antes, refrescar datos si hay partidos nuevos: `python scripts/collect.py && python scripts/collect_context.py && python scripts/collect_odds.py`.

## Salidas (dónde leer el pronóstico)

| Salida | Qué contiene |
|---|---|
| tabla `tournament_sim` | P(R16/QF/SF/Final/Campeón) por equipo (la fuente de verdad) |
| `outputs/pick_sheet_latest.md` | **Picks de polla**: campeón (seguro + valor por leverage), ownership, quién avanza por ronda |
| `outputs/insight_latest.md` | Valor vs mercado, suerte/regresión (goles−xG), camino de bracket |
| `scripts/scout.py "A" "B"` | Scouting táctico de un cruce (eventos WC2026) |
| `scripts/bracket.py` | Bracket completo lleno (16vos→campeón); imagen en `outputs/bracket_modelo.png` |

> **Geometría del cuadro verificada** (2026-06-29): `simulate.BRACKET` corregido contra el template oficial (openfootball/FIFA, M73-M104) y validado con CBS — España/Argentina, Francia/Inglaterra, Portugal/Colombia en mitades opuestas. La estructura binaria del código requería el orden de slots correcto (mitad A = slots 0-7, mitad B = 8-15).

## Snapshot del pronóstico (2026-06-29)

**Resultados 16vos jugados: 2/3** — Canadá 1-0 Sudáfrica ✓ · Brasil 2-1 Japón ✓ · Alemania 1-1 Paraguay (pen 3-4) → **Paraguay** ✗ (upset, predijimos Alemania 79%).

**Top campeón:** Argentina ~22.8% · France ~22.0% · Spain ~13.8% · England ~9.5% · Brazil ~7%.

**Bracket del modelo (geometría oficial verificada) — `outputs/bracket_modelo.png`:**
- Mitad A: …→ Cuartos Francia / España → **Semifinal 1: Francia vs España** (Francia 54%).
- Mitad B: …→ Cuartos Inglaterra / Argentina → **Semifinal 2: Argentina vs Inglaterra** (Argentina 59%).
- **Final: Francia 51% vs 49% Argentina → 🏆 Francia.**
- ⚠️ España y Argentina están en **mitades opuestas** (solo se cruzan en la final) — confirmado vs cuadro oficial FIFA/openfootball + CBS.

**Picks de polla:**
- Campeón seguro: **Argentina** (camino más blando + Elo #1) — empatada con Francia (~22%).
- Campeón valor: **España** / **Francia** (menos sobre-elegidas que Argentina por el público).
- Evitar: **Brasil** como campeón (sobre-elegido).

## Qué es y qué NO es este pronóstico (honesto)

- **Es** un modelo calibrado ≈ mercado/Opta (el techo predictivo real en selección), condicionado a resultados/partidos en vivo, con capa de decisión de polla.
- **No es** un oráculo que le gane al mercado (el backtest mostró RPS ≈ casas; ver [docs/10](10-backtest-y-critica.md)). El edge para la polla está en **valor vs el público + camino de bracket + regresión**, no en out-predecir al mercado.
- Las features tácticas/ML al core se probaron y son **ruido** (no se usan para el ranking; sí para scouting).
