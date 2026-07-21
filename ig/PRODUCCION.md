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

| # | Lámina | Estado | Archivo |
|---|--------|--------|---------|
| **S1** | **Portada — "La jugada anotada"** (gol real + línea remate→gol→Copa + lupa Trionda + esqueleto en el 7) | ✅ **APROBADA** | `cap1-ciencia-datos/final/s1_portada.png` (+ versión sin título) |
| S2 | Las cámaras / computer vision (foto Ferran celebrando + tracking sutil) | ⬜ pendiente | asset: `assets/foto ferran.png` |
| S3 | Anatomía del balón-sensor (Trionda estilo AFP, corte + chip) | ⬜ pendiente | asset: `assets/balon mundial.jpeg` |
| S4 | La IA en el banquillo (tablet + siluetas analistas — democratización, PhDs) | ⬜ pendiente | — |
| S5 | Cierre/puente (opcional: anotadores invisibles o teaser cap 2) | ⬜ por definir | — |

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

## CAPÍTULO 2 — Las matemáticas del gol 🟠

Estructura definida en `divulgacion/07` (C2-A1..A5 explicación + C2-B1..B5 curiosidades). ⬜ Sin producir.
Gráficos base ya computados: xG por zonas, xG race, xT grid, momentum (en `outputs/divulgacion/`).

## CAPÍTULO 3 — Insights del torneo 🟡

Pool de 17 insights en `divulgacion/07` (C3-01..17). ⬜ Pendiente depurar a ~6 y producir.

## CAPÍTULO 4 — España 🔴

15 insights (C4-01..15) + dashboard torneo (`outputs/divulgacion/dash_spain.png`). ⬜ Sin producir.

## CAPÍTULO 5 — Messi 🩵

6 insights (C5-01..06) + dashboard (`outputs/divulgacion/dash_messi.png`). ⬜ Sin producir.

## CAPÍTULO 6 — Táctica 🟣

11 insights (C6-01..11) + experimentos de grillas (`outputs/divulgacion/experiments/`). ⬜ Sin producir.

---

## Decisiones tomadas (log)

- 2026-07-21 · S1 aprobada (v5 "la jugada anotada"). Codex CLI actualizado 0.128→0.144 (habilita gpt-image-2 + refs vía `-i`).
- 2026-07-21 · Fondos v3 "olas vivas" aprobados; verde para cap 1, violeta para cap 6 (azul descartado por Argentina).
- 2026-07-20 · Sin marca/firma: publicación en IG personal.
- 2026-07-20 · Estructura 6 capítulos fijada (didáctico separado de insights).
- Título horneado por código; copys SIEMPRE de Julián en IG.
