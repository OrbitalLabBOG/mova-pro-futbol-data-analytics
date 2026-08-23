---
title: "FPL 2026/27 GW1 — investigación, modelo y decisión inicial"
date: 2026-08-20
status: mounted-and-verified
owner: MOVA Fantasy Fútbol Data Analytics
season: 2026-27
gameweek: 1
---

# FPL 2026/27 GW1 — investigación, modelo y decisión inicial

## Veredicto

La plantilla de arranque es una **intervención humana documentada** sobre la salida MILP,
no una sustitución silenciosa del modelo. El optimizador es útil como control estructural,
pero para una GW1 posterior al Mundial subestima incorporaciones, cambios de rol y jugadores
con poca pretemporada. La decisión final combina el núcleo de menor riesgo del Scout oficial
con la profundidad de la plantilla consensuada por su panel de expertos.

**Formación GW1: 3-4-3 · £100.0m · banco £0.0m · sin chip.**

- **XI:** Verbruggen; Calafiori, Mosquera, Maguire; Bruno Fernandes, Mbeumo, Tzolis,
  Groß; Haaland **(C)**, João Pedro, Calvert-Lewin.
- **Banca:** Kinský; Sangaré (1), Rodon (2), Bobby Thomas (3).
- **Vicecapitán:** Bruno Fernandes.
- **Huella canónica:** se genera desde
  `decisions/fpl/2026-27/gw01_final.json`; no debe editarse el acta a mano.

## Estado de datos y modelos

La ingesta histórica fue reconstruida de forma atómica el 20 de agosto:
**253.890 actuaciones, 10 temporadas, 2016/17–2025/26**. La última temporada aporta
29.747 filas; diez duplicados exactos se descartaron de forma idempotente.

El snapshot oficial final de esta revisión, sellado a las `2026-08-20T13:24:23Z`, contiene:

| Control | Resultado |
|---|---:|
| Jugadores / clubes | 595 / 20 |
| Fixtures | 380; 10 en GW1 |
| Deadline | 2026-08-21 17:30 UTC / 12:30 Bogotá |
| Disponibilidad afectada | 115; 87 con factor cero |
| SHA-256 bootstrap | `3942e9fd54f63b21eececd8d3fc2857a680ffe8412427b8a743c70b10b6ebc8e` |
| SHA-256 fixtures | `18745575078b4bbf1c3a1c85862945e8d5ff15825130c68b4d11124e2c7bbc54` |

Los artefactos productivos `minutes-1.1.0` y `points-1.1.0` incorporan ya 2025/26.
El primero conserva 2025/26 como calibración temporal; el segundo se ajusta con las diez
temporadas e incorpora por primera vez una temporada completa de contribuciones defensivas.
Sus hashes están en los metadatos versionados.

Hay **457 de 595 jugadores enlazados** con su identidad de 2025/26 y 138 sin histórico
directo, principalmente ascendidos y fichajes. Para estos últimos el motor aplica priors
conservadores por posición. Es una protección razonable, pero explica por qué sus xP y P(60)
no deben interpretarse como si el modelo hubiese observado su club, rol y pretemporada actual.

## Lo que dijo el modelo

La base MILP era válida y reproducible: 50,8 xP, £98.0m, banco £2.0m, huella
`5861fea0ff28ae86`. Proponía capitanear a Gibbs-White y dejaba fuera a Haaland y Bruno.
Eso es coherente con las señales que sí ve —histórico causal, precio, rival y minutos—,
pero no con el riesgo de capitán ni con la nueva información de agosto.

| Plantilla comparada | Coste | xP del XI con capitán | Lectura |
|---|---:|---:|---|
| MILP puro | £98.0m | 50,8 | Mayor xP interno; estructura y capitán frágiles ante señales nuevas |
| Scout oficial actualizado | £100.0m | 38,4 | Máximo ataque a GW1; banca deliberadamente débil |
| Panel oficial “ultimate” | £100.0m | 41,6 | Mejor profundidad y rotación; menos exposición a Arsenal-Coventry |
| **Híbrido revisado** | **£100.0m** | **38,5** | Núcleo seguro, upside GW1 y quince jugadores utilizables |

Los xP solo comparan lo que el modelo conoce. No incluyen explícitamente los siete goles de
pretemporada de João Pedro, el nuevo rol de nueve de Mbeumo ni las seis asistencias de Tzolis.
Por eso se conservan como evidencia y control, no como una orden ciega.

## Evidencia externa contrastada

Las fuentes de mayor peso fueron artículos oficiales de Premier League publicados o
actualizados entre el 14 y el 19 de agosto:

- El Scout declara como cuatro piezas esenciales a **Haaland, Bruno, Gabriel y João Pedro**.
  Haaland ha liderado la puntuación tras seis jornadas en sus cuatro temporadas de City;
  Bruno produjo 129 puntos en 17 partidos con Carrick; João Pedro llegó como máximo goleador
  de la pretemporada. [Must-haves oficiales](https://www.premierleague.com/en/news/4681709/the-scouts-must-haves-for-start-of-202627-fpl).
- La selección final del Scout añade **Mbeumo, Maguire, Mosquera, Tzolis, Groß, Sangaré y
  Kinský**. United abre ante Hull e Ipswich; Arsenal recibe a Coventry; Mbeumo actuó de nueve
  y sumó tres goles más una asistencia en sus tres últimas titularidades de verano.
  [Scout Selection](https://www.premierleague.com/en/news/4681112/scout-selection-the-best-fantasy-squad-for-202627).
- El panel oficial prefiere dos porteros rotables, **Kinský y Verbruggen**, y respalda a
  Calafiori, Maguire, Rodon, Bobby Thomas, Groß, Sangaré y Calvert-Lewin.
  [Ultimate squad](https://www.premierleague.com/en/news/4688908/fpl-experts-ultimate-squad-for-opening-gameweeks).
- En sus diez preguntas finales, los expertos consideran a Bruno el atacante seguro de
  United, prefieren Mbeumo como segundo activo, confirman la rotación Kinský-Verbruggen y
  destacan los minutos, penaltis y calendario de Calvert-Lewin.
  [Preguntas clave](https://www.premierleague.com/en/news/4688971/experts-answer-10-key-fpl-questions).
- La revisión club por club confirma a Mosquera como beneficiario de la lesión de Saliba,
  a Tzolis como probable titular, a Groß en penaltis, a João Pedro con siete goles en la
  pretemporada, a Calvert-Lewin con tres goles y dos asistencias, y a Kinský como número uno
  confirmado de Spurs. [Lecciones de pretemporada](https://www.premierleague.com/en/news/4681482/fpl-202627-pre-season-lessons-for-every-club).
- La señal no depende solo de la fuente oficial: una muestra de 11 élites con 81 acabados
  top-10k tenía 100% de Haaland y 76,9% de Bruno; su consenso también favorecía a João Pedro,
  Mosquera y los atacantes de precio medio.
  [Fantasy Football Fix](https://www.fantasyfootballfix.com/blog-index/fpl-expert-team-reveals-2026-27/).

## Por qué este híbrido

Se parte del Scout oficial y se hacen cuatro cambios presupuestariamente neutros:

| Sale del Scout | Entra | Delta | Motivo |
|---|---|---:|---|
| Dúbravka | Verbruggen | +£0.5m | Segundo portero titular y rotación real |
| Gabriel | Calafiori | −£2.5m | Mantener defensa Arsenal sin pagar precio premium |
| Greaves | Rodon | +£0.5m | Más minutos modelados y calendario rotacional |
| Kusi-Asare | Calvert-Lewin | +£1.5m | Delantero titular, penaltis y cinco fixtures FDR ≤3 |

El resultado conserva triple Arsenal y triple United para enfrentar ascendidos en GW1,
pero permite sentar dos activos de Arsenal cuando visiten Villa en GW2 y reciban a Chelsea
en GW3. No se usa Bench Boost: la banca es cobertura y rotación, no una apuesta de chip.

## Riesgos y condiciones de invalidez

1. **Calafiori/Mosquera:** el doblete defensivo maximiza GW1, pero hay riesgo de minutos.
   Una baja o una señal clara de suplencia invalida la estructura; White es la alternativa
   directa de £5.5m.
2. **Mbeumo/Bruno:** Bruno tuvo pretemporada corta y Mbeumo fue suplente en el último amistoso,
   aunque el contexto publicado favorece a ambos. Una rueda de prensa adversa exige reabrir.
3. **Haaland:** el modelo castiga su corta pretemporada; la capitanía se sostiene por su
   historial temprano, propiedad de 69,4%, localía ante Bournemouth y valor defensivo de
   cubrir al capitán más probable.
4. **£0.0m en banco:** reduce flexibilidad de precio, pero los precios quedan bloqueados hasta
   el deadline de GW1. Desde GW2 debe vigilarse el predictor oficial de cambios.
5. **Snapshot:** cualquier cambio de estado, precio, fixture o deadline obliga a recolectar
   otra captura, volver a emitir el acta y comparar su huella antes de tocar la web.

## Criterio de cierre

La decisión solo queda operativamente cerrada cuando se cumplen las cuatro condiciones:

- snapshot fresco y hashes válidos;
- `validate_squad == []`, £100.0m y 2/5/5/3 por posición;
- acta, spec y pantalla FPL coinciden en los 15 jugadores, XI, capitán, vice y banca;
- captura visual posterior a **Enter Squad**, conservada con su SHA-256.

## Cierre operativo

Las cuatro condiciones quedaron cumplidas el `2026-08-20T15:20:28-05:00` en la cuenta
`losmillosFPL` (entry `3609854`). FPL respondió **Equipo guardado** y una recarga posterior
conservó el XI 3-4-3, Haaland capitán, Bruno vicecapitán y el orden Kinský, Sangaré, Rodon,
Thomas. La pantalla confirmó £100.0m de valor, £0.0m en banco y ningún chip activado.

La evidencia visual se retiró del árbol operativo y permanece en el tag
`archive/pre-harness-cleanup-2026-08-23`, ruta
`outputs/fpl/2026-27/gw01_final_mounted.png`. Su SHA-256 es
`8573409eca1815bfa051157be9828f1017d0f1ea8dd9bc8aedc95b8e13becf6c`.
