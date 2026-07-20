# Divulgación — Insights avanzados (ciencia de datos sobre el event stream)

> Doc 5 de la serie (2026-07-20). Esta tanda NO sale de conteos: sale de **modelos computados sobre los 163K eventos** — xT propio entrenado con el torneo (Markov 16×12), momentum por ventanas, PPDA real, cadenas de posesión, teoría de grafos y clustering KMeans+PCA.
> Reproducible: `scripts/divulgacion_advanced.py [chains|ppda|xt|networks|cluster]`. Artefactos para visualización en `outputs/divulgacion/`.

---

## A. xT propio — el modelo de amenaza entrenado con el Mundial 💎💎

*Método: grilla 16×12, cadena de Markov iterativa (6 iter) sobre 100K+ pases exitosos y todos los tiros del torneo. Cada pase vale xT(destino)−xT(origen). Es el mismo tipo de modelo que usan los clubes élite — entrenado 100% con nuestros datos.*

66. 💎 **Messi fue el #1 generador de amenaza por pase del Mundial (5.40 xT)** — a los 39 años, por encima de todos. No es nostalgia: es el modelo. Y el matiz precioso: **el hub de circulación de Argentina era Paredes, no Messi** (ver §C) — Messi ya no toca más la pelota que nadie; la toca *mejor* que nadie.
67. 💎 **Pau Cubarsí, central de 19 años, fue el 4° creador de amenaza del torneo (3.35 xT)** — por delante de Dembélé, Olise y todos los "10" del planeta except Messi/Rodri/Pedri. El playmaker de España jugaba de central. La construcción moderna empieza atrás — y aquí está el número.
68. **El top-5 de xT: Messi, Rodri (3.44), Pedri (3.39), Cubarsí (3.35), Olise (3.38)** — 3 de 5 son españoles y ninguno es delantero. La amenaza no la generan los que la rematan.
69. **Joya escondida:** Alistair Johnston (lateral de Canadá, 3.35 xT) — top-6 mundial en generación de amenaza. Nadie habló de él.
70. **España fue el equipo con más xT generado (27.0)**, sobre Argentina (23.9) y Francia (22.3) — el dominio no era estéril: era la mayor fábrica de peligro del torneo.

## B. Momentum — el gráfico del broadcast, calculado por nosotros 💎

*Método: amenaza (xT de pases + xG de tiros) por ventana de 5 minutos, diferencial entre equipos. Serie completa de los 104 partidos guardada en `outputs/divulgacion/momentum_all.json`.*

71. 💎 **España tuvo momentum a favor en el 78% de las ventanas de 5' que jugó — #1 del torneo.** No solo ganaba: dominaba el flujo del partido casi todo el tiempo, todos los partidos.
72. 💎 **El momentum de la final, minuto a minuto:** España positiva en 24 de 29 ventanas (83%). Pico máximo justo en la ventana del gol (min 105-110: +0.34). Argentina solo despertó dos veces: al 50-55 y al final (130'+), cuando ya perdía — el patrón clásico del que reacciona tarde. **Este es EL gráfico sofisticado de la serie** (barras divergentes estilo broadcast, pero con método explicado).
73. **El dato incómodo del momentum:** Alemania (77%) y Turquía (69%) están en el top — y se fueron temprano. Momentum ≠ goles: dominar el flujo no basta si no conviertes (puente perfecto al insight de Colombia −5 xG).

## C. Redes de pases — teoría de grafos sobre las selecciones 💎

*Método: receptor inferido por secuencia de eventos, grafo dirigido ponderado por equipo, centralidad de intermediación (betweenness) y % de centralización del hub.*

74. 💎 **La red de España es una estrella con Rodri en el centro:** hub con el 14.9% de todo el peso de la red + máximo betweenness (todo camino pasa por él). Y **la dupla más transitada de las potencias es española: Laporte→Rodri, 140 conexiones**. El "pase de la salida" tenía nombre y apellido.
75. 💎 **Los hubs del Mundial ya no son mediocampistas: son centrales.** Francia = Upamecano, Inglaterra = Guéhi, Brasil = Gabriel Magalhães — en 3 de las 7 potencias analizadas, el jugador más conectado de la red es un central (y en España el #2 es Cubarsí). El líbero moderno existe y el grafo lo delata.
76. **Marruecos es el único cuyo hub es un lateral: Hakimi (12.7%)** — toda la circulación pasa por la banda derecha. Cruza perfecto con su huella de ataque (46% por la derecha): un equipo entero construido alrededor de un carril.
77. **Argentina: Paredes hub (11.4%) y la dupla Paredes→Enzo** — la sala de máquinas que alimentaba a Messi. Menor centralización que España = red más repartida... pero amenaza concentrada en un solo genio (66).

## D. Cadenas de posesión — la anatomía del gol 💎

*Método: 40K+ cadenas reconstruidas (secuencias on-ball por equipo), con longitud, duración y velocidad de avance.*

78. 💎 **El 56% de los goles del Mundial (171 de 307) nació de jugadas de 3 pases o menos.** Solo 62 goles (20%) vinieron de cadenas de 10+. En plena era de la posesión, el gol sigue siendo caos, transición y balón parado. (Y España, fiel a sí misma, lideró los goles de orfebrería: 5 tras cadenas de 10+.)
79. 💎 **Paraguay jugó otro deporte: 2.11 pases por cadena y 10.3% de cancha avanzada por segundo** — el doble de vertical que cualquier potencia. El equipo más directo jamás medido en nuestra base + el PPDA más profundo entre cuartofinalistas. El "anti-fútbol" cuantificado... y le alcanzó para eliminar a Alemania.
80. **El espectro completo en un solo eje:** Algeria 6.2 y Argentina 6.1 pases/cadena (los pacientes) ↔ Paraguay 2.1 (el búnker con contraataque). España 5.85 pero con el shot-rate más alto por cadena (13%) — paciencia CON colmillo, no paciencia por paciencia.

## E. PPDA y altura defensiva — el pressing, medido de verdad

*Método: PPDA clásico (pases rivales permitidos en su 60% / acciones defensivas propias en el 40% alto). Altura = x media de acciones defensivas.*

81. 💎 **Cabo Verde registró un PPDA de 43.5 — el búnker más extremo del torneo** (permitía 43 pases rivales por cada intento de robo). Combinado con sus tiros desde 25.5m y su invicto en 90': la estrategia David llevada al límite matemático, y casi le alcanza.
82. **Alemania tuvo el pressing más intenso del Mundial (PPDA 10.2)... y se fue en 16avos.** España #2 (11.26) con la **línea defensiva más alta del torneo (x̄=41.6) sostenida 8 partidos**. El pressing no es una idea ganadora per se: es ganadora cuando lo acompaña todo lo demás.
83. **La final fue también un choque de alturas:** España defendía en x̄=41.6 vs Argentina 33.1 — ocho metros de cancha de diferencia en dónde empezaba cada defensa.

## F. Clustering de estilos — los 5 fútboles del Mundial (KMeans + PCA) 💎

*Método: vector de 8 features por selección (posesión/pj, precisión, % pases largos, press alto, amplitud, distancia de tiro, % centros, % pases progresivos) → KMeans k=5. Coordenadas PCA guardadas para el scatter.*

84. 💎 **El algoritmo encontró los 5 fútboles sin que nadie le dijera nada:**
   - **Los dominadores** (España, Argentina, Francia, Brasil, Alemania, Portugal, Marruecos…): posesión y presión.
   - **Los búnkeres directos** (Cabo Verde, Paraguay, Qatar, Arabia, Irak…): bloque bajo + verticalidad.
   - **Los físicos de bloque medio** (Australia, Bosnia, Ghana, Irán…).
   - **Los de transición balanceada** (Inglaterra, Bélgica, Holanda, Noruega, Suiza… el grupo más grande).
   - **Los atrevidos sin élite** (Canadá, México, Turquía, Uruguay): mucha bola y presión sin plantel top.
85. 💎 **El insight del cluster de élite: campeón y subcampeón salieron del mismo grupo estilístico… igual que Turquía y Corea, eliminados temprano.** El estilo no te clasifica — la ejecución dentro del estilo sí. (El mismo mensaje del backtest del modelo: el método importa más que la etiqueta.)

---

## Mapa de visualizaciones sofisticadas (insight → gráfico)

| # | Visual | Herramienta |
|---|---|---|
| 66-70 | **Ranking xT con barras + mini-grilla de la cancha xT** (heatmap del modelo entrenado) | mplsoccer heatmap + `xt_grid.npy` |
| 71-72 | **Momentum chart de la final** (barras divergentes 5', goles anotados, estilo broadcast) | matplotlib + `momentum_all.json` |
| 74-77 | **Pass networks comparadas España vs Argentina** (nodos=posición media, aristas=volumen, tamaño=centralidad) | mplsoccer + networkx |
| 78-80 | **Scatter directness vs pases/cadena** con los 48 equipos (Paraguay y España en las esquinas) | dataviz skill |
| 81-83 | **PPDA vs altura defensiva** (cuadrantes: pressing alto/bajo × línea alta/baja) | scatter anotado |
| 84-85 | **Mapa PCA de estilos** (48 equipos, 5 clusters coloreados, campeón marcado) | `style_clusters.json` |

**Artefactos ya generados:** `outputs/divulgacion/` → `xt_grid.npy`, `momentum_all.json` (104 partidos), `networks.json`, `style_clusters.json` (con PCA), `chains.json.gz`, `ppda.json`.
