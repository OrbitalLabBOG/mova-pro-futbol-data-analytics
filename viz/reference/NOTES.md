# Notas — script de referencia @bariscanyeksin (match report WhoScored)

> 2026-07-20. Script original: `match_report_bariscanyeksin.py` (notebook Colab exportado, 1.785 líneas).
> **Hallazgo clave: consume WhoScored `matchCentreData` — EXACTAMENTE nuestro formato.** Nuestra DB ya tiene todo (events con qualifiers, lineups con shirtNo/isFirstEleven/position). Podemos replicar cada panel para los 104 partidos sin scraping.

## Qué grafica y cómo (técnicas por panel)

| Panel | Técnica | Notas de implementación |
|---|---|---|
| **Pass network** | Nodos = posición media de pases por jugador; aristas = pares pasador→receptor (receptor inferido: siguiente evento del mismo equipo); grosor+alpha ∝ volumen; línea vertical = mediana de altura de pases; círculo=titular, cuadrado=suplente | `pitch.lines` + `pitch.scatter` + `annotate` shirtNo. Igual a nuestro approach de grafos pero con posiciones reales en cancha |
| **Defensive block** | KDE heatmap de acciones defensivas (`pitch.kdeplot`, cmap custom bicolor) + nodos por jugador con tamaño ∝ engagement + **línea de altura defensiva (DAH)** + % compacidad | La línea DAH convierte el heatmap en argumento. Filtra GK. Aerials solo x≤80 |
| **Zonas (Pass end zone / Chance creating)** | `bin_statistic_positional` + `heatmap_positional` + `label_heatmap` con % — las zonas del juego de posición (half-spaces, zona 14) | mplsoccer nativo; el look "profesional" del dashboard |
| **Momentum** | xT por minuto en barras ± (color por equipo), goles como scatter arriba/abajo | El nuestro es superior (ventanas 5' + xG de tiros + suavizado). Adoptar su marcación de goles |
| **Shot map + goal mouth** | Scatter por resultado del tiro + mapa de portería (goalMouthY/Z de qualifiers — ¡lo tenemos!) | El goal-mouth (dónde entró cada tiro EN el arco) no lo habíamos considerado — muy vistoso |
| **High turnovers** | Recuperaciones a ≤40m del arco rival, con semicírculo de radio 40m dibujado | Viz simple y potente para pressing |
| **Crosses / box entries / progressive passes** | Flechas filtradas por qualifiers (Cross, sin Corner), entradas al área por tipo | Qualifier `Length` para longitud de saques (parse de JSON) |
| **Player bars** | Barras top pasadores/defensores/shot-sequence involvement | Relleno del dashboard |

**Diseño general:** un solo bg (#999), colores de equipo, `path_effects` stroke en títulos, FontManager, GridSpec 4×3. La unidad viene de: mismo pitch style + 2 colores semánticos + etiquetas mínimas.

## Qué NO se puede con event data (honestidad técnica)

- **Voronoi real** (territorio por jugada) — requiere tracking de los 22. Alternativa defendible: voronoi de POSICIONES MEDIAS ("territorio medio del XI") — visualmente espectacular y conceptualmente honesto si se etiqueta así.
- Sprints, distancias corridas, compacidad instantánea — tracking. Nuestra compacidad = proxy por dispersión de acciones.

## Catálogo de gráficos por vistosidad × legibilidad en grilla

| Gráfico | Vistoso | ¿Funciona en grilla 48? | Insight que porta |
|---|---|---|---|
| Pass network mini | ★★★★★ | ✅ (simplificado: sin números, top-N aristas) | Arquitectura/identidad estructural |
| Defensive block KDE + línea DAH | ★★★★☆ | ✅✅ (blobs+línea legibles en miniatura) | Búnker vs línea alta — el espectro táctico |
| Zonas posicionales (heatmap_positional) | ★★★★☆ | ✅ | Dónde vive cada equipo |
| Shot map mini | ★★★☆☆ | ✅ | Perfil de remate (cerca/lejos) |
| **Pass sonar** (no está en el script; mplsoccer) | ★★★★★ | ✅✅ (diseñado para grillas) | Firma direccional de pase — el look más "experto" |
| Voronoi de posiciones medias | ★★★★★ | ✅ | Territorio medio |
| Momentum | ★★★★☆ | ⚠️ (mejor grilla 8, no 48) | Flujo del partido |
| High turnovers | ★★★☆☆ | ⚠️ | Pressing |
| Goal mouth map | ★★★★☆ | ❌ (una lámina, un partido) | Dónde entraron los goles |
| Convex hull del XI | ★★☆☆☆ | ⚠️ poco legible mini | Forma |

## Grillas masivas candidatas (el "money shot" de tácticas masivas)

> **Regla de oro descubierta pensándolo: EL ORDEN DE LA GRILLA ES EL ARGUMENTO.** Una grilla de 48 ordenada alfabéticamente es un catálogo; ordenada por métrica o agrupada por cluster es UN GRÁFICO.

1. **G1 "Las 48 arquitecturas"** — grid de pass networks mini **agrupadas por los 5 clusters de estilo** (nuestro KMeans del doc 04). La grilla PRUEBA visualmente el clustering: los búnkeres se ven planos y rotos, los dominadores densos y altos. Cruce perfecto cap 6.
2. **G2 "Dónde defiende cada país"** — grid de bloques defensivos KDE **ordenada por altura defensiva** (de Cabo Verde 24.9 a España 41.6): el gradiente de color subiendo por la cancha a lo largo de la grilla es hipnótico. Con borde coloreado por ronda alcanzada = segundo argumento (la altura no predice éxito).
3. **G3 "Las firmas de pase"** — 48 pass sonars agrupados por cluster. El look más pro-analytics de todos.
4. **G4 "Cómo remata cada uno"** — 48 shot maps mini ordenados por distancia media de tiro (Noruega 14.5m → Cabo Verde 25.5m).
5. **G5 "España ×8"** — los 8 momentum charts de España en grilla (el torneo entero en flujo — casi todo rojo positivo). Para cap 4.
6. **G6 "El territorio medio"** — voronoi de posiciones medias de las 48 (etiquetado como territorio medio).

## Plan de adaptación

- Crear `viz/wc_viz.py`: port de las funciones clave del script a nuestra SQLite (coords ya opta 0-100), parametrizadas por `match_id`/`team` — sin scraping, sin estado global.
- Reusar de nuestro stack: xT propio (mejor que el suyo), momentum 5' + xG, clusters KMeans para ordenar grillas.
- Estilo: adaptar a dark Orbital (#0a0a0a) — el script usa fondo claro.
