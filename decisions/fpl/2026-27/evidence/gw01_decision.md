# Acta de decisión · FPL 2026-27 · Gameweek 1

**Emitida:** 2026-08-09T22:59:43+00:00  
**Deadline:** 2026-08-21T17:30:00Z  
**Política:** `milp` · horizonte 3  
**Modelos:** minutos `1.0.0` · puntos `1.0.0`  
**git sha:** `fc9b77e`  
**Fuente:** fantasy.premierleague.com/api (bootstrap-static + fixtures), solo GET


> ⚠️ **Emitida 11.8 días antes del cierre: esto es un borrador.** Los precios se mueven a diario, el parte médico cambia y las alineaciones probables aún no existen. Volver a correr dentro de las 24 horas previas al deadline y usar esa acta, no esta.

---

## Once inicial

| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |
|---|---|---|---:|---:|---:|---:|---|
| GKP | Jordan Pickford | Everton | £5.5 | 3.78 | ±2.4 | 91% | cs +1.5 · bon +0.2 |
| DEF | Gabriel dos Santos Magalhães | Arsenal | £8.0 | 3.76 | ±3.7 | 61% | gol +0.3 · asi +0.2 · cs +1.2 · def +0.4 · bon +0.5 |
| DEF | Nathan Collins | Brentford | £5.5 | 3.68 | ±3.0 | 84% | gol +0.3 · asi +0.2 · cs +1.1 · def +0.7 · bon +0.2 |
| DEF | Piero Hincapié | Arsenal | £5.5 | 3.61 | ±3.2 | 71% | asi +0.2 · cs +1.4 · def +0.4 · bon +0.2 |
| MID | Bruno Borges Fernandes **(C)** | Man Utd | £12.0 | 5.17 | ±3.7 | 86% | gol +1.1 · asi +1.2 · cs +0.2 · def +0.2 · bon +0.8 |
| MID | Dango Ouattara *(V)* | Brentford | £6.5 | 4.45 | ±3.6 | 83% | gol +1.4 · asi +0.7 · cs +0.3 · bon +0.3 |
| MID | Rayan Cherki | Man City | £7.5 | 4.34 | ±3.7 | 69% | gol +0.8 · asi +1.3 · cs +0.3 · bon +0.3 |
| MID | Morgan Gibbs-White | Nott'm Forest | £8.0 | 4.26 | ±3.5 | 78% | gol +1.6 · asi +0.4 · cs +0.3 · bon +0.3 |
| MID | Iliman Ndiaye | Everton | £6.0 | 4.16 | ±3.0 | 91% | gol +1.0 · asi +0.5 · cs +0.4 · def +0.3 · bon +0.2 |
| FWD | João Pedro Junqueira de Jesus | Chelsea | £7.5 | 4.38 | ±3.2 | 90% | gol +1.6 · asi +0.4 · bon +0.6 |
| FWD | Igor Thiago Nascimento Rodrigues | Brentford | £8.0 | 4.06 | ±3.8 | 73% | gol +2.0 · asi +0.3 · bon +0.4 |

## Banquillo

El orden importa: es la prioridad de las sustituciones automáticas.

| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |
|---|---|---|---:|---:|---:|---:|---|
| GKP | Bart Verbruggen | Brighton | £4.5 | 3.32 | ±2.3 | 90% | cs +1.2 |
| DEF | Malick Thiaw | Newcastle | £5.0 | 3.55 | ±3.1 | 86% | gol +0.6 · cs +0.8 · def +0.6 · bon +0.2 |
| DEF | Vitalii Mykolenko | Everton | £4.5 | 3.36 | ±2.6 | 87% | asi +0.2 · cs +1.4 · def +0.3 |
| FWD | Dominic Calvert-Lewin | Leeds | £6.0 | 3.32 | ±3.0 | 73% | gol +1.3 · asi +0.2 · bon +0.3 |

## Resumen

| | |
|---|---:|
| Coste de la plantilla | £100.0M |
| Banco | £0.0M |
| xP del once (con capitán) | 50.8 |
| Transferencias | 0 |
| Hits | −0 |
| Capitán | Bruno Borges Fernandes |
| Vicecapitán | Dango Ouattara |

## Chips

**Ninguno.** El planificador no corrio en esta jornada.

Ventana **H1** (GW1–19): quedan **19 jornadas** para usarla.
Sin gastar en esta ventana: `bench_boost`, `free_hit`, `triple_captain`, `wildcard`.

## Validación de reglas

`validate_squad` con las reglas 2026-27 devuelve **[]** — sin violaciones.

## Notas del motor

- shortlist 573/573 (100%) [DEF:187, FWD:69, GKP:64, MID:253] forzados=0
- horizonte [1, 2, 3] xp_total={1: 867.0, 2: 728.3, 3: 611.7}
- cold start: plantilla construida desde cero

---

Huella de la decisión: `8ca56955a9b8c3d5`  
Este documento se introduce **a mano** en la web de FPL. El motor no escribe contra la API (ADR-006).
