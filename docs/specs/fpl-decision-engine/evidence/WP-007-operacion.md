# WP-007 · Evidencia — operación de la GW1 de 2026/27

**Fecha:** 2026-08-09 · **Rama:** `feat/fpl-agent-clean` · **git sha:** `a1bc287`

```bash
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0
```

## AC-WP007-001 — el acta existe, con timestamp anterior al deadline

| | |
|---|---|
| Acta | `outputs/fpl/2026-27/gw01_decision.md` (copia en `evidence/WP-007-acta-gw01.md`) |
| Emitida | `2026-08-09T20:35:02Z` |
| Deadline | `2026-08-21T17:30:00Z` |
| Margen | **11,9 días** |

El acta **se marca sola como borrador**. Once días antes del cierre los precios se mueven a
diario, el parte médico cambia y las alineaciones probables no existen todavía. El propio
documento lleva el aviso y el runbook fija cuándo se emite la que cuenta: dentro de las 24
horas previas.

Lo que este acta demuestra no es qué equipo poner el 21 de agosto, sino que **el ciclo
completo funciona de punta a punta contra datos reales de 2026/27**.

## AC-WP007-002 — la plantilla es válida

`validate_squad` con las reglas de 2026/27 devuelve **`[]`**.

Composición verificada: 2 GKP · 5 DEF · 5 MID · 3 FWD · £100,0M exactos · máximo 3 por club
(Brentford llega al tope) · XI 1-3-5-2 · capitán y vicecapitán titulares y distintos.

## AC-WP007-003 — xP desglosado y procedencia

Cada uno de los quince jugadores aparece con su xP, su desviación estándar, su P(60') y el
desglose por componente. Ejemplo de la primera fila del once:

```
| MID | Bruno Borges Fernandes (C) | Man Utd | £12.0 | 5.17 | ±3.7 | 86%
| gol +1.1 · asi +1.2 · cs +0.2 · def +0.2 · bon +0.8 |
```

La decisión es discutible porque es legible. El acta también trae versión de cada modelo
(`minutos 1.0.0`, `puntos 1.0.0`), git sha `a1bc287`, la fuente exacta de los datos y la
huella de la decisión `8ca56955a9b8c3d5`.

## AC-WP007-004 — el ciclo tarda menos de diez minutos

```
real    0m5.571s
```

**5,6 segundos** contra un requisito de 600. Desglose: descarga del estado público,
proyección de 573 jugadores por componentes, optimización MILP con horizonte 3 **sin recorte
de mercado** —los 573 candidatos entran al modelo, optimalidad garantizada— y composición
del acta.

## AC-WP007-005 — solo GET contra fantasy.premierleague.com

`pytest tests/test_readonly_http.py` verde, sobre los 30 módulos del paquete:

| Prueba | Qué impide |
|---|---|
| `test_sin_verbos_de_escritura_declarados` | Un `method="POST"` en cualquier módulo |
| `test_sin_llamadas_http_de_escritura` | `requests.post`, `httpx.put`, `session.delete`… |
| `test_la_unica_primitiva_de_red_es_get` | Que exista más de un `urlopen` en el paquete |
| `test_ninguna_url_de_escritura_a_fpl` | Referencias a `/api/my-team`, `/api/transfers`, `login` |

No es una promesa de no escribir: **no existe código capaz de hacerlo**. Un bug no puede
gastar una transferencia real.

El módulo nuevo `data/live.py` no toca la red: consume `fetch_bootstrap()` y
`fetch_fixtures()` de `sources.py`, que sigue siendo el único punto de salida.

## AC-WP007-006 — la decisión quedó en la traza como `committed`

```
              run_id  season policy  horizon
2026-27-live-milp-h3 2026-27   milp        3

 gw     state      fingerprint  captain  hits  expected_points  total_cost
  1 committed 8ca56955a9b8c3d5      426     0            50.83           100.0
```

La corrida queda en `running` a propósito: la jornada no se ha jugado y no hay resultado con
el que reconciliar. Se cerrará cuando se puntúe.

## AC-WP007-007 — runbook

`docs/runbook-fpl.md`. Cubre cómo re-correr una jornada, cuándo hacerlo, cómo reentrenar,
qué hacer si la API no responde, cómo leer un `Infeasible`, qué significa un acta marcada
como inválida, qué horizonte usar y por qué, y qué falta para operar desde la GW2.

## Lo que este acta usa y el backtest no

Una diferencia que hay que declarar: `bootstrap-static` trae el **parte médico**
—`status` y `chance_of_playing_next_round`— y el histórico no lo conserva por jornada. La
decisión en vivo descuenta la probabilidad de jugar de los 58 jugadores con lesión, duda o
sanción; el backtest no puede hacerlo.

Es información legítimamente pre-deadline: cualquier manager la ve antes de decidir. Pero es
una señal **que las cifras del harness no incluyen**, así que el 2.217 medido en 2025/26 no
es exactamente el sistema que va a operar. La dirección del sesgo es favorable —alinear
lesionados solo puede restar— pero su tamaño no está medido.

## Estado de la plantilla propuesta

| | |
|---|---|
| Coste | £100,0M · banco £0,0M |
| xP del once con capitán | 50,8 |
| Capitán | Bruno Fernandes (5,17 xP, 86% de jugar 60') |
| Vicecapitán | Dango Ouattara |
| Jugadores con el parte tocado | 0 en la plantilla, de 58 en el mercado |
| Concentración | Brentford 3 (tope), resto ≤ 2 |
