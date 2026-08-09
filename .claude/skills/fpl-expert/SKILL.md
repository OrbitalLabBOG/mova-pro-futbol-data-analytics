---
name: fpl-expert
description: Reglas de la Fantasy Premier League 2026/27 (incluida la contribución defensiva y la reforma del BPS), estimación de puntos esperados y optimización MILP. Usar al trabajar sobre el motor de decisión FPL de este repo.
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-09
---

# FPL Expert — reglas, xP y optimización

> ⚠️ **El código manda sobre este documento.** Las reglas vivas están en
> `mova_fpl/rules/season_2026_27.py` y se validaron reproduciendo el `total_points` real de
> **29.757 actuaciones** con 100% de exactitud. Si algo aquí contradice al código, el código
> tiene razón y este archivo está desactualizado. Arquitectura completa:
> [docs/21-motor-fpl-arquitectura.md](../../../docs/21-motor-fpl-arquitectura.md).

## 1. Puntuación 2026/27

Por jugador y partido:

| Concepto | Puntos |
|---|---|
| Aparición | +1 si 1 ≤ min < 60 · +2 si min ≥ 60 |
| Gol | GKP/DEF +6 · MID +5 · FWD +4 |
| Asistencia | +3 |
| Portería a cero (solo si min ≥ 60) | GKP/DEF +4 · MID +1 · FWD 0 |
| **Contribución defensiva (DefCon)** | **+2** al alcanzar el umbral |
| Paradas | `+floor(paradas / 3)` — solo GKP |
| Penalti atajado | +5 |
| Penalti fallado | −2 |
| Goles encajados | `−floor(encajados / 2)` — solo GKP/DEF |
| Amarilla · roja | −1 · −3 |
| Autogol | −2 |
| Bonus | +3, +2, +1 por el ranking BPS del partido |

**DefCon**, la regla que abre ventaja porque el mercado todavía no la valora bien:

| Posición | Umbral | Acciones que cuentan |
|---|---:|---|
| DEF | **10** | **CBIT** — despejes, bloqueos, intercepciones, entradas |
| MID / FWD | **12** | **CBIRT** — lo anterior + recuperaciones |
| GKP | — | No es elegible |

Se paga una sola vez por partido, no por cada acción sobre el umbral.

**Reforma del BPS.** La matriz de puntuación por acción de 2026/27 es idéntica a la de
2025/26; lo que cambió es el reparto del BPS (`rules/bps.py::BPS_2026_27`). Consecuencia
declarada como riesgo **R-04**: el componente de bonus queda sobreestimado para defensas y
porteros hasta que haya datos de la temporada nueva.

## 2. Plantilla, transferencias y chips

```python
budget = 100.0            # £, en décimas enteras dentro del optimizador
size = 15                 # GKP 2 · DEF 5 · MID 5 · FWD 3
max_per_club = 3
starters = 11             # mínimos 1-3-2-1 · máximos 1-5-5-3
max_free_transfers = 5    # se acumulan; wildcard y free hit NO las destruyen
hit_cost = 4              # por transferencia extra
captain_multiplier = 2    # 3 con triple captain
```

Chips: `wildcard`, `free_hit`, `bench_boost`, `triple_captain`. **La política de chips está
sin implementar** (Q-04): hoy la heurística es nula. Cualquier criterio de activación que se
lea por ahí es opinión, no evidencia del sistema.

## 3. Cómo se estima xP en este repo

No es una regresión al `total_points`. Es una suma de componentes, cada uno con su
distribución, calculada **por rama de minutos** y mezclada al final:

| Componente | Distribución |
|---|---|
| Goles, asistencias, goles encajados | Poisson |
| Conteo de acciones defensivas | Binomial negativa (sobredispersa) |
| Portería a cero | Bernoulli, `P = e^(−λ_encajados)` |
| Paradas, encajados → puntos | `E[floor(X/n)]` **exacto**, sumando la pmf |

Dos trampas que ya costaron caro:

- **Nunca proyectar sobre los minutos esperados.** Las reglas no son lineales en los minutos
  (la portería a cero solo paga desde el 60'). Hay que calcular en cada rama y mezclar.
- **Nunca dividir la media para un `floor`.** `E[floor(X/3)] ≠ E[X]/3`. Ese error valía +43,5%
  de sesgo en el componente de paradas.

Y una tercera, más sutil: ajustar una transformación convexa por partido y aplicarla a
promedios subestima (desigualdad de Jensen). Fue un sesgo de −44,8% en bonus.

## 4. El optimizador

MILP con PuLP/CBC sobre un horizonte rodante. Variables binarias por jugador y jornada:
plantilla, once, capitán, comprado, vendido.

Tres detalles que no son obvios:

- **El dinero es conservación, no un tope.** `bank[t] = bank[t-1] + ventas − compras`, en
  décimas enteras. Las ventas usan el `selling_price`, que no es el precio de mercado.
- **Las transferencias libres se linealizan**: `ft[t+1] ≤ libres − usadas + golpes[t] + 1`.
- **El arranque en frío necesita un caso aparte**: quince fichajes con la recursión normal dan
  `5 − 15 + 1 = −9` y el problema sale infactible.

Implementación: `mova_fpl/optimizer/milp.py`. No reimplementarlo en un script suelto.

## 5. Reglas de trabajo sobre este motor

1. **Todo dato entra por `Store.as_of(temporada, jornada)`.** No hay otra lectura pública. Si
   necesitas algo que no pasa por ahí, el diseño está mal, no el contrato.
2. **`Store.results()` es el oráculo.** Solo el simulador y el evaluador pueden llamarlo. Hay
   una prueba que lo verifica y otra que impide que la lista permitida crezca.
3. **El motor no escribe en FPL.** Un solo `GET` en todo el paquete. El acta la introduce una
   persona a mano.
4. **`pytest -q` antes de dar algo por terminado.** Y el backtest de 2025-26 con semilla 42
   debe seguir dando **2.217** puntos.
5. **No tocar `src/mova_model/fpl_*.py` ni `scripts/train_fpl_xp_v*.py`.** Es el motor
   anterior, con leakage, congelado como registro.
