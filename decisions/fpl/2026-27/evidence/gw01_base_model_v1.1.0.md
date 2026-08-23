# Acta de decisión · FPL 2026-27 · Gameweek 1

**Emitida:** 2026-08-20T13:05:16+00:00
**Deadline:** 2026-08-21T17:30:00Z
**Política:** `milp` · horizonte 3
**Modelos:** minutos `1.1.0` · puntos `1.1.0`
**git sha:** `31a7aaa`
**Fuente:** fantasy.premierleague.com/api (bootstrap-static + fixtures) · snapshot data/raw/fpl_live/2026-27/gw01/20260820T130408Z, solo GET

---

## Once inicial

| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |
|---|---|---|---:|---:|---:|---:|---|
| GKP | Jordan Pickford | Everton | £5.5 | 3.81 | ±2.4 | 92% | cs +1.5 · bon +0.2 |
| DEF | James Tarkowski *(V)* | Everton | £6.0 | 4.47 | ±3.0 | 90% | gol +0.3 · asi +0.2 · cs +1.4 · def +0.8 · bon +0.3 |
| DEF | Gabriel dos Santos Magalhães | Arsenal | £8.0 | 4.46 | ±3.7 | 73% | gol +0.4 · asi +0.2 · cs +1.5 · def +0.5 · bon +0.5 |
| DEF | Nathan Collins | Brentford | £5.5 | 4.04 | ±2.9 | 93% | gol +0.3 · asi +0.2 · cs +1.3 · def +0.8 · bon +0.2 |
| MID | Morgan Gibbs-White **(C)** | Nott'm Forest | £8.0 | 4.50 | ±3.5 | 88% | gol +1.6 · asi +0.4 · cs +0.3 · bon +0.4 |
| MID | Dango Ouattara | Brentford | £6.5 | 4.35 | ±3.6 | 81% | gol +1.3 · asi +0.7 · cs +0.3 · bon +0.3 |
| MID | Kiernan Dewsbury-Hall | Everton | £6.5 | 4.21 | ±3.0 | 91% | gol +0.9 · asi +0.7 · cs +0.4 · def +0.2 · bon +0.4 |
| MID | Enzo Fernández | Chelsea | £7.0 | 4.10 | ±3.1 | 90% | gol +1.1 · asi +0.6 · cs +0.2 · bon +0.4 |
| MID | Rayan Cherki | Man City | £7.5 | 4.10 | ±3.6 | 64% | gol +0.8 · asi +1.2 · cs +0.3 · bon +0.3 |
| FWD | Igor Thiago Nascimento Rodrigues | Brentford | £8.0 | 4.13 | ±3.7 | 73% | gol +2.0 · asi +0.3 · bon +0.4 |
| FWD | João Pedro Junqueira de Jesus | Chelsea | £7.5 | 4.12 | ±3.2 | 86% | gol +1.5 · asi +0.4 · bon +0.6 |

## Banquillo

El orden importa: es la prioridad de las sustituciones automáticas.

| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |
|---|---|---|---:|---:|---:|---:|---|
| GKP | David Raya Martín | Arsenal | £6.0 | 3.26 | ±2.7 | 74% | cs +1.5 · bon +0.2 |
| FWD | Dominic Calvert-Lewin | Leeds | £6.0 | 3.83 | ±3.0 | 89% | gol +1.5 · asi +0.2 · bon +0.4 |
| DEF | Neco Williams | Nott'm Forest | £5.0 | 3.79 | ±3.0 | 90% | gol +0.3 · asi +0.4 · cs +1.2 · def +0.3 · bon +0.3 |
| DEF | Malick Thiaw | Newcastle | £5.0 | 3.69 | ±3.1 | 90% | gol +0.6 · cs +0.8 · def +0.6 · bon +0.3 |

## Resumen

| | |
|---|---:|
| Coste de la plantilla | £98.0M |
| Banco | £2.0M |
| xP del once (con capitán) | 50.8 |
| Transferencias | 0 |
| Hits | −0 |
| Capitán | Morgan Gibbs-White |
| Vicecapitán | James Tarkowski |

## Validación de reglas

`validate_squad` con las reglas 2026-27 devuelve **[]** — sin violaciones.

## Notas del motor

- shortlist 595/595 (100%) [DEF:196, FWD:71, GKP:66, MID:262] forzados=0
- horizonte [1, 2, 3] xp_total={1: 849.3, 2: 713.4, 3: 599.3}
- cold start: plantilla construida desde cero

---

Huella de la decisión: `5861fea0ff28ae86`
Este documento se introduce **a mano** en la web de FPL. El motor no escribe contra la API (ADR-006).
