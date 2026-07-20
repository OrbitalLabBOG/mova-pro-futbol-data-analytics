# Storyboard — Insights → Láminas (serie IG historias, 1080×1920 dark)

> Doc 6 (2026-07-20). Estructura editorial: 4 capítulos, ~14 láminas. Cada lámina: insight + gráfico que LO PRUEBA + fuente de datos + dificultad.
> Principio: una lámina = una idea = un gráfico. El gráfico no decora — demuestra.

---

## CAPÍTULO 1 — "El Mundial que se jugó dos veces" (intro conceptual, 2 láminas)

### L1. El Mundial más data-driven de la historia
- **Insight:** 150M puntos de tracking/partido, balón 500Hz, IA para las 48 selecciones (doc 00).
- **Gráfico:** infografía de números grandes (no chart) — cifras en tipografía gigante con iconos. La "portada" de la serie.
- **Datos:** doc 00. **Dificultad: baja.**

### L2. Así ve la cancha un modelo 💎 (la lámina académica)
- **Insight:** entrenamos un xT propio con los 100K pases del Mundial — cada zona de la cancha tiene un valor de amenaza aprendido (#66-70, método).
- **Gráfico:** **heatmap del xT grid sobre la cancha** (mplsoccer, colormap secuencial, valores anotados en zonas clave) + 1 línea: "así decide un modelo qué pase valió la pena". Es LA lámina que muestra expertise: nadie más publica su propia superficie xT del Mundial.
- **Datos:** `outputs/divulgacion/xt_grid.npy` ✅ listo. **Dificultad: baja.**

---

## CAPÍTULO 2 — "Lo que el torneo nos dijo" (el Mundial en datos, 5 láminas)

### L3. Los 5 fútboles del Mundial 💎
- **Insight #84-85:** KMeans encontró 5 estilos sin supervisión; campeón y eliminados tempranos comparten cluster — el estilo no clasifica, la ejecución sí.
- **Gráfico:** **scatter PCA 2D** — 48 puntos (uno por selección), 5 colores de cluster, España con corona, anotados Turquía/Alemania/Paraguay/Cabo Verde. Ejes sin unidades ("mapa de estilos").
- **Datos:** `style_clusters.json` ✅. **Dificultad: media** (etiquetado limpio con adjustText).

### L4. El gol sigue siendo caos 💎
- **Insight #78:** 56% de los goles nacieron de jugadas de ≤3 pases; solo 20% de 10+.
- **Gráfico:** **waffle chart / barras apiladas horizontales** (307 goles como cuadritos coloreados por longitud de cadena) + nota "España lideró la orfebrería: 5 goles de 10+ pases".
- **Datos:** `chains.json.gz` ✅. **Dificultad: baja.**

### L5. El mapa del pressing (y su mentira) 💎
- **Insight #81-82:** PPDA × altura defensiva; Alemania la más intensa y eliminada; Cabo Verde el búnker 43.5; España sostenible.
- **Gráfico:** **scatter de cuadrantes** PPDA (x, invertido) vs altura defensiva (y), **color = ronda alcanzada** (gradiente), 32+ equipos etiquetados los extremos. El color cuenta la historia: presionar mucho no pinta el punto de "campeón".
- **Datos:** `ppda.json` ✅. **Dificultad: media.**

### L6. Paraguay jugó otro deporte
- **Insight #79-80:** 2.11 pases/cadena y 10.3%/seg — el anti-fútbol que eliminó a Alemania.
- **Gráfico:** **scatter pases-por-cadena (x) vs velocidad de avance (y)** con los 48; Paraguay solo en una esquina, España/Argentina/Algeria en la otra; diagonal de "estilos". Bonus mini-mapa: heatmap defensivo de Paraguay (todo en su área).
- **Datos:** `chains.json.gz` ✅. **Dificultad: media.**

### L7. La posesión está sobrevalorada (Turquía) 
- **Insight #16 + #73:** 65% de posesión (la más alta) y eliminada en grupos; 4 de 5 reyes de la posesión, afuera temprano.
- **Gráfico:** **dot strip / lollipop**: posesión media (x) por equipo, color = hasta dónde llegó; Turquía resaltada con flecha "grupos", España "campeona". Un solo eje, mensaje brutal.
- **Datos:** query directa ✅. **Dificultad: baja.**

---

## CAPÍTULO 3 — "España, campeona por diseño" (el beat central, 5 láminas)

### L8. Nunca fue perdiendo 💎 (la lámina ancla)
- **Insight #1+55:** 770 minutos sin ir abajo + ganó el xG en los 8 partidos.
- **Gráfico:** **timeline horizontal de 8 barras** (una por partido, largo = minutos) coloreadas por estado (verde=empate/arriba continuo), con marcas: goles propios (punto blanco), Merino 93'/97' (estrella), la única grieta (De Ketelaere 40', punto rojo). Debajo: mini-fila con el xG de cada partido (España siempre mayor).
- **Datos:** events ✅. **Dificultad: media.** Es la lámina más narrativa: se lee como una historia.

### L9. La final en dos números: 20-2
- **Insight #8+65:** shot map de la final con xG.
- **Gráfico:** **shot map dual** (mplsoccer, media cancha por equipo): burbujas tamaño=xG, color gol/no-gol; el contraste visual 20 burbujas vs 2 es el mensaje. Título: "El 1-0 más mentiroso del Mundial".
- **Datos:** shot_xg ✅. **Dificultad: baja** (receta estándar).

### L10. El momentum de la final 💎 (la lámina sofisticada)
- **Insight #72:** España positiva 24/29 ventanas; pico en la ventana del gol; Argentina despertó tarde.
- **Gráfico:** **barras divergentes por ventana de 5'** (arriba España roja, abajo Argentina celeste), línea de gol al 106' anotada, sombreado de prórroga. Pie: "amenaza = xT de pases + xG de tiros, modelo propio".
- **Datos:** `momentum_all.json` ✅. **Dificultad: media.**

### L11. Rodri, el centro del universo 💎
- **Insight #74+60:** hub 14.9%, betweenness máximo, Laporte→Rodri 140 conexiones, 756 pases.
- **Gráfico:** **pass network de España sobre la cancha** (nodos en posición media, tamaño=centralidad, aristas gruesas por volumen; Laporte→Rodri en color acento con "140"). Al lado, versión miniatura de la red de Argentina (Paredes hub) para comparar estructuras.
- **Datos:** networks.json + posiciones medias (query) ✅. **Dificultad: alta** (la más compleja, y la que más expertise muestra).

### L12. La noche que ganó sin la pelota (semifinal)
- **Insight #56:** vs Francia: 51% posesión, field tilt 39%... xG 1.86-0.46.
- **Gráfico:** **3 barras enfrentadas** (posesión / territorio / peligro real) — Francia gana las dos primeras, España aplasta la tercera. Simple y demoledor: "¿cuál importaba?".
- **Datos:** query ✅. **Dificultad: baja.**

---

## CAPÍTULO 4 — "Los individuos bajo el microscopio" (4 láminas)

### L13. Messi: toca menos, vale más 💎💎
- **Insight #66+77:** #1 en xT (5.40) a los 39; pero el hub de Argentina era Paredes.
- **Gráfico:** **scatter volumen de pases (x) vs xT por pase (y)** — top ~40 jugadores del torneo como puntos grises, Messi solo arriba (poco volumen, valor altísimo), Rodri abajo-derecha (volumen enorme, valor alto), Paredes derecha. Cuadrantes: "los metrónomos" / "los magos". Es EL gráfico de dispersión de la serie.
- **Datos:** recomputable del script xt ✅. **Dificultad: media.**

### L14. Cubarsí: el playmaker juega de central 💎
- **Insight #67:** 4° creador de amenaza del Mundial con 19 años, siendo central.
- **Gráfico:** **mapa de cancha con sus 15-20 pases de mayor xT-gain** (flechas desde el círculo central/su zona, color por xT ganado, colormap secuencial) + barra lateral: top-5 xT del torneo con su nombre resaltado entre Messi/Rodri/Pedri. Título: "El 4° creador del Mundial es un central de 19 años".
- **Datos:** events + xt_grid ✅. **Dificultad: media.**

### L15. Mbappé, cazador del segundo tiempo
- **Insight #17:** 10 goles, 8 en el 2T.
- **Gráfico:** **strip plot de sus 10 goles sobre una línea de 0-120 min** (marca al 45'), tamaño=xG del tiro. Se ve el enjambre después del 45. Nota: "primer 10+ desde Müller 1970 [verificar]".
- **Datos:** events ✅. **Dificultad: baja.**

### L16. La doble vida de Olise
- **Insight #50:** 0 goles en 20 tiros + máximo asistidor (6).
- **Gráfico:** **panel dividido**: izquierda su shot map (20 puntos, ninguno verde), derecha sus 6 asistencias como flechas a gol. "El mismo jugador. La peor y la mejor estadística."
- **Datos:** events ✅. **Dificultad: media.**

---

## Orden de producción sugerido (por impacto/esfuerzo)

| Tanda | Láminas | Racional |
|---|---|---|
| 1 | **L8 (nunca perdiendo), L10 (momentum final), L13 (Messi scatter)** | Las 3 firmas de la serie: narrativa + sofisticación + el gráfico conversation-starter |
| 2 | L2 (xT grid), L11 (red Rodri), L14 (Cubarsí) | El bloque "expertise": modelo propio + grafos |
| 3 | L3 (clusters), L5 (pressing), L9 (final 20-2) | Ciencia + táctica |
| 4 | L4, L6, L7, L12, L15, L16 | Complementos rápidos |

**Especificaciones comunes:** 1080×1920, fondo #0a0a0a (brand Orbital), tipografía vía FontManager, `highlight_text` para títulos con color semántico (España #c60b1e / Argentina #75aadb), footer con logo Orbital + "modelo y datos propios · 163K eventos", pie metodológico de 1 línea por lámina (credibilidad académica).
