# Divulgación — Cómo usan los datos los equipos modernos y las métricas que importan

> Doc 2 de la serie (2026-07-20). Complementa [00-insights-mundial-data-driven.md](00-insights-mundial-data-driven.md).
> Referencia técnica profunda (fórmulas, SQL, umbrales por posición): skill `football-analytics` en Orbital OS.

---

## 1. Cómo usan los datos los equipos modernos (los 6 casos de uso)

| Caso de uso | Qué se hace | Ejemplo concreto |
|---|---|---|
| **1. Recruitment / fichajes** | Modelos de valoración: rendimiento subyacente (xG, xA, progresión) ajustado por liga, edad, contexto — comprar lo que el mercado no ve | Liverpool fichó a Salah cuando su reputación estaba golpeada tras el Chelsea: los datos decían élite (ver doc 00 §6c) |
| **2. Scouting del rival** | Formaciones, triggers de pressing, rutinas de balón parado, tendencias individuales (¿el lateral cierra el pie?) | Estándar pre-partido en el Mundial: dossiers por rival con plataformas de video+datos |
| **3. En vivo (banquillo)** | Desde 2018 FIFA permite tablets y comunicación analistas→banquillo: xG live, mapas de pressing, fatiga | En WC2026, **Football AI Pro** consultable pre/post; el análisis in-match del cuerpo técnico decide cambios y ajustes |
| **4. Post-partido** | Reemplazo del "ver el video 90 min": clips indexados por evento + métricas de fase | FIFA pasó de reportes de 50-60 páginas a interfaz de IA consultable |
| **5. Carga física / lesiones** | GPS y acelerometría: distancia de alta intensidad, sprints, carga aguda:crónica → rotaciones | Crítico en WC2026: 104 partidos, calor, viajes entre 3 países — la gestión de plantilla fue tendencia declarada del torneo |
| **6. Jugadas específicas entrenables** | Balón parado y penales como "laboratorios" de ROI: pocas variables, repetibles | Inglaterra 2018 (9/12 goles de balón parado), Argentina 2022 (dossiers de penales) — doc 00 §6c |

**El insight transversal:** el dato no reemplaza al entrenador — le cambia la pregunta. De "¿cómo nos fue?" (resultado, ruidoso) a "¿qué tan bien jugamos?" (procesos, estable). El resultado de UN partido es ruido; los procesos predicen los siguientes diez.

---

## 2. La pirámide de métricas (de contar a predecir)

```
Nivel 4 — FÍSICO-TÁCTICO (tracking): compacidad, altura de línea, sprints con contexto
Nivel 3 — TÁCTICO (evento+posición): PPDA, field tilt, line breaks, fases de juego
Nivel 2 — PROBABILÍSTICO (modelos):   xG, xA, xT/EPV, momentum
Nivel 1 — DESCRIPTIVO (conteos):      posesión, tiros, pases, córners
```
La revolución fue pasar del nivel 1 (lo que pasó) a los niveles 2-3 (qué tan probable era y por qué pasó). La posesión sola ya no dice nada — este Mundial lo confirmó: lo que importa es *qué tan rápido y hacia dónde* circula (PPM, doc 00 §3).

---

## 3. Las métricas clave y cómo se calculan

### 3.1 xG (Expected Goals) — la probabilidad de que un tiro sea gol

- **Qué es:** modelo entrenado sobre cientos de miles de tiros históricos que asigna a cada disparo su probabilidad de gol según: **distancia** (lo más importante), **ángulo**, parte del cuerpo (cabeza convierte ~50% menos), tipo de asistencia, estado del juego (contras ~+20%).
- **Cómo se calcula:** regresión logística o gradient boosting. Features geométricas + contexto → P(gol). Ej. simplificado: `xG = 1/(1+e^(0.1·dist − 2.5 + 0.5·ángulo))`.
- **Referencias de conversión real** (de nuestra DB Premier/skill): área chica ~40%, área ~15%, fuera del área ~4%, "BigChance" 36.6%.
- **Cómo se usa:** goles−xG sostenido = definición élite o suerte que regresa (la señal que nos advirtió de Francia, doc 00). xG por tiro = calidad de selección de tiro.
- **[PROPIO]** Entrenamos un xG nativo WhoScored (Brier 0.080) con 462K eventos StatsBomb de WC2018/22. La final: **España 2.34 xG vs Argentina 0.38** (Coaches' Voice) — verificable con nuestro shot map.
- **Trampa a explicar en la historia:** un penal (xG ~0.79) infla el xG sin decir nada del juego. Siempre separar xG de penal ("npxG").

### 3.2 Momentum — el gráfico de "quién domina ahora"

- **Qué es:** el chart de barras del broadcast (arriba/abajo del eje) que muestra dominio por ventanas de tiempo. NO es una métrica oficial única — cada proveedor lo calcula distinto, pero la receta general es:
- **Cómo se calcula:** ventana móvil (ej. 5 minutos) sobre una **métrica de amenaza** — típicamente xT o xG generado por cada equipo en esa ventana → `momentum(t) = amenaza_A(t−5,t) − amenaza_B(t−5,t)`, suavizado (media móvil exponencial). Barras positivas = domina A.
- **[PROPIO]** Lo podemos calcular exacto con nuestros eventos: xT por ventana de 5' → momentum chart de la final propia (¿cuándo dominó Argentina, si alguna vez?).

### 3.3 xT / EPV (Expected Threat / valor de posesión) — el valor de CADA acción

- **Qué es:** resuelve el problema de que el 99% de las acciones no son tiros. Divide la cancha en una grilla (12×8 = 96 zonas); cada zona tiene una probabilidad de terminar en gol en las próximas N acciones.
- **Cómo se calcula:** cadena de Markov iterativa: `xT(zona) = P(tirar)·P(gol|tiro) + P(mover)·Σ P(mover a j)·xT(j)`. El valor de un pase = `xT(destino) − xT(origen)`.
- **Cómo se usa:** ranking de jugadores por amenaza generada sin necesidad de que tiren (el metric que revela a los "motores ocultos"). Variantes pro: VAEP (ML sobre secuencias), OBV (StatsBomb).

### 3.4 PPDA — la intensidad del pressing en un número

- **Fórmula:** `pases que permites al rival en su 60% del campo / tus acciones defensivas (tackles+intercepciones+faltas) en ese territorio`. Menos = presionas más.
- **Umbrales:** <8 pressing extremo (Klopp/Guardiola peak) · 8-10 alto · 10-14 medio · >14 bloque bajo.
- **El matiz WC2026:** el pressing fue **selectivo** (por triggers: mal control, pase atrás, trampa de banda). PPDA bajo ya no significa correr 90 minutos sino elegir bien las oleadas — "timing, spacing y conexión entre jugadores" (zone14).
- **[PROPIO]** proxy calculable: % de acciones defensivas en campo rival por selección.

### 3.5 Field tilt — dominio territorial real

- **Fórmula:** `tus pases en el último tercio / (tuyos + los del rival en último tercio) × 100`.
- **Por qué mata a la posesión:** puedes tener 55% de posesión en tu propia cancha (inútil) y 35% de field tilt (te están dominando). España 65% posesión + paliza territorial en la final = ambas altas → dominio genuino.

### 3.6 Las métricas oficiales FIFA (Enhanced Football Intelligence)

El diferencial de los Mundiales modernos: FIFA desarrolló (equipo High Performance, liderado por **Arsène Wenger**) su propio set de **11 métricas oficiales** sobre el tracking de 50Hz, estrenadas en Qatar 2022 y expandidas en 2026:

| Métrica EFI | Qué mide |
|---|---|
| **Line breaks** | Cuántas veces un pase/conducción rompe una **unidad** defensiva (defensa/medio/ataque) y si fue por dentro, por fuera o por arriba — la vía cuantitativa a la "verticalidad" |
| **Phases of play** | % del tiempo en cada una de **9 fases con balón** (build-up, progresión, último tercio, contraataque…), **9 sin balón** (bloque bajo, counter-press, recovery…) y 5 de balón parado — la huella táctica de un equipo en un gráfico |
| **Defensive line height & team length** | Altura de la línea y compacidad (distancia entre líneas) — la métrica que zone14 destaca como LA que los entrenadores deben mirar: sin compacidad no hay pressing |
| **Pressure on the ball** | Presión real sobre el portador (proximidad+dirección de rivales) — distingue "parecer intenso" de "molestar de verdad" |
| **Ball recovery time** | Segundos promedio para recuperar el balón tras perderlo — el KPI del counter-press |
| **Forced turnovers, final third entries, receptions behind lines, possession control, team shape, xG** | Pérdidas forzadas, entradas al último tercio (y su TIPO: pase al pie vs centro esperanzado vs conducción), recepciones a espalda de líneas, etc. |

**El insight para la serie:** cuando el comentarista dice "España rompe líneas", desde 2022 eso ES un número oficial de FIFA. Y las "fases de juego" son exactamente lo que un modelo de ML clasificaría — Wenger armó un equipo de data scientists para taxonomizar el fútbol.

### 3.7 Lo físico con contexto (nivel 4)

- Ya no importa el kilometraje total: "un jugador corre 12 km sin cambiar el partido; otro corre menos pero hace 5 acciones de alta intensidad decisivas" (zone14). Lo que se mide: **sprints por zona y momento**, distancia de alta intensidad (>19.8 km/h y >25.2 km/h), aceleraciones.
- En WC2026 esto alimentó la narrativa de **squad management**: rotaciones planificadas por datos de carga en el torneo más largo (104 partidos) y caluroso de la historia.

---

## 4. El mapa métrica → pregunta del entrenador (cierre de la historia)

| Pregunta del DT | Métrica que la responde |
|---|---|
| ¿Creamos ocasiones de verdad o tiramos por tirar? | xG por tiro, npxG |
| ¿Quién genera juego aunque no tire? | xT / xG buildup |
| ¿Nuestro pressing molesta o solo corre? | PPDA + pressure on the ball + ball recovery time |
| ¿Dominamos o solo tenemos la pelota? | Field tilt + line breaks + PPM |
| ¿Somos rompibles a la espalda? | Altura de línea + recepciones tras línea + compacidad |
| ¿A quién roto hoy? | Carga alta intensidad acum. + sprint maps |
| ¿Cómo nos ganan? | Phases of play del rival + forced turnovers por zona |

---

## 5. Backlog [PROPIO] — qué podemos calcular nosotros con mundial.db

1. **xG race + shot map de la final** (validar el 2.34−0.38).
2. **Momentum chart propio de la final** (xT por ventanas de 5').
3. **Proxy de line breaks de España** (pases que cruzan >20 unidades de x con receptor entre líneas).
4. **PPDA/high-press % de las 48 selecciones** → scatter pressing vs avance en el torneo.
5. **PPM (pases por minuto de posesión)** — reproducir el 17.0 de España.
6. **xT ranking de jugadores del Mundial** → ¿quién fue el motor oculto de España? (hipótesis: no fue Lamine — verificar).

---

## 6. Fuentes

- FIFA — Enhanced Football Intelligence (release oficial + PDF explicativo): https://inside.fifa.com/innovation/media-releases/fifa-to-introduce-enhanced-football-intelligence-at-fifa-world-cup-2022-tm · https://www.fifatrainingcentre.com/media/native/world-cup-2022/Enhanced%20Football%20Intelligence%20EN.pdf
- zone14 — stats que los entrenadores deben mirar en WC2026: https://zone14.ai/en/blog/football-data/world-cup-2026-football-statistics/
- SVG — cómo se visualizó EFI en broadcast: https://www.sportsvideo.org/2022/12/01/2022-fifa-world-cup-enhanced-football-intelligence-visualizes-new-statistics-in-new-ways/
- Marco Cardinale — "When FIFA Opened the Data": https://marcocardinale.com/2026/06/26/when-fifa-opened-the-data-how-the-world-cup-is-changing-the-way-we-understand-the-game/
- Definiciones y umbrales técnicos: skill interna `football-analytics` (Orbital OS) — xG, xT, PPDA, field tilt, per-90, benchmarks por posición.
