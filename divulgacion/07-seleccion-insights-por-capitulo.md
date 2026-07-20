# Selección de insights por capítulo — v2 (estructura de 6 capítulos)

> Doc 8 v2 (2026-07-20). Estructura ajustada por Julián: **1)** el Mundial de los datos · **2)** cómo se calculan los indicadores top (explicación, NO insights) + curiosidades de esos indicadores · **3)** [NUEVO] los mejores insights generales del Mundial · **4)** España · **5)** Messi · **6)** táctica avanzada.
> Se mantienen TODOS los candidatos (⭐ y sin estrella) — la depuración viene después. Julián marca ✅/❌.

---

## CAPÍTULO 1 — El Mundial de los datos (sin cambios)

- [ ] ⭐ **C1-01. 150M puntos de tracking por partido** — 16 cámaras ópticas por estadio; cada jugador 50 veces/seg, 20+ puntos corporales.
- [ ] ⭐ **C1-02. El balón es un sensor** — Trionda con IMU a 500Hz; cada toque detectado.
- [ ] **C1-03. Avatares 3D** — todos los jugadores escaneados; sus gemelos digitales dentro del sistema de arbitraje.
- [ ] ⭐ **C1-04. El offside lo canta un modelo** — SAOT v2: alertas directas al juez de línea; pose estimation + fusión de sensores.
- [ ] ⭐ **C1-05. Football AI Pro: la democratización** — IA generativa para las 48 por igual; la brecha ya no es acceso, es saber qué preguntar.
- [ ] **C1-06. Los staffs son laboratorios** — PhDs en física/matemática/ML en cuerpos técnicos de selecciones.
- [ ] ⭐ **C1-07. Los invisibles del dato** — miles de anotadores (Manila, El Cairo, Río…) a ~$70/partido, 3.000 acciones etiquetadas.
- [ ] ⭐ **C1-08. ¿Quién puede ver estos datos?** — pirámide de acceso + "nosotros: 163K eventos de la capa pública y modelos propios". Setup de la serie.
- [ ] **C1-09. ¿Funciona? Evidencia histórica** — Alemania-SAP 2014 (3.4s→1.1s), Inglaterra 2018 (9/12 balón parado + tanda con método), Krul 2014, Argentina 2022.
- [ ] **C1-10. La escala del formato** — 48 equipos, 104 partidos (+63%), 3 países.

---

## CAPÍTULO 2 — Cómo se calculan los indicadores top (didáctico puro + curiosidades)

### Parte A — La explicación (no son insights: son las láminas docentes)

- [ ] ⭐ **C2-A1. xG, la probabilidad de cada tiro** — qué es (P(gol) de cada disparo), con qué se entrena (cientos de miles de tiros históricos; el nuestro: 462K eventos StatsBomb), qué features pesan (distancia >> ángulo > parte del cuerpo > contexto), y cómo se valida (calibración: si el modelo dice 20%, deben entrar 2 de cada 10). Nivel sofisticado, lenguaje llano. *Visual: heatmap de conversión real por zona (datos propios) + anatomía de un tiro con sus features señaladas.*
- [ ] ⭐ **C2-A2. Cómo se LEE el xG: la race chart** — el acumulado por minuto cuenta "el partido que mereciste". Se enseña con un partido real del torneo (candidato: Turquía 0-1 Paraguay, 2.85-0.30 — el robo perfecto). *Visual: xG race anotada paso a paso (flechas explicando cada tramo de la curva).*
- [ ] ⭐ **C2-A3. xT: el valor de lo que NO es tiro** — el 99% de las acciones no terminan en disparo; xT le pone precio a cada zona de la cancha (cadena de Markov: el valor de una zona = qué tan probable es que desde ahí termines anotando en las próximas jugadas). Un pase vale lo que gana en amenaza. *"Esta superficie la entrenamos con los 100.000 pases del Mundial."* *Visual: nuestra grilla xT 16×12 sobre la cancha + un pase real valorado (antes/después).*
- [ ] ⭐ **C2-A4. Momentum: la gráfica famosa del broadcast, desarmada** — amenaza neta (xT de pases + xG de tiros) por ventanas de 5', suavizada. No es magia ni "sensación": es una serie de tiempo. *Visual: construcción en 3 pasos (eventos crudos → amenaza por ventana → barras divergentes) con el Francia 4-6 Inglaterra de demo (10 goles cayendo sobre las olas).*
- [ ] **C2-A5. (Opcional) La trampa del penal y el npxG** — un penal vale 0.79: infla el xG sin decir nada del juego; por eso los analistas usan npxG. Mini-lámina puente.

### Parte B — Curiosidades/absurdos DE los indicadores (con gráfico)

- [ ] ⭐ **C2-B1. El gol de 7-en-1.000 y el fallo de 76-en-100** — Van Dijk anotó un cabezazo de 0.007 xG; Ché Adams se comió un 0.76. El mismo modelo que explica el fútbol también mide sus milagros. *Visual: media cancha con ambos tiros reales y sus probabilidades.*
- [ ] ⭐ **C2-B2. La presión se puede medir** — penales en juego: 73% de conversión; en tandas: 62%. Mismos 11 metros, distinto peso en las piernas. *Visual: infografía comparativa simple (dos arcos, dos números).*
- [ ] **C2-B3. Los extremos del xG del torneo** — Japón anotó el DOBLE de lo que sus tiros valían (8 goles con 4.0 xG, +4.0); Colombia lo contrario (8 con 13.0, −5.0). La puntería existe… y regresa a la media. *Visual: barras divergentes goles−xG por selección.*
- [ ] **C2-B4. El momentum también miente** — Alemania dominó el flujo el 77% de sus ventanas… y quedó eliminada en 16avos. Dominar ≠ convertir (anticipo del cap 6). *Visual: ranking de % momentum con la ronda alcanzada como color.*
- [ ] **C2-B5. La joya que solo ve el xT** — Alistair Johnston, lateral de Canadá: top-6 mundial en generación de amenaza (3.35 xT), y nadie habló de él. Los modelos encuentran lo que el highlight ignora. *Visual: ranking xT top-12 con su nombre resaltado entre estrellas.*

---

## CAPÍTULO 3 — [NUEVO] Los mejores insights generales del Mundial

*Criterio de selección final: los más interesantes Y con gráfico espectacular detrás. Pool completo; depurar a ~6.*

- [ ] ⭐ **C3-01. Cabo Verde, la despedida más cruel** — debutante, invicto en los 90' (0-0 con el campeón incluido), eliminado por autogol propio al 126' de la prórroga contra el subcampeón. Nadie los venció. *Visual: tarjeta narrativa de sus 4 partidos + timeline del drama del 126'.*
- [ ] ⭐ **C3-02. Paraguay, el atraco perfecto** — ganó con 0.30 xG vs 2.85 (el robo del torneo), eliminó a Alemania por penales; Orlando Gill líder de atajadas (26) + el gol más rápido del Mundial (Galarza, 1:04). *Visual: xG race del robo + strip de las 26 atajadas.*
- [ ] ⭐ **C3-03. El 23% de los partidos se decidió después del minuto 90** — 54 goles en el descuento (18%), 8 en prórroga, 4 tandas. El formato 48 fue drama tardío puro. *Visual: strip de los 104 partidos coloreados por "cuándo se decidió" — un mosaico brutal.*
- [ ] ⭐ **C3-04. La dependencia goleadora** — Haaland 58% de los goles de Noruega, Mbappé 50%, Messi 44%… y el campeón: 38% con 7 goleadores. A los dependientes les cortas un cable. *Visual: lollipop de dependencia con banderas, campeón resaltado.*
- [ ] ⭐ **C3-05. El banquillo ganó el Mundial** — 20% de los goles fueron de suplentes (59); la "posición" más goleadora después de los delanteros. Undav y Lukaku con 3 c/u; Svanberg anotó 0 minutos después de entrar; y el gol del título (Ferran, asistencia de Nico) lo fabricaron dos cambios. *Visual: waffle de goles por posición con "Sub" gigante.*
- [ ] ⭐ **C3-06. Anotar primero gana el 68%** — y solo el 16% de los partidos se remontó a victoria (15 remontadas; 3 de Argentina). El fútbol es un juego de estados. *Visual: sankey/flujo "quién anota primero → cómo termina".*
- [ ] **C3-07. Récord de autogoles: 14** — el récord previo era 12 [verificar]; incluye al portero Bounou en propia puerta a los 9'… y Marruecos igual remontó 4-2. *Visual: mapa de los 14 autogoles en una cancha.*
- [ ] **C3-08. Los 6 goles de saque de banda** — 2 en el mismo partido (Turquía 3-2 USA, uno por bando); Chequia anotó 2 en el torneo así. El long throw volvió como arma seria. *Visual: cancha con las 6 trayectorias.*
- [ ] **C3-09. La doble vida de Olise** — 0 goles en 20 tiros (el gatillo más frío) + máximo asistidor del torneo (6). *Visual: panel dividido shot map estéril | flechas de asistencia.*
- [ ] **C3-10. Mbappé, cazador del segundo tiempo** — 10 goles, 8 tras el descanso; 4 dobletes; [verificar: primer doble dígito desde Müller 1970]. *Visual: strip de sus 10 goles en la línea 0-120'.*
- [ ] **C3-11. Los abuelos y el niño** — Ronaldo anotó a los 41 (el más viejo del torneo, 3 goles); Messi 8 a los 39; Lamine y 2 más anotaron a los 18. 23 años separan al goleador más joven del más viejo. *Visual: dot plot edad de cada goleador del torneo (uno por punto).*
- [ ] **C3-12. Argentina, la más bajita, llegó a la final** — 178.1 cm promedio vs Noruega 187.8 (la más alta, afuera en cuartos). *Visual: barras de altura por selección con ronda alcanzada.*
- [ ] **C3-13. Cada equipo tiene huella digital de ataque** — Australia 53% por la derecha (la más sesgada), Noruega 47% (la autopista a Haaland), Suiza/Austria zurdas. *Visual: grid de 48 mini-canchas con flechas de lateralidad — hipnótico.*
- [ ] **C3-14. Colombia se negó a anotar** 💛 — nunca fue perdiendo en el torneo y quedó eliminada por penales; peor puntería del Mundial (8 goles, 13.0 xG). *Visual: xG acumulado vs goles (la brecha de −5 como área sombreada).*
- [ ] **C3-15. Eloy Room contra el mundo** — 15 atajadas en un partido (récord del torneo) para el 0-0 de Curazao ante Ecuador. *Visual: mapa de las 15 atajadas en el arco (goal mouth).*
- [ ] **C3-16. El Azteca imparable + anfitriones** — 80.824 personas en cada uno de sus 5 partidos; los 3 anfitriones pasaron de grupos (México 4 victorias). *Visual: infografía de asistencia.*
- [ ] **C3-17. El segundo tiempo mata** — 58% de los goles en el 2T; el tramo 46-60' el más letal (53). *Visual: histograma de goles por franja con el pico señalado.* (Si no entra, absorber en C3-03.)

---

## CAPÍTULO 4 — España: la campeona que nunca sufrió (antes cap 3, sin cambios de contenido)

- [ ] ⭐ **C4-01. Nunca fue perdiendo** — 770 min, 8 partidos, jamás abajo. La ancla.
- [ ] ⭐ **C4-02. Un gol encajado en todo el torneo** — 490 min imbatida, 47 tiros recibidos, Unai Simón 10 atajadas en total.
- [ ] ⭐ **C4-03. No robó ni un partido** — ganó la batalla del xG en los 8.
- [ ] ⭐ **C4-04. El día que el fútbol fue injusto** — 0-0 Cabo Verde: tilt 97%, 2.26 xG, cero goles… y no cambió nada.
- [ ] ⭐ **C4-05. La red con centro de gravedad** — Rodri hub (14.9%, betweenness máx), Laporte→Rodri 140, top-3 pases 100% español.
- [ ] **C4-06. Cubarsí, playmaker de central a los 19** — 4° creador de amenaza del Mundial (xT 3.35).
- [ ] ⭐ **C4-07. La noche que ganó sin la pelota** — semi: 51% posesión, tilt 39%, xG 1.86-0.46.
- [ ] **C4-08. El pressing inteligente** — línea más alta del torneo sostenida (41.6) + #1 offsides provocados + intensidad negociada por rival (66% vs 24%).
- [ ] ⭐ **C4-09. La casa entera** — 7 goleadores, 8 asistidores, nadie >2 asistencias; dependencia 38%.
- [ ] ⭐ **C4-10. Merino, el cerrajero** — 97' vs Portugal y 93' vs Bélgica: los dos partidos cerrados, el mismo suplente.
- [ ] **C4-11. La única grieta** — cabezazo de De Ketelaere al 40'; cerrada en 53 minutos.
- [ ] **C4-12. El caso Lamine: dato vs hype** — 1 gol, 0 asistencias… y campeona sin su mejor versión.
- [ ] ⭐ **C4-13. La final en dos lentes** — 20-2 en tiros (xG 2.09-0.14) + momentum 24/29 con pico en el gol del 106'.
- [ ] **C4-14. Momentum 78% del torneo** — #1 en flujo a favor de todo el Mundial.
- [ ] **C4-15. Los debes del campeón** — 54 córners/1 gol; sub-rindió xG (13 vs 15.8): dominó por volumen, no por puntería.

## CAPÍTULO 5 — Messi: la última función (antes cap 4, sin cambios)

- [ ] ⭐ **C5-01. Lo que dice el modelo** — #1 en xT del Mundial (5.40) a los 39.
- [ ] ⭐ **C5-02. Toca menos, vale más** — Paredes hub (11.4%), Messi mago (scatter volumen vs xT/pase).
- [ ] ⭐ **C5-03. El mapa del mago** — líder en regates (28) y faltas recibidas (20); 7/8 goles de zurda; su territorio de siempre.
- [ ] **C5-04. Involucrado en todo** — 12 de 18 goles argentinos (8G+4A); 3 remontadas, Lautaro al 95' en semi.
- [ ] ⭐ **C5-05. Los datos también escriben tragedias** — 2 penales fallados; final con 0.14 xG de equipo, Dibu 11 atajadas en derrota, Enzo roja al 97'.
- [ ] **C5-06. El contexto generacional** — Ronaldo 41, Lamine 18, Messi cerrando la era.

## CAPÍTULO 6 — La táctica bajo el microscopio (antes cap 5, sin cambios)

- [ ] ⭐ **C6-01. Los 5 fútboles del Mundial** — KMeans/PCA encontró los estilos sin supervisión.
- [ ] ⭐ **C6-02. El estilo no clasifica** — campeón y eliminados en el mismo cluster; Turquía 65% posesión afuera en grupos.
- [ ] ⭐ **C6-03. El mapa del pressing y su mentira** — Alemania PPDA 10.2 eliminada en 16avos; España top-2 sostenido; color=ronda desmiente el eje.
- [ ] ⭐ **C6-04. El búnker matemático de Cabo Verde** — PPDA 43.5, tiros de 25.5m: la estrategia David al límite (cruce con C3-01).
- [ ] ⭐ **C6-05. El gol sigue siendo caos** — 56% de goles en ≤3 pases; balón parado 25%; España lideró la orfebrería (5 de 10+).
- [ ] **C6-06. Paraguay jugó otro deporte** — 2.11 pases/cadena, 10.3%/seg: el anti-fútbol cuantificado.
- [ ] ⭐ **C6-07. Los hubs ahora son centrales** — Upamecano/Guéhi/Gabriel; Hakimi único hub lateral (46% derecha de Marruecos).
- [ ] **C6-08. Momentum ≠ goles** — Alemania 77% del flujo, eliminada (eco de C2-B4, versión análisis).
- [ ] **C6-09. Distancia de tiro como personalidad** — Noruega 14.5m (paciente) vs Cabo Verde 25.5m (francotirador desesperado).
- [ ] **C6-10. Camaleones vs identidades** — Inglaterra 21 cambios de formación (3er puesto) vs Marruecos 4; el 4-4-2 resucitó, el 4-2-3-1 dominó.
- [ ] ⭐ **C6-11. Cierre de la serie: la moraleja del modelador** — le dimos 16% a España y era el value pick. "Con datos abiertos y método, se compite. Es lo que enseñamos." CTA Externado/Orbital.

---

**Totales v2:** C1: 10 · C2: 5 explicativas + 5 curiosidades · C3: 17 (pool a depurar → ~6) · C4: 15 · C5: 6 · C6: 11 = **69 candidatos**.
**Movimientos clave vs v1:** el didáctico quedó puro (A) con curiosidades propias (B); Cabo Verde-despedida, Paraguay-atraco, dependencia, suplentes, Olise, Mbappé, Colombia y rarezas pasaron al cap 3 nuevo; España/Messi/táctica corren un puesto (4/5/6).
