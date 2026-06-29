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

## Snapshot del pronóstico (2026-06-29)

**Resultados 16vos hasta ahora: 2/2 aciertos** — Canadá 1-0 Sudáfrica ✓ · Brasil 2-1 Japón ✓.

**Top campeón:** Argentina 22.4% · France 20.8% · Spain 13.5% · England 9.3% · Brazil 6.7% · Portugal 4.9% · Netherlands 4.5% · Colombia 3.4%.

**Picks de polla:**
- Campeón seguro: **Argentina** (camino más blando + Elo #1).
- Campeón valor: **España** (leverage ~1.35, infravalorada por el público).
- Evitar: **Brasil** como campeón (sobre-elegido: público ~8% vs modelo 6.7%).
- Final más probable del modelo: **Argentina vs France**.

**16vos restantes — favoritos del modelo:** Germany, Netherlands, **Norway** (upset vs C.Marfil), France, Mexico, England, Belgium, USA, Spain, Portugal, Switzerland, **Egypt** (upset vs Australia), Argentina, Colombia.

## Qué es y qué NO es este pronóstico (honesto)

- **Es** un modelo calibrado ≈ mercado/Opta (el techo predictivo real en selección), condicionado a resultados/partidos en vivo, con capa de decisión de polla.
- **No es** un oráculo que le gane al mercado (el backtest mostró RPS ≈ casas; ver [docs/10](10-backtest-y-critica.md)). El edge para la polla está en **valor vs el público + camino de bracket + regresión**, no en out-predecir al mercado.
- Las features tácticas/ML al core se probaron y son **ruido** (no se usan para el ranking; sí para scouting).
