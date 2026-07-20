# Divulgación — El Mundial más data-driven de la historia

> **Documento de insights para la serie de historias de Instagram** (divulgación de datos tácticos del Mundial 2026, con ángulo académico Externado).
> Creado: 2026-07-20. Estado: investigación de contexto ✅ → siguiente: validar con datos propios (`data/mundial.db`, 163K eventos).
> Regla editorial: **todo dato citado aquí tiene fuente**; los que generemos nosotros saldrán de la DB propia y se marcan como [PROPIO].

---

## 1. La tesis central del storytelling

**No es solo "el Mundial más tecnológico" — es el primer Mundial donde la IA fue infraestructura oficial del juego, y donde el acceso a datos se democratizó para las 48 selecciones.** El arbitraje, la preparación táctica, las alineaciones y hasta el relato mediático corrieron sobre un pipeline de datos. Y detrás de ese pipeline hay ciencia (computer vision, network science) y también personas (miles de anotadores humanos). Ese arco — *de la cancha al dato, del dato a la decisión, y quién hace el trabajo invisible* — es la serie.

---

## 2. La infraestructura oficial de FIFA (datos duros verificados)

| Dato | Detalle | Fuente |
|---|---|---|
| **16 cámaras de tracking óptico por estadio** | Generan **+150 millones de puntos de tracking por partido** | FIFA Inside |
| **Tracking 50 veces por segundo** | Cada jugador seguido con **+20 puntos corporales** (pose estimation) | FIFA / LearnOpenCV |
| **Balón conectado (Adidas Trionda)** | IMU (acelerómetro + giroscopio) a **500Hz** — detecta cada toque; base del offside semiautomático | LearnOpenCV / TechTimes |
| **Offside semiautomático (SAOT) v2** | Primera vez que las alertas de offside van **directo a los árbitros en cancha** (ya no todo pasa por la sala VAR) | FIFA Inside |
| **Avatares 3D** | Todos los jugadores fueron escaneados en 3D; sus avatares se integran al sistema de offside y análisis posicional | FIFA Inside |
| **Football AI Pro** | **Asistente de IA generativa oficial para las 48 selecciones**: reemplaza los reportes de partido de 50-60 páginas por una interfaz consultable (pre y post partido) | FIFA Inside |
| **Escala del torneo** | 48 equipos, **104 partidos** (63% más que los 64 de antes), 3 países sede | FIFA |

**El insight de democratización (clave para el relato):** FIFA dio a las 48 selecciones acceso *igualitario* a las capacidades de análisis — una federación pequeña sin departamento de analytics recibió las mismas herramientas (Football AI Pro, tracking 3D, recreaciones de partido) que España o Argentina. La brecha ya no es de acceso al dato, sino de **capacidad de hacerle buenas preguntas** ← puente directo a la tesis educativa (lo que enseñamos en la universidad: el diferencial es el criterio analítico, no la herramienta).

---

## 3. Cómo lo usaron las selecciones

- **Perfil del staff:** las selecciones llegaron con analistas propios, software a la medida e IA; hoy los cuerpos técnicos incluyen **doctores en física, matemáticas y machine learning** (Rest of World / Medium CS series).
- **Scouting de rivales:** formaciones preferidas, tendencias ofensivas, vulnerabilidades defensivas, estructuras de pressing, rutinas de balón parado y comportamientos individuales — todo desde plataformas de análisis (análisis estándar pre-partido).
- **El problema específico de selecciones (vs clubes):** tiempo juntos limitadísimo — no hay meses para implantar un sistema. La analítica acorta ese ciclo: lectura rápida de rendimiento, química y rival (Medium CS series). *Ángulo docente: es un problema de aprendizaje con pocos datos/tiempo — transfer learning organizacional.*
- **España como caso:** los análisis de clusters de pases revelan un estilo más directo del que se le atribuye, priorizando a Nico Williams y Lamine Yamal como receptores de desequilibrio (Northeastern/ScoutingStats). Se cruza con nuestra narrativa de "posesión con verticalidad letal".
- **Selectividad del pressing:** la tendencia táctica del torneo — presión por oleadas con *triggers* (mal control, pase hacia atrás, trampa de banda, saque del portero) en vez de presión constante — es en sí misma una decisión informada por datos de eficiencia de pressing (Total Football Analysis / Football Express).
- **Circulación como métrica de intención:** promedio del torneo **14.79 pases por minuto de posesión (PPM)**; los de circulación más rápida: **Portugal 17.5, Argentina 17.1, España 17.0, Alemania 17.0** — y el matiz: Alemania y Holanda (transicionales puras) cayeron en 16avos → el dato sin gestión de partido no clasifica (Tactical Football Analysis).

---

## 4. El ángulo académico (network science — puente universitario directo)

El **Network Science Institute de Northeastern** (grupo NetSI Sport, dir. Brennan Klein; postdoc Maddalena Torricelli) analizó el Mundial con ciencia de redes, con partnership de datos StatsBomb en tiempo real:

- Trabajan con **3.000-4.000 eventos granulares por partido** (pases, conducciones, presiones, xG) — el mismo orden de magnitud de nuestros datos [PROPIO: WhoScored nos da ~1.500-2.000 eventos on-ball por partido].
- **Motivos de estilo por selección** desde grafos de pases: Australia = pases largos desde el arquero; Suiza = pase corto; **España = pases laterales filosos a lo ancho** para desorganizar bloques.
- Sobre **13.000+ partidos (2020-2025)**: el volumen y la precisión de pases vienen subiendo sostenidamente — el fútbol mundial converge hacia más control técnico.
- Su hipótesis sobre el formato de 48: más espacio para innovación y upsets. [PROPIO: nuestro repo lo confirmó — Paraguay eliminó a Alemania por penales, Noruega eliminó a Brasil, y nuestro backtest ya mostraba varianza récord.]

*Uso en el storytelling: "esto no es solo fútbol — es un problema de grafos. El pase es una arista, el jugador un nodo, y la centralidad de Rodri se mide igual que la de un router en una red".*

---

## 5. El lado B: los trabajadores invisibles del dato (ángulo Data y Derecho)

La historia que casi nadie cuenta (Rest of World) — y que conecta con tus cursos de Data y Derecho en el Externado:

- Detrás del "AI-driven World Cup" hay **miles de anotadores humanos** que etiquetan cada pase, tackle y disparo — hasta **3.000 acciones por partido**, 3-4 horas de trabajo por partido.
- Están concentrados en el **Sur Global**: Manila, El Cairo, Chennai, Ternopil, Río de Janeiro, Camboya, India — mientras el trabajo analítico de alto valor queda en los centros ricos.
- Condiciones: un freelancer en Río gana **~USD $70 por partido** (más transporte), con riesgo de no pago por entregas tardías; deadlines apretados porque el dato alimenta betting en tiempo real.
- Pocas firmas controlan el mercado del dato futbolístico (ej. Impect, alemana, con su unidad Packing Sports en Manila).

*Este es el insight diferenciador de la serie: la IA del Mundial también es trabajo humano precarizado e invisible. Nadie más va a contar esto en una historia de Instagram de fútbol.*

---

## 6. Nuestro lugar en la historia [PROPIO]

Nosotros somos **consumidores independientes de ese mismo pipeline**: recolectamos 163.688 eventos con coordenadas de los 104 partidos (event data Opta vía WhoScored) + 462K eventos históricos StatsBomb + Elo + 3 mercados de predicción, construimos un modelo Elo→Dixon-Coles y lo backtesteamos honestamente:

- El modelo proyectó **exactamente las dos semifinales reales** (Francia-España, Argentina-Inglaterra).
- El **pick de valor** (España, leverage 1.31 vs el público) **fue el campeón** — validación empírica de que el edge estaba en la estrategia, no en out-predecir al mercado.
- RPS 0.153 a nivel partido ≈ nivel casas de apuestas — con datos 100% públicos y gratuitos.
- → Mensaje docente: *"con datos abiertos y método, un equipo de dos personas en Bogotá empata técnicamente con la industria"*. Doc completo: [../docs/15-postmortem-final.md](../docs/15-postmortem-final.md).

---

## 7. Datos pendientes de validar con nuestra DB (backlog para las siguientes historias)

| # | Claim externo | Validación propia posible |
|---|---|---|
| 1 | España encajó solo 1 gol en el torneo (récord) | ✅ trivial: query a `matches` — **verificar el número exacto** antes de publicar |
| 2 | PPM España 17.0 / torneo 14.79 | Reproducible aprox. con nuestros eventos (pases / minutos de posesión) |
| 3 | Pressing selectivo (bloque medio + oleadas) | High press % por selección desde coordenadas de acciones defensivas |
| 4 | España = "pases laterales filosos" (NetSI) | Distribución de ángulos de pase de España vs resto |
| 5 | Goles desde fuera del área al alza | % goles fuera del área 2026 vs StatsBomb WC2018/22 |
| 6 | Final: xG 2.34-0.38, tiros 20-2 | Nuestro event data de la final + shot map |
| 7 | Rodri hub de España | Pass network + centralidad (grafo) por partido |
| 8 | Balón parado decisivo | % goles de córner/tiro libre/penal en el torneo |

---

## 8. Fuentes

- FIFA Inside (innovación WC2026): https://inside.fifa.com/innovation/news/offside-decisions-referee-body-cams-innovation-world-cup-2026
- LearnOpenCV — tecnología de offside 2026: https://learnopencv.com/world-cup-2026-offside-technology/
- TechTimes — el mayor test tecnológico en vivo: https://www.techtimes.com/articles/318259/20260611/world-cup-2026-becomes-techs-biggest-live-test-ai-offside-smart-ball-player-data.htm
- Northeastern NetSI — network science y el Mundial: https://news.northeastern.edu/2026/06/03/soccer-analytics-world-cup-network-science/ y https://news.northeastern.edu/2026/06/09/world-cup-analysis-teams/
- Rest of World — los data workers del fútbol: https://restofworld.org/2026/fifa-world-cup-ai-data-workers/
- Tactical Football Analysis — transiciones y PPM: https://tacticalfootballanalysis.com/world-cup-2026-transition-football-tactics-data-analysis/
- Total Football Analysis — analytics spotlight: https://totalfootballanalysis.com/thought-analysis/from-xg-to-pressing-efficiency-analytics-spotlight-on-the-2026-world-cup
- Coaches' Voice — táctica de la final: https://learning.coachesvoice.com/cv/spain-argentina-2026-world-cup-final-tactical-analysis/
- Serie técnica (Medium, CS teacher) — tracking y plataformas: https://parashar--manas.medium.com/understanding-fifa-world-cup-2026-technology-part-5-ai-powered-player-tracking-c4ac09039311
