# Storyboard v2 — La serie definitiva en 5 capítulos

> Doc 7 (2026-07-20). **Supersede al doc 05.** Estructura acordada con Julián: (1) el Mundial de los datos, (2) cómo se calculan xG y momentum, (3) el camino de España, (4) Messi, (5) táctica avanzada.
> **Principio editorial:** cada capítulo es una historia con arco (gancho → desarrollo → remate) y cada lámina prueba una idea con UN gráfico. Voz: experto que construyó sus propios modelos, no curador de internet.

## Las 4 firmas de experto (aplican a TODA la serie)

1. **Pie metodológico en cada lámina** (1 línea, tipografía pequeña): *"xG: modelo propio entrenado con 462K tiros StatsBomb · datos: 163.688 eventos Opta"*. La credibilidad está en el pie.
2. **Todo gráfico sale de datos/modelos propios** — jamás screenshot de terceros. Si el dato es externo (FIFA specs), se visualiza con diseño propio y fuente citada.
3. **Sistema de diseño único:** 1080×1920, fondo #0a0a0a, una sola familia tipográfica, colores semánticos fijos (España #c60b1e, Argentina #75aadb, acento Orbital para lo propio), footer constante "MOVA · Orbital Lab — modelo y datos propios".
4. **Cada capítulo cierra con un puente** al siguiente (la serie se ve completa, no son posts sueltos).

---

# CAPÍTULO 1 — "El Mundial que se jugó dos veces" (5 láminas)

*Tesis: en la cancha y en los datos. La IA fue infraestructura oficial del juego — y hay que saber quién ve esos datos.*

| # | Lámina | Contenido | Gráfico |
|---|---|---|---|
| 1.1 | **Portada-gancho** | "Mientras Ferran definía el Mundial al 106', dieciséis cámaras lo medían 50 veces por segundo." | Infografía de cifras gigantes: 150M puntos/partido · balón 500Hz · 20+ puntos corporales/jugador · 104 partidos. Silueta de cancha de fondo con grid de puntos |
| 1.2 | **La máquina** | Cómo fluye el dato: cancha → 16 cámaras + IMU del balón → visión por computador (pose estimation) → SAOT → decisión en segundos. "El offside ya no lo canta el línea: lo canta un modelo." | **Diagrama de pipeline** horizontal con iconos (estilo arquitectura de sistemas — nuestro terreno) |
| 1.3 | **La democratización** | Football AI Pro: las 48 selecciones con las mismas herramientas (reporte de 60 páginas → IA consultable). El diferencial ya no es acceso: es saber qué preguntar. | Infografía comparativa antes/después (documento vs chat), con las 48 banderas en grid igualitario |
| 1.4 | **Los invisibles** | Detrás de la IA: miles de anotadores etiquetando ~3.000 acciones/partido desde Manila, El Cairo, Río… a ~$70 el partido. La IA del Mundial también es trabajo humano. | **Mapa mundial de puntos** (ciudades de anotación) con flujo hacia los estadios. La lámina con conciencia — nadie más la va a publicar |
| 1.5 | **¿Y quién puede ver esto?** + puente | La pirámide de acceso: FIFA (cerrado) → data comercial ($$$) → capa pública → open data. *"Nosotros recolectamos 163.688 eventos de la capa pública y entrenamos nuestros propios modelos. Todo lo que viene en esta serie sale de ahí."* | **Pirámide de 5 capas** con candados/precios; la capa nuestra resaltada. Cierre: teaser cap 2 |

---

# CAPÍTULO 2 — "Las matemáticas del gol" (6 láminas)

*Tesis: alfabetizar en xG y momentum usando NUESTROS modelos y partidos reales del Mundial — para que los caps 3-5 se disfruten. Es el capítulo docente (marco Externado).*

| # | Lámina | Contenido | Gráfico |
|---|---|---|---|
| 2.1 | **Gancho: dos tiros, dos mentiras** | Ché Adams falló un tiro que era gol el 76% de las veces; Van Dijk anotó uno que entra 7 de cada 1.000. El marcador no cuenta esta historia — el xG sí. | **Media cancha con los 2 tiros reales** marcados (posición exacta, valor xG anotado, uno rojo/uno verde) |
| 2.2 | **Qué es el xG** | Probabilidad de gol de cada tiro según distancia, ángulo, parte del cuerpo, contexto. Entrenado con cientos de miles de tiros. La cancha no vale lo mismo en todas partes: área chica ~40%, borde del área ~4%. | **Heatmap de conversión real por zona** (media cancha, gradiente + % anotados en cada zona — datos propios del torneo) |
| 2.3 | **El xG cuenta el partido que no viste** | Caso real: Turquía 0-1 Paraguay — 2.85 xG contra 0.30. El equipo que mereció ganar 3-0 perdió. Así se ve "merecer" en un gráfico. | **xG race** (curva escalonada acumulada por minuto, gol de Paraguay marcado — la curva turca sube sola y pierde) |
| 2.4 | **¿Y los pases? El xT** | El 99% de las acciones no son tiros. xT: cada zona de la cancha tiene un valor de amenaza aprendido (Markov). Un pase vale lo que gana en amenaza. *"Esta superficie la entrenamos con los 100.000 pases del Mundial."* | **Nuestro xT grid sobre la cancha completa** (heatmap 16×12 con valores clave) — la lámina académica insignia |
| 2.5 | **El momentum, por fin explicado** | La gráfica famosa del broadcast: amenaza neta (xT de pases + xG de tiros) por ventanas de 5'. Demo con el partidazo Francia 4-6 Inglaterra (10 goles). "La próxima vez que la veas en TV, sabes qué hay debajo." | **Barras divergentes de momentum** del 4-6, con los 10 goles anotados sobre las barras — se VE que el gol llega en las olas |
| 2.6 | **Cierre + puente** | Recap visual de 15 segundos: xG = calidad del tiro · xT = valor del pase · momentum = flujo. "Ahora sí: veamos lo que hizo España con estas tres lentes." | Mini-tríptico de los 3 gráficos anteriores en miniatura |

---

# CAPÍTULO 3 — "España: la campeona que nunca sufrió" (6 láminas)

*Tesis: no ganó por épica ni por suerte — ganó por diseño. Y las 3 lentes del cap 2 lo demuestran.*

| # | Lámina | Contenido | Gráfico |
|---|---|---|---|
| 3.1 | **Ancla: nunca fue perdiendo** | 770 minutos, 8 partidos, jamás abajo en el marcador. Una grieta (cabezazo de De Ketelaere, 40') cerrada en 53 minutos por Merino. | **Timeline de 8 barras horizontales** (largo=minutos, verde continuo), goles ○, Merino 93'/97' ★, la grieta ● roja. Se lee como una historia |
| 3.2 | **No robó ni un partido** | Ganó la batalla del xG en los 8 (nadie más lo hizo). El campeón sin deuda con el azar. | **8 pares de barras** xG España vs rival (España siempre mayor) — patrón visual inmediato |
| 3.3 | **El día que el fútbol fue injusto** | 0-0 con Cabo Verde: 97% del juego en campo rival (récord del torneo), 2.26 xG… y cero goles. España no entró en pánico: no cambió nada y ganó los 7 siguientes. | **Heatmap territorial del partido** (toques de España devorando la cancha) + xG race del 0-0 en mini |
| 3.4 | **La red con un centro de gravedad** | El grafo de pases: Rodri hub (14.9% del peso, betweenness máximo), la autopista Laporte→Rodri (140 conexiones, la dupla del torneo). | **Pass network sobre la cancha** (nodos=posición media, tamaño=centralidad, arista Laporte→Rodri en acento) + mini-red de Argentina como contraste estructural |
| 3.5 | **La noche que ganó sin la pelota** | Semifinal: Francia le quitó posesión (51%) y territorio (39%)… y España generó 1.86-0.46 de xG. Cuando no pudo dominar CON el balón, dominó SIN él. | **3 duelos de barras**: posesión / territorio / peligro real — Francia gana 2, España aplasta donde importa |
| 3.6 | **La final en dos lentes** | Shot map 20-2 (xG 2.09-0.14: "el 1-0 más mentiroso") + momentum: España positiva 24/29 ventanas, pico exacto en la ventana del gol (106'). | **Panel doble**: shot map dual arriba, momentum divergente abajo con el gol de Ferran marcado. Puente: "¿y el que perdió esta final? Ese merece su propio capítulo" |

---

# CAPÍTULO 4 — "Messi: la última función, contada por los datos" (5 láminas)

*Tesis: sin nostalgia — el modelo dice que a los 39 fue el jugador más valioso con el balón. Y también dice cómo termina la historia. El capítulo emocional con rigor.*

| # | Lámina | Contenido | Gráfico |
|---|---|---|---|
| 4.1 | **Gancho: lo que dice el modelo** | "No es nostalgia: nuestro modelo de amenaza lo pone #1 del Mundial a los 39 años." 5.40 xT — nadie generó más peligro con sus pases. | **Barra top-10 xT del torneo**, Messi arriba en celeste, edad anotada junto a cada nombre (los demás: 24-28) |
| 4.2 | **Toca menos, vale más** 💎 | El hub de Argentina era Paredes (el metrónomo). Messi ya no toca más la pelota que nadie — la toca MEJOR que nadie. Dos formas de ser vital, separadas por el modelo. | **Scatter volumen de pases (x) vs xT por pase (y)** — 40 jugadores en gris, Messi solo arriba (mago), Rodri/Paredes derecha (metrónomos). El gráfico-conversación de la serie |
| 4.3 | **El mapa del mago** | Sus zonas de siempre: media cancha derecha. 28 regates (líder del torneo), 20 faltas recibidas (líder), 8 goles — 7 de zurda. El cuerpo cambió; el mapa no. | **Cancha con sus acciones**: hexbin de toques + flechas de sus 10 pases de mayor xT + puntos de regate. Denso y bello |
| 4.4 | **Involucrado en todo** | 12 de los 18 goles de Argentina pasaron por él (8 goles + 4 asistencias). La dependencia hecha número — y comparada: Haaland 58%, Mbappé 50%, Messi 44%… pero con 39 años. | **Lollipop de dependencia goleadora** por estrella, con la edad como segunda dimensión |
| 4.5 | **Los datos también escriben tragedias** | 2 penales fallados en el torneo. 11 atajadas de Dibu en la final — su mejor partido fue el que perdió. 0.14 xG generado por todo su equipo esa noche. El adiós más humano posible. Puente: "¿por qué Argentina no pudo? La respuesta es táctica → cap 5" | **Timeline de sus 7 partidos** (goles ○, asistencias △, penales fallados ✕ en rojo) terminando en la final gris |

---

# CAPÍTULO 5 — "La táctica bajo el microscopio" (6 láminas)

*Tesis: el cierre para los que quieren la cátedra completa — estilos, pressing, caos y la moraleja de los datos. El capítulo más denso, a propósito: es el embudo hacia el mundo Orbital/Externado.*

| # | Lámina | Contenido | Gráfico |
|---|---|---|---|
| 5.1 | **Los 5 fútboles del Mundial** | KMeans sobre 8 features por selección encontró 5 estilos sin que nadie le dijera nada. | **Mapa PCA 2D**: 48 puntos, 5 clusters coloreados, España coronada, extremos anotados |
| 5.2 | **El estilo no clasifica** | Campeón y subcampeón comparten cluster… con Turquía y Corea (eliminadas en grupos). La ejecución dentro del estilo es lo que separa. | Mismo mapa PCA con **overlay de ronda alcanzada** (tamaño/opacidad) — el cluster élite tiene campeones Y fracasos |
| 5.3 | **El mapa del pressing (y su mentira)** | PPDA × altura defensiva: Alemania presionó más que nadie y se fue en 16avos; España top-2 sostenido 8 partidos; Cabo Verde el búnker 43.5. | **Scatter de cuadrantes** con color = ronda alcanzada. El color desmiente el eje |
| 5.4 | **El gol sigue siendo caos** | 56% de los goles en jugadas de ≤3 pases; solo 20% de 10+. La era de la posesión no cambió la naturaleza del gol. | **Waffle de 307 goles** coloreados por longitud de cadena + nota "España lideró la orfebrería (5 de 10+)" |
| 5.5 | **Los extremos del espectro** | Paraguay: 2.1 pases/cadena, 10.3% cancha/seg — el anti-fútbol que eliminó a Alemania. En la otra esquina: Argentina 6.1. Ambos llegaron lejos: no hay una sola forma de competir. | **Scatter pases/cadena vs velocidad de avance** — Paraguay solo en su esquina, diagonal de estilos anotada |
| 5.6 | **Cierre de la serie: la moraleja** | Los hubs modernos son centrales (Upamecano/Guéhi/Gabriel/Cubarsí). El fútbol cambió de arquitectura. Y nuestra moraleja de modeladores: le dimos 16% a España — el valor estaba donde el público no miraba. "Con datos abiertos y método, se compite. Es lo que enseñamos." CTA. | **Small multiples: 4 mini pass-networks** (hubs resaltados) + cifra final de la serie |

---

## Plan de producción

| Orden | Qué | Por qué primero |
|---|---|---|
| 1 | Sistema de diseño (template matplotlib: fondo, fuentes, footer, paleta) | Consistencia antes que volumen |
| 2 | Cap 3 completo (España) | El de mayor demanda de audiencia; todos los datos listos |
| 3 | Cap 2 (didáctico) | Reusa gráficos base ya construidos (xG race, xT grid, momentum) |
| 4 | Cap 4 (Messi) → Cap 5 (táctico) → Cap 1 (infografías, sin cómputo) | De más data-viz a más diseño puro |

**Pendientes de verificación antes de publicar** (marcados en docs 02/04): récord histórico de autogoles, Mbappé 10+ desde Müller 1970. Todo lo demás es dato propio verificable.
