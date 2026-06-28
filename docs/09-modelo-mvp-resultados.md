# Modelo MVP — resultados y estado (E0–E4)

> Fase 2 MVP **completada** 2026-06-28. Pipeline re-ejecutable que produce P(avance/campeón). Pendiente de revisión antes de E5 (backtest) y refinamientos.

## Qué se construyó

Paquete `src/mova_model/` (estilo `mova_data`, funciones puras + idempotente):
`geometry · shots · xg_model · elo · strengths · match_model · market · blend · predict · simulate · pipeline`.
Orquestador: `scripts/run_model.py` → `xg → motor → features → predict → simulate`, registra en `model_runs`.

Datos previos: `intl_results` (49.477 partidos martj42) + Elo propio (`elo_computed`).

## Cómo correr (re-ejecutable con datos frescos)

```bash
python scripts/collect_elo_history.py   # una vez (histórico)
python scripts/train_xg.py              # una vez (artefacto models/xg/)
python scripts/fit_match_model.py       # una vez (models/dc/)
python scripts/run_model.py --seed 42   # cada vez que haya datos nuevos del collector
```
Idempotente y determinista (DP exacto): re-correr sin datos nuevos → resultado idéntico (verificado, dif=0.000000).

## Componentes y validación

| Componente | Resultado |
|---|---|
| xG propio (logística calibrada, StatsBomb→WhoScored) | Brier 0.082, AUC 0.787; sanity pie>cabeza>lejano, penal=0.79 |
| Motor Elo→Dixon-Coles | b0=0.193, b1=0.191, ρ=−0.045; dr=0→29% empate, dr=+300→71% favorito |
| Elo propio (martj42, 49K partidos) | Argentina 2227, Spain 2215, France 2191 |
| Bracket Monte Carlo / DP | DP exacto = MC (<0.2pp); Σ P(campeón)=1.000 |

## Salida estrella — P(campeón) (run 2026-06-28)

| Equipo | MODELO | Mercado | Opta |
|---|---|---|---|
| Argentina | **29.5%** | 19.5% | 16.3% |
| Spain | **22.8%** | 10.5% | 13.5% |
| France | 14.2% | 21.9% | 18.7% |
| England | 9.0% | 10.1% | 9.7% |
| Brazil | 4.4% | 5.8% | 6.5% |
| Colombia | 4.3% | 2.5% | — |

**Lectura:** el modelo (basado en xG) ve a **Spain y Argentina muy por encima** del mercado — dominaron en números subyacentes (Spain xGF 1.5 / xGA 0.15; Argentina 1.53 / 0.37) — y a **France por debajo** (ganó sus 3 pero con xG flojo 0.94 / 0.83). Es exactamente la señal diferencial xG que buscábamos.

## Limitaciones conocidas (a resolver en revisión / E5)

1. **Sobreconfianza vs mercado.** La simulación usa el modelo puro (Elo+forma xG); NO está anclada al mercado a nivel torneo (el blend con mercado solo aplica a los 15 partidos de R32 con odds). La evidencia (docs/08) dice anclar al mercado → **siguiente refinamiento clave**: blendear las probabilidades del torneo con el consenso de mercado (winner) y/o calibrar.
2. **xG WhoScored subestima ~30% agregado** (transferencia SB→WS). Solo afecta el ajuste de forma relativo (xGF−xGA), no el motor de goles (Elo calibrado en goles reales). Refinar con calibración por proveedor.
3. **R32 simulado desde cero** (incluido SA-Canada ya jugado 0-0, ganador no en datos). Al avanzar el torneo, congelar resultados reales.
4. **Sin backtest aún** (E5): falta validar RPS y skill vs mercado sobre WC2018/2022.

## Próximos pasos (post-revisión)

- **E5 backtest** walk-forward (WC2018/2022) → RPS, skill vs mercado, calibrar `w_blend`.
- **Anclar torneo al mercado** (blend champion/round con consenso winner).
- **Calibración xG por proveedor** (escala WhoScored).
- Capa de polla minimizada: ranking por `p_champion`/`p_group_adv` (ya disponible en `tournament_sim`).
