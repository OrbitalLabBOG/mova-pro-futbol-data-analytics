---
title: Laboratorio causal de estrategia FPL de largo horizonte
status: experimental
owner: MOVA Fantasy
experiment_id: EXP-MOVA-2026-001
updated: 2026-09-03
---

# Long-horizon uncertainty lab

Este laboratorio busca maximizar puntos esperados de temporada, no acertar un
partido aislado. Vive en una rama/worktree independiente y no publica artefactos
ni modifica la selección activa del runtime.

## Contrato experimental

- **Control:** algoritmo vigente, reentrenado causalmente por fold, estado solo
  de la temporada objetivo, horizonte 3 y repetición del xP del rival actual.
- **Desarrollo:** 2021-22, 2023-24 y 2024-25. Se excluye 2022-23 porque
  incluyó transferencias ilimitadas entre GW16 y GW17 por el Mundial, transición
  que este simulador aún no representa.
- **Holdout sellado:** 2025-26, que solo se abre después de congelar el candidato.
- **North star:** `PVA-38`, diferencia pareada de puntos reales de temporada
  contra el control sobre los mismos partidos.
- **Incertidumbre:** CRPS, coberturas 50/80/90%, bootstrap pareado por bloques y
  penalización de transferencias sustentadas por alta desviación predictiva.
- **Eventos:** `threat` y `creativity` históricos como proxies jugador-partido.
  Los eventos WhoScored solo cubren parte de 2025-26 y permanecen como ablation
  secundaria; no pueden justificar promoción multitemporada.
- **Promoción:** prohibida en este experimento. Primero se socializa el holdout y
  se requiere autorización explícita.

Cada fold entrena minutos y puntos únicamente con temporadas anteriores al
objetivo. La última temporada pasada calibra minutos y no entra al clasificador
base. En replay, `multi_season_as_of` conserva estado de jugadores entre
temporadas sin mezclar ninguna fila del futuro.

## Ablaciones

| Variante | Estado | Calendario | Horizonte | Eventos | Estabilidad |
|---|---|---|---:|---|---|
| `control_h3` | temporada | rival actual repetido | 3, decay .84 | no | no |
| `state_h3` | multitemporada | rival actual repetido | 3, decay .84 | no | no |
| `state_recency_h3` | multitemporada con recencia | rival actual repetido | 3, decay .84 | no | no |
| `fixture_h3` | multitemporada | por fixture | 3, decay .84 | no | no |
| `fixture_h6` | multitemporada | por fixture | 6, decay .84 | no | no |
| `fixture_h6_nodiscount` | multitemporada | por fixture | 6, sin descuento | no | no |
| `long_h6` | multitemporada | por fixture | 6, sin descuento | sí | no |
| `long_h6_stable` | multitemporada | por fixture | 6, sin descuento | sí | sí |

La secuencia evita atribuir a “IA” una mejora que en realidad venga de corregir
el cold start o de mirar el rival correcto.

## Ejecución

```bash
python -m experiments.long_horizon.run manifest --fpl-db /ruta/fpl_canonical.db
python -m experiments.long_horizon.run screen-events --fpl-db /ruta/fpl_canonical.db
python -m experiments.long_horizon.run select-policy --fpl-db /ruta/fpl_canonical.db
python -m experiments.long_horizon.run holdout --fpl-db /ruta/fpl_canonical.db
```

La evidencia generada queda fuera del repo, en el directorio hermano
`../mova-fpl-experiments/EXP-MOVA-2026-001/`:
manifest con hashes, artefactos por fold, predicciones, trazas, puntos por GW,
bootstrap y acta del holdout.

## Límites conocidos

1. El calendario histórico conoce la asignación final de aplazamientos (`L-01`).
2. La CRPS Normal aproxima una distribución discreta e inflada en cero.
3. En dobles jornadas se suman varianzas condicionales; falta modelar la
   correlación compartida de disponibilidad.
4. Solo cuatro temporadas modernas tienen club y posición completos para un
   replay de política comparable.

Estas limitaciones son gates de interpretación, no permisos para ajustar sobre
el holdout.
