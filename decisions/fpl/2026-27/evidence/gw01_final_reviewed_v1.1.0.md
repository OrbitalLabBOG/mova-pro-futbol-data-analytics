# Acta de decisión · FPL 2026-27 · Gameweek 1

**Emitida:** 2026-08-20T13:28:12+00:00
**Deadline:** 2026-08-21T17:30:00Z
**Política:** `human-reviewed` · horizonte 3
**Modelos:** minutos `1.1.0` · puntos `1.1.0`
**git sha:** `edd7e07`
**Fuente:** snapshot sellado data/raw/fpl_live/2026-27/gw01/20260820T132423Z · manifest 2026-08-20T13:24:23+00:00 · spec decisions/fpl/2026-27/gw01_final.json; solo lectura

---

## Once inicial

| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |
|---|---|---|---:|---:|---:|---:|---|
| GKP | Bart Verbruggen | Brighton | £4.5 | 2.81 | ±2.4 | 76% | cs +1.0 |
| DEF | Riccardo Calafiori | Arsenal | £5.5 | 2.89 | ±3.2 | 56% | gol +0.4 · cs +1.1 |
| DEF | Harry Maguire | Man Utd | £5.0 | 2.47 | ±2.6 | 72% | gol +0.2 · cs +0.7 · def +0.4 |
| DEF | Cristhian Mosquera | Arsenal | £5.5 | 2.27 | ±2.8 | 47% | cs +1.0 · def +0.3 |
| MID | Pascal Groß | Brighton | £5.5 | 3.86 | ±2.6 | 93% | gol +0.4 · asi +0.8 · cs +0.3 · def +0.2 · bon +0.4 |
| MID | Bryan Mbeumo | Man Utd | £8.0 | 3.69 | ±3.2 | 74% | gol +1.2 · asi +0.4 · cs +0.2 · bon +0.3 |
| MID | Bruno Borges Fernandes *(V)* | Man Utd | £12.0 | 3.52 | ±3.7 | 54% | gol +0.7 · asi +0.8 · bon +0.6 |
| MID | Christos Tzolis | Arsenal | £6.5 | 2.19 | ±2.5 | 45% | gol +0.3 · asi +0.3 · cs +0.2 · bon +0.2 |
| FWD | João Pedro Junqueira de Jesus | Chelsea | £7.5 | 4.12 | ±3.2 | 86% | gol +1.5 · asi +0.4 · bon +0.6 |
| FWD | Dominic Calvert-Lewin | Leeds | £6.0 | 3.83 | ±3.0 | 89% | gol +1.5 · asi +0.2 · bon +0.4 |
| FWD | Erling Haaland **(C)** | Man City | £15.5 | 3.43 | ±4.4 | 50% | gol +1.6 · asi +0.3 · bon +0.5 |

## Banquillo

El orden importa: es la prioridad de las sustituciones automáticas.

| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |
|---|---|---|---:|---:|---:|---:|---|
| GKP | Antonín Kinský | Spurs | £4.5 | 1.80 | ±1.9 | 72% | cs +0.5 |
| MID | Mamadou Sangaré | Brentford | £5.5 | 2.07 | ±2.5 | 43% | gol +0.4 · asi +0.3 |
| DEF | Joe Rodon | Leeds | £4.5 | 2.99 | ±2.5 | 89% | gol +0.2 · cs +0.8 · def +0.5 |
| DEF | Bobby Thomas | Coventry City | £4.0 | 0.74 | ±1.6 | 29% | cs +0.2 |

## Resumen

| | |
|---|---:|
| Coste de la plantilla | £100.0M |
| Banco | £0.0M |
| xP del once (con capitán) | 38.5 |
| Transferencias | 0 |
| Hits | −0 |
| Capitán | Erling Haaland |
| Vicecapitán | Bruno Borges Fernandes |

## Validación de reglas

`validate_squad` con las reglas 2026-27 devuelve **[]** — sin violaciones.

## Montaje y cierre operativo

- **Cuenta:** `losmillosFPL` · entry `3609854`.
- **Guardado confirmado:** 2026-08-20T15:20:28-05:00.
- **Respuesta de FPL:** `Equipo guardado`.
- **Revalidación:** recarga completa posterior al guardado; persistieron XI, formación
  3-4-3, capitán, vicecapitán y orden de banca.
- **Presupuesto mostrado por FPL:** £100.0m · £0.0m en banco.
- **Chips:** ninguno activado.
- **Evidencia visual archivada:** tag `archive/pre-harness-cleanup-2026-08-23`, ruta
  `outputs/fpl/2026-27/gw01_final_mounted.png`.
- **SHA-256 evidencia:**
  `8573409eca1815bfa051157be9828f1017d0f1ea8dd9bc8aedc95b8e13becf6c`.

## Notas del motor

- Intervencion humana deliberada sobre la base MILP: el modelo no observa pretemporada, roles nuevos ni ruedas de prensa.
- Nucleo de control de riesgo: Haaland, Bruno Fernandes, Mbeumo y Joao Pedro; capitan Haaland y vice Bruno Fernandes.
- Triple Arsenal y triple Manchester United atacan rivales ascendidos en GW1; la banca permite cubrir el deterioro del calendario de Arsenal en GW2-GW3.
- Calafiori y Mosquera sustituyen al costoso Gabriel para financiar a Calvert-Lewin y dos porteros titulares rotables.
- Sin chip en GW1: se preservan Wildcard, Free Hit, Bench Boost y Triple Captain de la primera ventana.
- La decision debe revalidarse contra un snapshot fresco y noticias de ultima hora antes del deadline; cualquier cambio exige nueva spec y nueva huella.

---

Huella de la decisión: `5e39cc0f12c84566`
La decisión fue introducida **a mano** y revalidada visualmente en la web de FPL.
El motor no escribe contra la API (ADR-006).
