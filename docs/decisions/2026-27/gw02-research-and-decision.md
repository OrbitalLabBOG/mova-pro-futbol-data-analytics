---
title: "FPL 2026/27 GW2 — revisión estratégica y decisión final"
date: 2026-08-28
status: approved-pending-execution
owner: MOVA Fantasy Fútbol Data Analytics
season: 2026-27
gameweek: 2
---

# FPL 2026/27 GW2 — revisión estratégica y decisión final

## Veredicto

La decisión final es **guardar la transferencia**, no usar chip y corregir únicamente el
once, la banca y la capitanía. Es una intervención humana documentada sobre el MILP: el
optimizador detectó correctamente que la estructura podía mejorar, pero la recomendación
dependía de probabilidades de minutos contradichas por la observación de GW1 y por fuentes
oficiales vigentes.

**Formación GW2: 3-4-3 · 1 FT guardada · £0.0m en banco · sin chip.**

- **XI:** Kinský; Maguire, Calafiori, Mosquera; Tzolis, Bruno Fernandes **(C)**,
  Mbeumo, Sangaré; Haaland **(V)**, João Pedro, Calvert-Lewin.
- **Banca:** Verbruggen; Groß (1), Rodon (2), Bobby Thomas (3).
- **Transferencias:** ninguna.
- **Huella canónica:** se deriva de
  `decisions/fpl/2026-27/gw02_final.json`; cualquier cambio exige una nueva revisión.

## Certificación predeadline

La revisión se cerró el 28 de agosto de 2026 antes del deadline de las `17:30 UTC`
(`12:30 America/Bogota`). El estado autenticado del entry `3609854`, observado a las
`14:53:04 UTC`, era válido y confirmaba 15 jugadores, 1 FT, £0.0m y los cuatro chips de la
primera ventana disponibles.

| Control | Resultado |
| --- | ---: |
| Doctor | 22 PASS, 0 WARN, 0 FAIL |
| Catálogo FPL final | 620 jugadores, 20 clubes, 380 fixtures |
| GW1 live | 610 filas de jugador |
| Eventos GW1 | 10/10 partidos, 15.434 eventos |
| Odds GW2 | 20 partidos, 43 bookmakers, H2H y totals completos |
| Modelos | minutos `1.1.0`, puntos `1.1.0` |
| Estado privado | válido, 1 FT, banco £0.0m, cuatro chips disponibles |

El colector se forzó una vez en la ventana final. FPL, schedule y cobertura de eventos
terminaron correctamente. El servicio de odds conservó el checkpoint de deadline ya sellado
y no consumió cuota de forma redundante.

## Escenarios comparados

| Escenario | xP interno GW2 | Coste de decisión | Lectura |
| --- | ---: | ---: | --- |
| MILP H3 + chips | 54,7 | Wildcard | Inválido: plantilla £100,1m; no ejecutar |
| MILP H5 sin chips | 49,0 | 3 cambios, −8 | Vende Haaland y Sangaré por señal de minutos no confiable |
| Política conservadora | 47,8 | 1 FT | Tzolis → Le Fée; depende del mismo sesgo de minutos |
| **Intervención revisada** | no comparable sin recalibrar | **0 FT, 0 chip** | Maximiza información y flexibilidad para GW3 |

No se usa el xP del override como cifra falsa de precisión: el proyector asignó P(60) de
40% a Haaland, 19% a Tzolis y 13% a Sangaré, aunque jugaron 90, 75 y 75 minutos en GW1,
respectivamente, y la API los marca disponibles. Ese desacuerdo invalida la comparación
puntual de las alternativas que los venden.

## Evidencia deportiva y de mercado

- El Scout oficial aconseja conservar a Bruno y Mbeumo para recibir a Ipswich y considera a
  Bruno el mejor candidato de capitanía de GW2. También identifica a Sangaré como un activo
  de XI *set-and-forget* tras sus 14 puntos de GW1:
  <https://www.premierleague.com/en/news/4697098/ten-lessons-from-gameweek-1-in-fantasy>.
- El Scout considera a Haaland esencial incluso en una plantilla nueva/Wildcard. La decisión
  de mantenerlo no depende de reaccionar a sus dos puntos de GW1:
  <https://www.premierleague.com/en/news/4698173/the-scouts-fpl-gw2-squad-for-wildcarders-and-new-starters>.
- Brentford confirmó a Sangaré como titular en GW1 y destacó su rendimiento durante 76
  minutos, sus dos asistencias y su aporte defensivo:
  <https://www.brentfordfc.com/en/news/article/analysis-mamadou-sangare-premier-league-debut-brentford-3-tottenham-hotspur-0>.
- La rueda de prensa de City solo reportó la recuperación de Foden para visitar Palace y no
  publicó una alerta sobre Haaland:
  <https://www.mancity.com/news/mens/pep-guardiola-press-conference-crystal-palace-63814049>.
- El consenso de 43 bookmakers da como favoritos a United sobre Ipswich (67,7%), Arsenal
  sobre Villa (61,8%) y City sobre Palace (56,9%). Un ajuste Poisson sobre H2H y over/under
  aproxima 2,20 goles para United, 1,90 para Arsenal y 1,90 para City.

## Por qué se guarda la transferencia

La plantilla ya contiene a los tres activos cuya salida domina las propuestas defectuosas:
Haaland, Tzolis y Sangaré. Venderlos ahora materializaría un error de observabilidad del
modelo, no una señal de campo. Mantenerlos conserva además el núcleo Haaland–Bruno–Mbeumo–
João Pedro y permite observar otra jornada antes de decidir si la estructura de triple
Arsenal/triple United necesita Wildcard.

Llegar a GW3 con dos FT permite corregir dos posiciones sin hit. La Wildcard queda reservada
para una divergencia estructural verificable —lesiones, pérdida de titularidad o un frente de
fixtures claramente superior— y no para perseguir los puntos de una sola jornada.

## Spec exacta de ejecución

1. No abrir la pantalla de transferencias y no activar chip.
2. Seleccionar a Kinský como portero titular y dejar a Verbruggen en banca.
3. XI de campo: Maguire, Calafiori, Mosquera; Tzolis, Bruno, Mbeumo, Sangaré;
   Haaland, João Pedro, Calvert-Lewin.
4. Banco de campo en orden: Groß, Rodon, Bobby Thomas.
5. Capitán Bruno Fernandes; vicecapitán Erling Haaland.
6. Guardar, esperar la confirmación de FPL, recargar y comparar los 15 jugadores, XI,
   C/V, banca, 1 FT, banco y chips contra el JSON canónico.

## Condiciones de invalidez

- cambio de estado o precio en el equipo privado antes de guardar;
- noticia oficial adversa sobre Bruno, Haaland, Tzolis o Sangaré;
- discrepancia entre la pantalla y el JSON canónico;
- deadline cerrado, MFA o sesión no autenticada;
- activación accidental de un chip o aparición de un coste de transferencia.

Ante cualquiera de estas condiciones se detiene la operación; no se improvisa una segunda
plantilla en el navegador.

