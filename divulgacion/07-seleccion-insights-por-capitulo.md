# Selección de insights por capítulo (para filtrar y fijar)

> Doc 8 (2026-07-20). Lista maestra: TODOS los insights documentados (docs 00-04) asignados al capítulo donde mejor funcionan. Julián marca ✅/❌ y con eso se fija el guion final.
> ⭐ = mi recomendación de imprescindible.

## CAPÍTULO 1 — El Mundial de los datos

- [ ] ⭐ **C1-01. 150M puntos de tracking por partido** — 16 cámaras ópticas por estadio; cada jugador seguido 50 veces/seg con 20+ puntos corporales. La escala del dato.
- [ ] ⭐ **C1-02. El balón es un sensor** — Adidas Trionda con IMU a 500Hz; cada toque detectado. Sin él no hay offside semiautomático.
- [ ] **C1-03. Avatares 3D** — los 26×48 jugadores escaneados en 3D; sus gemelos digitales viven dentro del sistema de arbitraje.
- [ ] ⭐ **C1-04. El offside lo canta un modelo** — SAOT v2: por primera vez las alertas van directo al juez de línea (ya no todo pasa por la sala VAR). Pose estimation + fusión de sensores.
- [ ] ⭐ **C1-05. Football AI Pro: la democratización** — IA generativa oficial para las 48 selecciones por igual; reemplazó reportes de 50-60 páginas por una interfaz consultable. La brecha ya no es acceso: es saber qué preguntar (tesis educativa).
- [ ] **C1-06. Los staffs son laboratorios** — selecciones con doctores en física, matemáticas y ML; el problema único de selecciones (poco tiempo juntos) hace la analítica más valiosa que en clubes.
- [ ] ⭐ **C1-07. Los invisibles del dato** — miles de anotadores en Manila, El Cairo, Río… etiquetan ~3.000 acciones por partido a ~$70 el partido, con deadlines de betting. La IA del Mundial también es trabajo humano.
- [ ] ⭐ **C1-08. ¿Quién puede ver estos datos?** — pirámide de acceso: FIFA (cerrado) → Opta/StatsBomb ($$$) → capa pública (WhoScored/FotMob) → open data (StatsBomb WC18/22 gratis). Nosotros: 163.688 eventos de la capa pública + modelos propios. El setup de toda la serie.
- [ ] **C1-09. ¿Y esto funciona? La evidencia histórica** — Alemania 2014 (SAP: posesión 3.4s→1.1s, campeones), Inglaterra 2018 (9/12 goles de balón parado — récord — y primera tanda ganada con método), Van Gaal/Krul 2014, dossiers de penales de Argentina 2022. Opcional: casos de club (Midtjylland, Brentford, Liverpool).
- [ ] **C1-10. La escala del formato** — 48 equipos, 104 partidos (+63%), 3 países: el torneo más largo y más instrumentado de la historia.

## CAPÍTULO 2 — Las matemáticas del gol (xG + momentum, didáctico)

- [ ] ⭐ **C2-01. Dos tiros, dos mentiras** — Ché Adams falló un tiro que era gol el 76% de las veces; Van Dijk anotó uno de 7-en-1.000. El marcador no cuenta esa historia; el xG sí. (Gancho con tiros REALES del torneo, de nuestro modelo.)
- [ ] ⭐ **C2-02. La cancha no vale lo mismo en todas partes** — conversión real por zona (datos propios): área chica ~40%, área ~15%, borde ~4%. Distancia y ángulo mandan; cabeza convierte la mitad.
- [ ] **C2-03. La trampa del penal** — un penal vale 0.79 xG: infla el número sin decir nada del juego (por eso existe npxG). Bonus dato: Messi y Mbappé fallaron penales este Mundial.
- [ ] ⭐ **C2-04. El xG cuenta el partido que no viste** — Turquía 0-1 Paraguay: 2.85 vs 0.30 xG. "Merecer" tiene gráfico: el xG race. (Enseña a leer la curva con el robo más grande del torneo.)
- [ ] ⭐ **C2-05. ¿Y los pases? El xT** — cada zona tiene valor de amenaza aprendido (Markov, entrenado con los 100K pases del Mundial). Un pase vale lo que gana en amenaza. Nuestra superficie xT = lámina académica insignia.
- [ ] ⭐ **C2-06. El momentum del broadcast, por fin explicado** — amenaza neta (xT+xG) por ventanas de 5 min. Demo: Francia 4-6 Inglaterra (10 goles cayendo sobre las olas).
- [ ] ⭐ **C2-07. La presión se puede medir** — mismos 11 metros: penales al 73% durante el partido, 62% en tandas. El peso psicológico, cuantificado. (Cierra el capítulo conectando el dato con lo humano.)
- [ ] **C2-08. El segundo tiempo mata** — 58% de los goles en el 2T; el tramo 46-60' es el más letal (53 goles); 18% de los goles en el 90+. Por qué: fatiga + cambios (20% de los goles fueron de suplentes).
- [ ] **C2-09. Anotar primero pesa** — el que abre el marcador gana el 68% y solo pierde el 16%. El fútbol es un juego de estados.

## CAPÍTULO 3 — España: la campeona que nunca sufrió

- [ ] ⭐ **C3-01. Nunca fue perdiendo** — 770 minutos, 8 partidos, jamás abajo en el marcador. La lámina ancla de la serie.
- [ ] ⭐ **C3-02. Un gol encajado en todo el torneo** — 490 min imbatida de arranque; 47 tiros recibidos en total; Unai Simón hizo 10 atajadas EN TODO el Mundial. La muralla no era el arquero: era que nunca llegaban.
- [ ] ⭐ **C3-03. No robó ni un partido** — ganó la batalla del xG en los 8. El único campeón sin deuda con el azar (contraste directo con el 2.85-0.30 del cap 2).
- [ ] ⭐ **C3-04. El día que el fútbol fue injusto** — 0-0 con Cabo Verde: 97% de field tilt (récord del torneo), 2.26 xG, cero goles. Y no cambió nada: ganó los 7 siguientes. Resiliencia al azar = mentalidad de modelo.
- [ ] ⭐ **C3-05. La red con centro de gravedad** — grafo de pases: Rodri hub (14.9% del peso + betweenness máximo); la dupla más transitada del torneo es Laporte→Rodri (140). Top-3 de pases del Mundial: 100% español.
- [ ] **C3-06. Cubarsí, el playmaker de 19 años que juega de central** — 4° creador de amenaza del torneo por xT (3.35), solo detrás de Messi/Rodri/Pedri. La arquitectura moderna: se construye desde atrás. *(Puede ir aquí o en Cap 5 con los hubs — recomiendo aquí.)*
- [ ] ⭐ **C3-07. La noche que ganó sin la pelota** — semifinal: Francia le quitó posesión (51%) y territorio (tilt 39%)… y España generó 1.86-0.46. La identidad era el control, no la pelota.
- [ ] **C3-08. El pressing inteligente** — línea defensiva más alta del torneo sostenida 8 partidos (x̄ 41.6) + #1 en offsides provocados (24) + Unai líder líbero (12)… pero presionó 66% contra débiles y 24-27% contra grandes. Identidad con cerebro.
- [ ] ⭐ **C3-09. La casa entera** — 13 goles: 7 goleadores y 8 asistidores distintos, nadie con más de 2 asistencias. Dependencia del top scorer: 38% (vs Haaland 58%, Mbappé 50%, Messi 44%). No había cable que cortar.
- [ ] ⭐ **C3-10. Merino, el cerrajero** — sus únicos dos partidos apretados los ganó en el descuento el mismo suplente: 97' vs Portugal y 93' vs Bélgica. La perfección también fue clutch.
- [ ] **C3-11. La única grieta** — el cabezazo de De Ketelaere (40', cuartos): sin error, sin contra — la única forma de golearla fue un balón aéreo una vez. Cerrada en 53 minutos.
- [ ] **C3-12. El caso Lamine: dato vs hype** — 1 gol, 0 asistencias, 27/63 regates. Y no importó: campeona sin la mejor versión de su estrella de 18 años. (Más fino que cualquier elogio.)
- [ ] ⭐ **C3-13. La final en dos lentes** — tiros 20-2, xG 2.09-0.14 ("el 1-0 más mentiroso") + momentum: positiva en 24/29 ventanas con pico exacto en la del gol (106'). Y el gol: Ferran + Nico, dos suplentes fabricando el título.
- [ ] **C3-14. Momentum del torneo: 78%** — España tuvo el flujo a favor en el 78% de las ventanas de 5' que jugó, #1 del Mundial. El dominio como estado permanente.
- [ ] **C3-15. Los debes del campeón** — 54 córners (líder) con 1 solo gol; sub-rindió su xG (13 vs 15.8). Ganó sin su mejor puntería: dominó por volumen, no por definición. (Honestidad = credibilidad.)

## CAPÍTULO 4 — Messi: la última función

- [ ] ⭐ **C4-01. Lo que dice el modelo (no la nostalgia)** — #1 generador de amenaza del Mundial: 5.40 xT, a los 39 años, sobre todos los de 24-28.
- [ ] ⭐ **C4-02. Toca menos, vale más** — el hub de Argentina era Paredes (11.4% de la red); Messi ya no toca más que nadie: la toca MEJOR que nadie (scatter volumen vs xT/pase — el gráfico-conversación de la serie).
- [ ] ⭐ **C4-03. El mapa del mago** — líder del torneo en regates (28) y en faltas recibidas (20); 8 goles, 7 de zurda; su territorio de siempre (media cancha derecha). El cuerpo cambió; el mapa no.
- [ ] **C4-04. Involucrado en todo** — 12 de los 18 goles argentinos pasaron por él (8G+4A). Y el equipo lo sabía: 3 remontadas del torneo fueron suyas (Egipto 98', semifinal con Lautaro al 95').
- [ ] ⭐ **C4-05. Los datos también escriben tragedias** — 2 penales fallados en el torneo; en la final su equipo generó 0.14 xG y Dibu hizo 11 atajadas (su mejor partido: el que perdió); Enzo expulsado al 97'. El adiós más humano posible.
- [ ] **C4-06. El contexto generacional** — Ronaldo anotó a los 41 (el más viejo); Lamine a los 18 (entre los más jóvenes). Messi en el medio, cerrando la era. Los abuelos: 11 goles y 80 años entre CR7 y él.

## CAPÍTULO 5 — La táctica bajo el microscopio

- [ ] ⭐ **C5-01. Los 5 fútboles del Mundial** — KMeans sobre 8 features encontró 5 estilos sin supervisión: dominadores, búnkeres directos, físicos, transición, atrevidos-sin-élite.
- [ ] ⭐ **C5-02. El estilo no clasifica** — campeón y subcampeón comparten cluster con Turquía y Corea (eliminadas en grupos). La ejecución dentro del estilo separa. (+ la posesión sobrevalorada: Turquía 65% — la más alta — eliminada en grupos; 4 de 5 reyes de posesión, afuera temprano.)
- [ ] ⭐ **C5-03. El mapa del pressing y su mentira** — PPDA×altura con color=ronda: Alemania presionó más que nadie (10.2) y cayó en 16avos; España top-2 sostenido. El pressing no es idea ganadora per se.
- [ ] ⭐ **C5-04. El búnker matemático de Cabo Verde** — PPDA 43.5 (permitía 43 pases por intento de robo), tiros desde 25.5m, invicto en los 90': la estrategia David llevada al límite… eliminada por autogol propio al 126'. (La historia emocional del capítulo.)
- [ ] ⭐ **C5-05. El gol sigue siendo caos** — 56% de los goles en jugadas de ≤3 pases; solo 20% de 10+ (España lideró la orfebrería: 5). En la era de la posesión, el gol vive en la transición y el balón parado (25% de los goles).
- [ ] **C5-06. Paraguay jugó otro deporte** — 2.11 pases por cadena y 10.3% de cancha/seg (el doble que cualquiera): el anti-fútbol cuantificado que eliminó a Alemania. En la otra esquina, Argentina (6.1). No hay una sola forma de competir.
- [ ] ⭐ **C5-07. Los hubs ahora son centrales** — el jugador más conectado de Francia (Upamecano), Inglaterra (Guéhi) y Brasil (Gabriel) es un central; Marruecos es el único con hub lateral (Hakimi — y cuadra con su 46% de ataques por la derecha). El fútbol cambió de arquitectura.
- [ ] **C5-08. Momentum ≠ goles** — Alemania dominó el flujo el 77% del tiempo y se fue en 16avos. Dominar no es convertir (el eco de Colombia: nunca fue perdiendo, −5.0 xG de puntería, eliminada sin perder un partido en 90').
- [ ] **C5-09. Cada equipo tiene huella digital** — Australia atacó 53% por la derecha, Noruega 47% (la autopista a Haaland), Alemania la más central; Noruega remata desde 14.5m vs Cabo Verde 25.5m. El estilo es medible hasta en la lateralidad.
- [ ] **C5-10. Camaleones vs identidades** — Inglaterra cambió de formación 21 veces (3er puesto); Marruecos 4. El 4-2-3-1 dominó y el 4-4-2 resucitó (confirmado en datos).
- [ ] ⭐ **C5-11. Cierre: la moraleja del modelador** — nuestro modelo le daba 16% a España y la señaló como value pick vs el público. No le ganamos al mercado prediciendo (nadie puede); le ganamos entendiendo dónde estaba el valor. "Con datos abiertos y método, se compite. Es lo que enseñamos." CTA Externado/Orbital.

## PÍLDORAS BONUS (stories sueltas entre capítulos, mantener el feed vivo)

- [ ] **P-01. Colombia se negó a anotar** 💛 — nunca fue perdiendo en el torneo y quedó eliminada en 16avos por penales; peor puntería del Mundial (8 goles con 13 xG; Puerta 14 tiros sin gol). Para la audiencia local.
- [ ] **P-02. Rarezas pack** — récord de autogoles (14, incluido el portero Bounou), 6 goles de saque de banda (2 en el mismo partido), Svanberg gol a los 0 min de entrar, gol más rápido (Galarza 1:04) y más tardío (Tielemans 137').
- [ ] **P-03. La doble vida de Olise** — 0 goles en 20 tiros + máximo asistidor del torneo (6). La peor y la mejor estadística en el mismo cuerpo.
- [ ] **P-04. Mbappé, cazador del segundo tiempo** — 10 goles, 8 en el 2T. [verificar: primer doble dígito desde Müller 1970]
- [ ] **P-05. Eloy Room contra el mundo** — 15 atajadas en un solo partido (récord del torneo) para el 0-0 de Curazao ante Ecuador.
- [ ] **P-06. El Azteca imparable** — 80.824 personas en sus 5 partidos, el estadio más lleno; los 3 anfitriones pasaron de grupos.

---

**Totales:** C1: 10 · C2: 9 · C3: 15 · C4: 6 · C5: 11 · Píldoras: 6 = **57 candidatos** (⭐ 28 imprescindibles sugeridos).
Al filtrar: objetivo ~5-6 láminas/capítulo → recortar a ~28-30 fijos.
