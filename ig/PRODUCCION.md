# Producción Serie IG — Inventario y estado

> Tracker vivo de la serie "El Mundial de la ciencia de datos". Se actualiza con cada lámina.
> Última actualización: 2026-07-21.

## Pipeline validado (la fórmula)

1. Fondo por capítulo: `python ig/assets/make_fondo.py [1-6]` (olas vivas, color por capítulo)
2. Ilustración: `codex exec -i <fondo> -i <refs...> -- "<prompt>"` + rescate de cache (~70s)
   - Escena real como protagonista (referencias respetadas)
   - Una línea de datos conectando elementos con sentido narrativo
   - Callouts estilo agencia (lupas) para objetos técnicos
   - Overlays mínimos · CERO texto en codex
3. Título/tipografía por código (PIL + Barlow Condensed, `ig/assets/fonts/`)
4. Copys: los escribe Julián directo en IG (borradores aquí)
5. Export final 1080×1920 → `ig/capN-*/final/`

## Colores por capítulo

1 🟢 verde esmeralda · 2 🟠 naranja · 3 🟡 dorado · 4 🔴 rojo→gualda (España) · 5 🩵 celeste (Messi) · 6 🟣 violeta

---

## CAPÍTULO 1 — El Mundial de la ciencia de datos 🟢

**Estructura fijada (2026-07-21): portada + 3 láminas de dato, en este orden:**

| # | Lámina | Dato central | Estado | Archivo |
|---|--------|--------------|--------|---------|
| **S1** | **Portada — "La jugada anotada"** (gol real + línea remate→gol→Copa + lupa Trionda + esqueleto en el 7) | — | ✅ **APROBADA** | `cap1-ciencia-datos/final/s1_portada.png` (+ versión sin título) |
| ~~S2-S5~~ | ~~Balón / cámaras / tecnificación / cierre~~ — **DESCARTADAS: la portada cubre el capítulo** (decisión 2026-07-21). Los datos van en los copys de la S1 | — | ✖️ cerrado | — |

### Copys S1 (borradores — elegir al publicar)

- **Principal (opción narrativa, recomendada):** "El gol que definió el Mundial duró 3 segundos. Medirlo tomó 16 cámaras, un sensor dentro del balón y 150 millones de datos."
- Alt tesis: "Nunca hubo tantas herramientas para entender el fútbol. Este fue el primer Mundial donde cada jugada quedó convertida en datos."
- Alt provocadora: "Viste el gol. El sistema vio otra cosa: 29 puntos del cuerpo, la curva del balón a 500Hz y la probabilidad exacta de que entrara."
- Alt personal: "Llevo meses metido en los datos de este Mundial. Lo que encontré da para una serie. Empecemos por el principio: nunca un torneo se midió tanto."
- Micro-copy junto a la lupa: "sí, el balón lleva un chip →"
- Cierre/teaser: "¿de dónde salen estos datos? →"

### Copys S2-S4 (borradores previos)

- S2 cámaras: "Mientras Ferran definía el Mundial al 106', 16 cámaras lo medían 50 veces por segundo — cada jugador convertido en 29 puntos en el espacio." (decidir 29 vs 20+ puntos)
- S3 balón: "El Trionda lleva un sensor que reporta 500 veces por segundo: dónde, cuándo y cómo fue cada toque. Sin él no existiría el offside automático."
- S4 IA: "Y por primera vez las 48 selecciones tuvieron la misma IA de análisis. Detrás de cada táctica: equipos con doctorados en física y estadística."

---

## CAPÍTULO 2 — Las matemáticas del gol (fondo verde, continuidad con cap 1)

**Decisión final (2026-07-21): UNA sola lámina con los 3 indicadores** — "Los 3 lentes" (se descartó 1 lámina por indicador y se descartaron datos puntuales: la lámina evoca, los copys explican).

| # | Lámina | Estado | Archivo |
|---|--------|--------|---------|
| **S2** | **"Los 3 lentes"** — 3 escenas apiladas conectadas por línea punteada: Messi rematando (xG, trayectoria+retícula) → peinada de Nico vista elevada (xT, degradado de valor+flecha) → panel MATCH MOMENTUM broadcast fiel (Paraguay-Francia, banderas y todo) | ✅ **APROBADA** | `cap2-matematicas/final/s2_tres_lentes.png` |

### Copys Lámina 2 cap 3 (Julián en IG)

- **Arriba (dependencia):** "¿De quién dependen los goles de un equipo? Haaland hizo el 58% de los de Noruega. Mbappé el 50% de Francia. Messi el 44% de Argentina. ¿Y el campeón? Nadie pasó del 38%: España tuvo 7 goleadores distintos. A los dependientes les cortas un cable — a España había que apagarle la casa entera."
- **Abajo (redes):** "¿Y de quién depende el JUEGO? Cada red muestra las conexiones de pase reales del torneo: España es una telaraña con Rodri al centro. Paraguay una red deshilachada (8 conexiones fuertes vs 35 de España). Países Bajos gira alrededor de un solo sol. Marruecos vive en el carril de Hakimi. Argentina es la democracia: Paredes y Enzo empatados como cerebro. Y Colombia, la red elástica de Davinson."
- Cierre: "el campeón no dependía de nadie — ni en goles ni en juego →"

### Copys Lámina 1 cap 3 (Julián en IG — uno por mitad)

- **Banquillo (junto a la escena):** "El 20% de los goles del Mundial los hicieron suplentes. Si el banquillo fuera una selección, habría sido de las máximas goleadoras del torneo (59 goles). Hasta el gol del título lo fabricaron dos cambios: Nico asistió, Ferran definió."
- **Reloj (junto al dial):** "¿Y cuándo caen esos goles? El 23% de los partidos se decidió DESPUÉS del minuto 90: 54 goles en el descuento, 8 en la prórroga y 4 tandas de penales. Cada punto rosa es un gol real del 90'+. El Mundial se jugó al final."
- Cierre/teaser: "los datos del final del partido son otra dimensión →"

### Copys S2 (definiciones — Julián los escribe en IG, uno por franja)

- **xG (goles esperados):** "La probabilidad de que un tiro termine en gol, según distancia, ángulo, parte del cuerpo y cómo llega el balón. Se calcula con modelos entrenados con cientos de miles de tiros históricos. Un xG de 0.20 = ese tiro entra 20 de cada 100 veces."
- **xT (amenaza esperada):** "¿Y los pases? El 99% de las acciones no son tiros. El xT le pone valor a cada zona de la cancha: cada pase que acerca el balón a zonas más peligrosas suma amenaza, aunque no termine en tiro. Así se mide el peligro invisible."
- **Momentum:** "La gráfica que ves en cada transmisión: amenaza generada por ventanas de 5 minutos — quién manda, minuto a minuto. Ojo: dominar no es ganar. Esa de ahí es Francia aplastando a Paraguay en cuartos… ganó apenas 1-0."
- Cierre/teaser: "Con estos 3 lentes vamos a releer todo el Mundial. →"

### Notas de producción (aprendizajes)

- Codex RECHAZA nombrar figuras públicas ("Messi") → describir como "delantero albiceleste dorsal 10, rostro sin detalle" y pasa.
- Edición quirúrgica funciona: pasar la lámina aprobada como ref 1 + "reproduce exactamente con UNA modificación" preservó las escenas al cambiar solo el panel.
- Texto corto en codex (MATCH MOMENTUM, 0'-45') sale nítido; textos largos NO.
- `codex exec` en background necesita `< /dev/null` (si no, se cuelga leyendo stdin).

Reserva C2-B (curiosidades, por si el capítulo pide más historias): Van Dijk 7-en-1000, Adams 76-en-100, penales 73% vs 62%, Japón +4/Colombia −5, momentum Alemania 77% y eliminada.
Gráficos reales ya computados por si se usan: xG por zonas, xG race, xT grid, momentum 104 partidos (`outputs/divulgacion/`).

## CAPÍTULO 3 — Insights del torneo 🟡

**Selección de Julián (2026-07-21):**

| # | Insight | Gráfico | Estado |
|---|---------|---------|--------|
| C3-04 + C3-13 | **LÁMINA 2 — "¿De quién depende un equipo?"**: dependencia 2×2 (58→38%, España con chips de 7 goleadores) + redes 3×2 (6 arquetipos) — estilo neón transparente + sombras orgánicas + río de partículas divisor, charts a máximo tamaño (v7), compuesta 100% por código (charts píxel-perfecto; test codex descartado por falsificar datos) | ✅ **APROBADA** → `cap3-insights-torneo/final/lamina2_dependencia_redes.png` (compose: `viz/compose_lamina2.py`) | ✅ |
| C3-05 + C3-03 | **LÁMINA 1 — "El Mundial se decidió al final"**: escena del banquillo (DT + tablet glow + partículas + hilo dato→decisión) + reloj dial 0'→130' con los 62 goles del 90'+ ardiendo y 4 estrellas de tandas. Título horneado "ALGUNOS DATOS INTERESANTES" (única con título del cap) | ✅ **APROBADA** → `cap3-insights-torneo/final/lamina1_banquillo_reloj.png` (+ sin título). Dial: `viz/reloj.py` | ✅ |

Resto del pool (C3-01,02,06..12,14..17) queda en reserva en `divulgacion/07`.

## CAPÍTULO 4 — España 🔴

15 insights (C4-01..15) + dashboard torneo (`outputs/divulgacion/dash_spain.png`). ⬜ Sin producir.

## CAPÍTULO 5 — Messi 🩵

6 insights (C5-01..06) + dashboard (`outputs/divulgacion/dash_messi.png`). ⬜ Sin producir.

## CAPÍTULO 6 — Táctica 🟣

11 insights (C6-01..11) + experimentos de grillas (`outputs/divulgacion/experiments/`). ⬜ Sin producir.

---

## Decisiones tomadas (log)

- 2026-07-22 · Cap 3 CERRADO: lámina 2 aprobada (neón por código — pipeline nuevo para láminas con charts: transparencia + sombras orgánicas + divisor).
- 2026-07-21 · Cap 1 cerrado con solo la portada (los 3 datos van en copys). Cap 3 en producción.
- 2026-07-21 · S2 "Los 3 lentes" aprobada (v3): cap 2 consolidado en UNA lámina, fondo verde de continuidad, panel broadcast fiel.
- 2026-07-21 · S1 aprobada (v5 "la jugada anotada"). Codex CLI actualizado 0.128→0.144 (habilita gpt-image-2 + refs vía `-i`).
- 2026-07-21 · Fondos v3 "olas vivas" aprobados; verde para cap 1, violeta para cap 6 (azul descartado por Argentina).
- 2026-07-20 · Sin marca/firma: publicación en IG personal.
- 2026-07-20 · Estructura 6 capítulos fijada (didáctico separado de insights).
- Título horneado por código; copys SIEMPRE de Julián en IG.
