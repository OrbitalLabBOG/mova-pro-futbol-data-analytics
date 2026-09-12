---
title: "FPL 2026/27 GW4 — equipo montado, verificación y plan de chips"
date: 2026-09-11
updated: 2026-09-11
status: supervised-mount-verified
owner: MOVA Fantasy Fútbol Data Analytics
season: 2026-27
gameweek: 4
---

# GW4 — decisión humana ejecutada y verificada

## Resultado

Julián aprobó y solicitó el montaje desde el VPS. El GET privado posterior,
observado el **11 de septiembre de 2026 a las 19:33:52.427 UTC (14:33 Colombia)**,
coincide con la aprobación y con la pantalla recargada después de `Team Saved`.
Entry `3609854`, formación **3-4-3**, **sin transferencias ni chips**, una FT
disponible y £0,0m en banco en ese corte.

| Puesto | Jugador | Rol |
| --- | --- | --- |
| 1 | Verbruggen | Portero titular |
| 2–4 | Calafiori, Egan, Tarkowski | Defensa |
| 5–8 | Groß, Bruno Fernandes, Mbeumo, Tzolis | Medio; Bruno vicecapitán |
| 9–11 | Calvert-Lewin, João Pedro, Haaland | Delantera; Haaland capitán |
| 12 | Kinsky | Portero suplente |
| 13–15 | Thomas, Maguire, Sangaré | Banca de campo, en ese orden |

Tzolis entra por Sangaré; Thomas queda primero en la banca de campo. Se conserva
la plantilla de 15 y la capitanía. Esta decisión sustituye la propuesta preliminar
registrada en PM el 10 de septiembre; no altera retrospectivamente esa nota.

## Análisis y límites de la decisión

| Alternativa del corte | xP GW4 | Lectura |
| --- | ---: | --- |
| No hacer nada, propuesta almacenada | 48,26 | Referencia del motor |
| Conservar plantilla y optimizar XI, cálculo local | 48,74 | Base de la decisión humana |
| Calafiori → Justin, sin chip | 49,76 | Mejora inmediata pequeña frente a guardar FT |
| Calafiori → Justin y Bench Boost | 60,48 | +10,72 frente al mismo cambio sin chip |

Son proyecciones internas del corte, no puntos garantizados. El cálculo local del
XI usa las proyecciones congeladas y el multiplicador de capitán; no simula
autosustituciones ni valora por sí solo conservar recursos varias jornadas.
No se ha demostrado matemáticamente que guardar Bench Boost sea óptimo: se eligió
flexibilidad ante cobertura parcial y coste de oportunidad incierto.

La sesión Codex del VPS se recuperó y hubo inferencia real exitosa, no sólo un
archivo de credenciales presente. Researcher `gpt-5.6-luna` importó
`research_38bf2fbd7ff0bd5f1e215ea470c71870`: cobertura 11/25 (44 %), evidencia
9/25 (36 %), seis de los quince jugadores cubiertos y un conflicto pendiente.
Una noticia de Haaland describe una lesión de 2023/24 pese a elementos dinámicos
actualizados en la página; no acredita una lesión actual. Falta corregir la
validación temporal y mejorar la cobertura antes de confiar en esa señal.

Strategist/Critic `gpt-5.6-terra`, deliberación
`deliberation_d1e83ed8e0168ed067e8f406d7d8ff15`, terminó bloqueado y prefirió
`do_nothing`; esto es una respuesta condicionada por la calidad del research.
El envelope `envelope_2fb3ca386991fe813f8c17d9` conserva el bloqueo
`RESEARCH_CONFLICTS_CLEAR`. No se promovió la intervención shadow ni un modelo.

Research consumió 355.066 tokens frente a su límite individual de 160.000.
El exceso se revisó con acción `reduce_scope`, sin subir el límite ni declararlo
resuelto. Corte presupuestal posterior: 437.930 consumidos, 120.000 estimados de
un intento fallido previo y 557.930 comprometidos de 900.000; cero reservas
huérfanas. No repetir investigación amplia para resolver un conflicto puntual.

## Autoridad y evidencia

La ventana supervisada fue `guarded/A2`, limitada al XI aprobado. Los eventos de
control 16–20 abrieron la ventana y 21–25 la cerraron. Estado final:
`shadow/A0`, `browser_writes=false`, `kill_switch=true`,
`compliance_gate=pending`; browser detenido. Doctor a las **19:34:50 UTC**:
**24 PASS, 0 WARN, 0 FAIL**, runtime v0.7.0,
`dea98e20db44b05da7b426d0b4476f1cd5fca928`. No se desplegó código.

Evidencia privada conservada en el VPS, bajo
`/var/lib/mova-fpl/artifacts/decisions/2026-27/`:

| Archivo | SHA-256 |
| --- | --- |
| `gw04_20260911_human_approved_lineup.json` | `037493eb73f1234b468a16029eed0af688dd5144e601d1e98206affe9380b490` |
| `gw04_20260911_final_mounted.png` | `d3de10db9be6507419cd53edef5b0d392d62551d4093bed3eea9af3f5a063c01` |
| `gw04_20260911_observed_after_mount.json` | `ae782093dcf392e23225c1feb64f667eef5e12103e365a7b753177181f0b0dd2` |

`gw04_20260911_mount_verification.json` registra siete comprobaciones verdaderas:
equipo, GW, puestos, capitán, vicecapitán, cero transferencias y cero chips.
Los payloads privados y la captura no se copian a Git ni a Supabase PM.

**Límite pendiente:** el importador supervisado legado sólo admite A1; no se
reclasificó esta ejecución A2 ni se editó el ledger directamente. El estado
`supervised-mount-verified` de esta acta describe evidencia externa comprobada,
no un cierre `executed_verified` normalizado en el harness. La adaptación de
`manual_verified` y el cierre del ciclo siguen pendientes. El montaje tampoco
cuenta como rehearsal del driver ni habilita ejecución autónoma futura.

## Plan provisional de poderes

El snapshot privado confirma disponibles Wildcard, Free Hit, Triple Captain y
Bench Boost, con primera ventana hasta GW19. FPL permite un chip por jornada y
renueva el juego de cuatro desde GW20. La
[guía oficial del 7 de septiembre](https://www.premierleague.com/en/news/4362085)
identifica GW6 tras el parón como ventana de Wildcard, Haaland en casa ante
Ipswich GW7 o Hull GW16 para Triple Captain, y GW12 como posible Free Hit.

Nuestra propuesta, pendiente de datos y decisión de cada jornada:

| Poder | Ventana a evaluar | Condición de MOVA |
| --- | --- | --- |
| Wildcard | GW6 | Reestructuración justificada por titulares, lesiones y calendario; no gastarla por un mal resultado aislado |
| Triple Captain | Haaland GW7; alternativa GW16 | Disponibilidad y minutos fiables, buen techo de puntos y revisión de rotación |
| Bench Boost | Una o dos jornadas después de una eventual Wildcard | Quince opciones con minutos fiables; comparar el valor de los cuatro suplentes y coste de preparar la banca |
| Free Hit | GW12 u otra jornada con desventaja temporal clara | Corregir ausencias o calendario adverso sin desarmar la estructura futura |

Si Bench Boost y Triple Captain compiten por GW7, escoger uno y mover el otro.
Empezar la comparación en GW5, reservar jornadas distintas para los cuatro y
revisar el calendario antes de GW19; no esperar indefinidamente una doble
jornada no confirmada. Estas ventanas son propuestas, no activaciones programadas.
