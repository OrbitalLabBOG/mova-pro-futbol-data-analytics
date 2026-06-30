# Apuestas deportivas cuantitativas — investigación y estrategia (Mundial 2026)

> **Investigado:** 2026-06-29 (lunes), torneo en Ronda de 32 / octavos.
> **Pregunta de fondo:** ¿es posible ganar dinero de forma *consistente* apostando al Mundial con algoritmos, con nuestros datos, o en Polymarket? ¿Hay alguna estrategia con valor esperado (+EV) sostenible?
> **Método:** 13 investigadores en paralelo (matemática, referentes, fuentes de datos, exchanges, in-play, históricos CLV, value/arb tools, Polymarket strategy, ML papers, panorama WC2026). Todas las URLs verificadas vía búsqueda/fetch; lo no confirmado de fuente primaria va marcado. Informes crudos en `scratchpad/research-*.md` de la sesión.

---

## 0. TL;DR honesto

1. **Predecir mejor que el mercado en mercados líquidos es casi imposible.** Nuestro propio backtest ya lo decía (RPS ≈ casas). La literatura académica lo confirma: la **línea de cierre** (especialmente Pinnacle de-vigada) es un estimador de probabilidad casi insuperable a escala. Apostar direccional "quién gana" = EV negativo tras el vig.

2. **El edge real NO es predictivo, es estructural.** Los que ganan de verdad atacan el *mercado menos eficiente* (handicap asiático, pools pari-mutuel, props in-play), modelan probabilidad verdadera y **solo apuestan en la divergencia** — y su verdadero foso es el **acceso/distribución** (poder colocar dinero sin que te limiten), no las matemáticas.

3. **Para retail con algoritmos hoy hay tres frentes con +EV genuino:**
   - **Value betting / arbitraje** en casas blandas → real pero **~2-4% de yield**, y te **limitan/banean ("gubbing")** antes de extraer volumen. Edge real, extractable bajo.
   - **Closing Line Value (CLV)** como brújula → la única prueba honesta de si tienes edge. *Antes de arriesgar un peso, mide si le ganas al cierre de Pinnacle.*
   - **Polymarket/Kalshi: market making + arbitraje + resolution-edge** → el frente más prometedor para nosotros, **porque no requiere predecir mejor**. El Mundial trajo una ola de retail ($1.6B apostado a colas <1%) = la contraparte ideal.

4. **El Mundial es el mejor momento** para market making/arb en Polymarket (244 mercados, ~$352M de liquidez, +300% de volumen), y el **peor** para apostar direccional al campeón (favoritos bien preciados por smart money + bots).

5. **Caveat duro:** en Polymarket **84% de los traders pierden**; <0.04% capturan >70% de las ganancias. El retail *es* la liquidez. Y la legalidad/acceso de Polymarket/Kalshi desde **Colombia no está verificada** — requiere asesoría legal antes de operar.

---

## 1. La matemática del edge

### 1.1 EV y el vig (por qué la casa gana por construcción)
La casa no necesita predecir mejor que tú: incorpora un **margen (vig/overround)** en los precios de modo que las probabilidades implícitas sumen **>100%**.

- **Fórmula exacta:** para cuota decimal `d` y stake unitario, `EV = p·(d−1) − (1−p) = p·d − 1`. Por tanto **+EV ⇔ p > 1/d** (tu probabilidad supera la implícita del precio).
- Moneda justa: 2.00/2.00 (50%/50%). Ninguna casa la ofrece: ambos lados a ~**1.91 (-110)** → implica **52.36% c/u → suma 104.72%**. Ese ~4.7% es el margen, un impuesto sobre cada apuesta gane quien gane.
- A -110 necesitas **ganar 52.38%** solo para no perder. Los pros sostienen **53-55%** — margen finísimo, dificilísimo de mantener.
- La implícita cruda (`1/d`) está **inflada por el margen** → sobreestima la probabilidad real. Si tu modelo iguala al mercado (nuestro caso), tras el vig el EV es negativo. Por eso el primer paso operativo es **quitar el vig** para recuperar la `p` "verdadera" del mercado.

### 1.2 Devigging (estimar la probabilidad "verdadera" del mercado)
Quitar el margen para que las implícitas (`rᵢ = 1/dᵢ`, `O = Σrᵢ`) sumen 100%. Cada método asume un reparto distinto del vig:
- **Multiplicativo/proporcional** `pᵢ = rᵢ/O` — el simple; ignora el favorite-longshot bias (FLB) → sobreestima longshots.
- **Aditivo** `pᵢ = rᵢ − (O−1)/n` — resta el margen por igual; corrige FLB pero puede dar negativos en colas (= Shin en mercados de 2 vías).
- **Power** `pᵢ = rᵢ^k` con `k` resuelto para `Σrᵢ^k = 1` (`scipy.brentq`) — siempre en (0,1), corrige FLB intermedio. **Default recomendado por solidez teórica** en mercados de 2 vías.
- **Shin** — modela margen como insider trading. ⚠️ **Folklore desacreditado:** Whelan (2024) demuestra que su parámetro `z` **no mide insider trading** (es positivo aun sin insiders; refleja costos/competencia). Sirve como transformación de devig, no como medida informacional.
- **Gap entre métodos ≈ 1-2 pp** — material en apuestas +EV marginales, irrelevante en edges grandes. **Ninguno tiene backtest publicado** que pruebe superioridad → enfoque conservador = Worst-Case (toma la `pᵢ` más baja).

Regla clave: **de-vigar un mercado *sharp* y líquido (Pinnacle/Betfair) da una "probabilidad verdadera" mucho más fiable** que de-vigar una casa blanda. Es el insumo central del value betting **y del CLV** (todo depende del devig).

### 1.3 Closing Line Value (CLV) — la prueba honesta de skill
**EL concepto central de todo el campo.** CLV = diferencia entre la cuota que tomaste y la cuota de cierre (justo antes del pitazo, cuando el mercado ya digirió toda la info).

- La línea de cierre es el estimador más preciso de probabilidad verdadera → si **consistentemente tomas precios mejores que el cierre**, anticipas al mercado = tienes edge.
- **Separa skill de suerte mucho más rápido** que el P&L: ~**50 apuestas** para un CLV-beater consistente, vs cientos/miles para el win-rate.
- Estándar de sharp: positivo en **65-70%** de las apuestas, **+1-2% de CLV promedio** sobre muestra grande.
- **Las casas te limitan precisamente por mostrar CLV**, aunque aún no seas net-winner.
- **Caveat de Buchdahl (no folklore):** CLV valida estrategias de *line-shopping/seguir al mercado*; un **originador de odds** con modelo no descubierto puede tener edge real y *no* mostrar CLV (el mercado nunca se mueve hacia él). No es proxy universal.
- **Corolario brutal:** *si no le ganas al cierre, no tienes edge — solo estás viviendo varianza.*

### 1.4 Kelly (sizing) y riesgo de ruina
`f* = (b·p − q)/b = (p·d − 1)/(d − 1) = edge/(cuota − 1)`. Maximiza `E[log(riqueza)]` → la tasa de crecimiento **geométrico** (asintóticamente óptimo, teorema de Breiman). Pero:
- **Full Kelly recomienda stakes aterradores** y asume que conoces tu edge exacto. Propiedad dura (Thorp): `P(caer alguna vez a fracción x del bank) ≈ x` → **P(drawdown al 50%) ≈ 0.5**.
- **Trade-off exacto del fraccional** (múltiplo `c` de Kelly): crecimiento relativo `= c·(2−c)`, std-dev relativo `= c`. ⚠️ **Corrección de folklore:** half-Kelly (c=0.5) → **3/4 del crecimiento con la *mitad del std-dev* = un cuarto de la varianza** (no "la mitad de la varianza", como dice el mito).
- **Sobreapostar es catastrófico:** `c=2` (doble Kelly) → crecimiento esperado **CERO** pese a tener edge real; `c>2` → quiebra con prob. 1. Como el edge se *estima y se exagera*, full Kelly sobre un `p` inflado empuja silenciosamente a `c>1`. Por eso **Kelly fraccional (¼-½) no es opcional.**
- **Multi-outcome:** NO se suman las fracciones individuales (sobreapuesta). Optimización conjunta + cap de exposición simultánea ~20-25% del bank. Correlación positiva → stake conjunto menor.

### 1.5 Métricas de evaluación
- **RPS (Ranked Probability Score)** — la usada para 1X2 (sensible a distancia: home-win está "más cerca" del empate que del away). xG post-partido como mejor predictor single da RPS≈0.148 en Bundesliga; nuestro modelo ≈0.216 (nivel mercado). ⚠️ **Disputado:** Wheatcroft (2019/21) argumenta que el RPS discrimina mal entre forecasters y recomienda **log-loss/Ignorance** para fútbol. La supremacía del RPS (Constantinou-Fenton) ya no es consenso.
- **Brier, log-loss** — calibración. El campo concuerda: **calibración > AUC/accuracy**.
- **ROI vs yield** — el ROI a corto plazo engaña (varianza domina). Muestra creíble: **<100 = ruido, 500+ refleja skill, 2.000-3.000+ = confianza estadística**. Con 100 backtests de parámetros aleatorios, ~5 lucen "rentables" por azar. **CLV es estimador de menor varianza del edge** (se mide por apuesta vs benchmark eficiente, sin esperar el resultado) → los pros priorizan **CLV > ROI corto plazo**.

---

## 2. Cómo ganan los que ganan de verdad (referentes)

> Separando **hecho documentado** de **leyenda/alegato**. Las cifras de ganancia casi siempre son estimaciones o alegatos judiciales — estas operaciones son privadas por diseño.

| Figura | Mercado | Método | Edge real | Replicable hoy |
|---|---|---|---|---|
| **Tony Bloom** (Starlizard, Brighton) | Handicap asiático fútbol | Modelo de probabilidad verdadera de marcadores; 200+ analistas; apuesta en divergencia 1-3% | Modelo + **distribución** (frontmen alegados) en el mercado más profundo/menos eficiente | ❌ Muy baja (escala/acceso) |
| **Matthew Benham** (Smartodds, Brentford, Midtjylland) | Fútbol (asiático) | **Dixon-Coles** + xG + watchers; Moneyball aplicado a clubes | Ser temprano a DC/xG en mercados ineficientes (~2001-2010) | 🟡 Filosofía sí (DC/xG son públicos); el edge de betting ya está priceado |
| **Bill Benter** (HK horse racing) | Pari-mutuel | **Logit multinomial** + combinación 2 etapas con odds públicas (ΔR²); Kelly fraccional | Pari-mutuel = **no te banean**; pools gigantes; exotics multiplican edge | 🟡 El *método* es lo más enseñable; pools hoy más eficientes |
| **Haralabos Voulgaris** (NBA, Mavs) | Totales/props NBA | Modelo "Ewing", simulación a nivel lineup; ~6% ROI/1000 bets (anécdota) | Books lentos + totales blandos pre-2004 | ❌ Mercado ya maduró; props limitados rápido |
| **Joseph Buchdahl** (football-data.co.uk) | Analista/escéptico | Investigación empírica de CLV; *Squares & Sharps* | — (es el contrapeso crítico) | ✅ Su test de **CLV vs Pinnacle** es la herramienta más replicable y honesta |

**Síntesis crítica:**
- **El edge recurrente es estructural, no mágico:** atacar el mercado *menos eficiente*, modelar probabilidad verdadera, apostar solo en divergencia del precio.
- **La idea más profunda (Benter):** tu modelo debe ganarle al **precio de mercado**, no a la realidad. Medido vía ΔR² (Benter) o CLV (Buchdahl) — mismo principio.
- **El verdadero foso es el acceso, no la matemática.** Bloom (frontmen), Benter (pari-mutuel sin baneo), HK (liquidez enorme). Eso es justo lo que un retail NO puede replicar.
- **Buchdahl es el aterrizaje:** mide tu CLV; si no le ganas al cierre, no tienes edge demostrable. Suele probar que *no* lo tienes.

---

## 3. Value betting y arbitraje retail — realidad vs marketing

**Ambas son +EV en teoría.** En la práctica el edge es fino y el cuello de botella es el **gubbing** (te limitan/banean por ganar).

### 3.1 Value betting automatizado (RebelBetting, OddsJam, Trademate, Betburger)
- **Mecánica:** escanear millones de cuotas/min, de-vigar la línea sharp (Pinnacle/consenso) → "fair price" → marcar la casa blanda que paga de más.
- **ROI real:** marketing dice "30% ROI/mes" (eso es bankroll reciclado). El número honesto y repetible es **~2-4% de yield**. La cifra más creíble del registro público: **Trademate ~2.19% de yield sobre ~1M de trades comunitarios**.
- **Límites:** te **gubean** (especialmente arbing — "la forma más rápida"); el edge solo se realiza sobre **volumen enorme** con varianza brutal; la **suscripción (€89-199/mo) se come el yield** si apuestas pequeño; software lento pierde oportunidades.

### 3.2 Arbitraje (surebets)
- **Math:** surebet si `Σ(1/odds_i) < 1`. Margen `= (1/Σ) − 1`. Stakes proporcionales a `1/odds_i`.
- **ROI por arb:** **1-3%** (hasta ~5%). "5-15% del bank/mes" solo con 20-30 arbs/día compuestos.
- **El killer — palpable errors:** la casa **anula** una pata por "error obvio" aunque haya ganado → quedas con la otra pata descubierta (pérdida o swing grande). Nunca tomar arbs rated >110%.
- **No escala:** capital fragmentado en decenas de cuentas, ventanas de segundos, gubbing rapidísimo. "Risk-free" es un mito tras anulaciones + movimiento de línea entre patas.

> **Veredicto §3:** edge real pero **extractable bajo y decreciente por cuenta**. Para un operador disciplinado con muchas cuentas y tolerancia a varianza/churn puede ser net-positive, pero el marketing exagera la facilidad y durabilidad.

---

## 4. Polymarket / Kalshi — el frente más prometedor para nosotros

> Porque el edge **no requiere predecir mejor**: es de microestructura. Y el Mundial trajo la contraparte ideal.

### 4.1 Mecánica
- **CLOB híbrido** (matching off-chain, settlement on-chain Polygon). **Peer-to-peer, sin vig de casa** — el "overround" es solo la suma de spreads del libro.
- Cada $1 USDC acuña 1 share YES + 1 NO; **precio (0-1) = probabilidad implícita**; al resolver, ganador $1 / perdedor $0.
- Resolución vía **UMA Optimistic Oracle**. Fees: históricamente 0 taker/maker; modelo 2025-26 da a makers **20-25% de taker fees** como rebate.
- **Kalshi:** exchange CFTC-regulado, **partner oficial del Mundial 2026**, mismo modelo binario (cents 0-100).

### 4.2 Por qué es MÁS eficiente (y dónde están las grietas)
Sin vig + bots/arbitrajistas → los precios **trackean la probabilidad real y hasta superan ligeramente a las casas** (Reichenbach & Walther). Batirlo direccional = muy difícil. Grietas explotables **sin saber más de fútbol**:

| Estrategia | ¿Edge real? | Por qué |
|---|---|---|
| **Market making + liquidity rewards** | ✅ El más sólido | Cosechas spread + 20-25% taker fees + rewards (~$12M/año Polymarket repartió a LPs); scoring cuadrático premia estar pegado al midpoint |
| **Resolution-edge holding** | ✅ | La estrategia **dominante del smart money** (win rate por evento mediana 93%): mantener casi-resueltos a <$1 hasta que pagan $1 |
| **Arbitraje cross-platform** (PM↔Kalshi↔casas) | ✅ pero comprimido | Garantizado si suma <$1 neto de fees; ventanas de ~30s (eran 5min en 2024) → necesita bot |
| **Arb intra-platform / dutching** (multi-outcome) | ✅ en mercados nuevos/ilíquidos | Si Σ(YES de outcomes excluyentes) <$1 → comprar todos; inconsistencias "grupo vs campeón" antes de que bots alineen |
| **Longshot bias del retail** | 🟡 fino | A nivel agregado NO hay sesgo; a nivel retail sí sobrepagan colas extremas. Edge fino, requiere volumen/disciplina |
| **Apostar direccional "quién gana"** | ❌ ilusión | Mercado eficiente + smart money + bots; 84% pierde |

**Riesgo dominante del MM:** *adverse selection* — los binarios resuelven 0/1; si pones bid 53¢ y sale noticia, los informados te venden antes de que canceles. Mitigar: evitar cerca de resolución, ensanchar spreads pre-evento, limitar tamaño, preferir info difusa. **Inventory risk:** rebalancear/hedgear en correlacionados.

### 4.3 El Mundial 2026 en Polymarket — la oportunidad
- Volumen del "World Cup Winner" cruzó **$3.3B** (superó al Super Bowl); Bernstein proyecta >$10B antes de la final. Categoría soccer: ~$53M/día → **$220M/día** (+300%). **244 mercados**, liquidez pooled **~$352.7M**.
- **La trampa del longshot en estado puro:** **~$1.6B (≈2/3 del volumen) fue a equipos con ≤1%** (Cabo Verde, Egipto, Marruecos, México…). Overround para *takers* ~15% en esas colas → **tomar es caro; proveer liquidez ahí es donde está el dinero**.
- **Veredicto:** el Mundial es el mejor momento para MM/arb (ola de retail no sofisticado = contraparte), y el peor para direccional al campeón.

### 4.4 La verdad incómoda (estudios 2026)
- **84.1%** de traders en pérdida (2.5M wallets); otro estudio 70% de 1.7M.
- **<0.04%** capturan >70% de ganancias ($3.7B). Retail cierra en ganancia 7.9% de mercados; smart money 67% (**brecha 8.5×**).
- Smart money: 40% del volumen en mercados de **baja atención** (ineficientes); retail solo 8% (se aglomera en alta atención ya eficiente). Retail sufre *disposition effect* (aguanta perdedores 5.7× más).
- **El retail ES la liquidez que cosecha el smart money.**

### 4.5 Regulación / acceso (CRÍTICO para Colombia)
- **USA:** Polymarket aprobado CFTC (compra de QCEX, relanzado invite-only); Kalshi regulado CFTC. Patchwork estado-por-estado (NV demanda, TN cierre, MN prohibición). Regla CFTC propuesta 2026-06-10.
- **Internacional:** 10+ países han prohibido/restringido PM/Kalshi.
- **⚠️ Colombia: estatus legal de Polymarket/Kalshi NO verificado.** Técnicamente accesible vía wallet self-custody (USDC/Polygon), pero acceso geográfico/KYC + legalidad local (Coljuegos) **requieren consulta legal antes de operar**. No afirmamos legalidad en ningún sentido.

---

## 5. Fuentes de datos (mapa operativo)

### 5.1 Odds / líneas
| Fuente | Gratis/Pago | Cobertura | ¿CLV histórico? |
|---|---|---|---|
| **The Odds API** (ya integrada) | Free 500 cr/mo; pago $30-249/mo | 70+ deportes, 40+ casas (incl. Pinnacle) | Sí, snapshots 5-min desde 2022 (solo pago) |
| **bettingiscool** Pinnacle Data API | Tokens, free trial | 46 deportes, hist. desde 2021, **devig + endpoint `/api/clv`** | ✅ **El más relevante para CLV** |
| RapidAPI "Pinnacle Odds" (tipsters) | Free + pago [$ no verif.] | Backdoor a Pinnacle, archive | Sí (archive) |
| **Pinnacle API oficial** | **Cerrada al público desde 2025-07-23** | — | ❌ (1 req/2min, cuenta funded) |
| OddsJam / OpticOdds | Pago opaco (enterprise) | 200+ casas, props, in-play | Sí (tier pago) |
| SportMonks / API-Football | Free limitado; €29-249/mo | Fútbol | Débil para closing lines |

### 5.2 Exchanges (precio = "fair odds", y **no limitan ganadores**)
| Exchange | API | Costo API | Comisión | Notas |
|---|---|---|---|---|
| **Betfair** | API-NG + Stream | Delayed gratis; **£499** live key | 5% + **Premium Charge 20-50%** a ganadores | Liquidez más profunda; el PC castiga a pros |
| **Smarkets** | docs.smarkets.com | **£150** único | **2%** plano, sin PC | Buena economía para ganadores |
| **Matchbook** | developers.matchbook.com | Free <1M GET/mo | **1.5%** (0.75% maker) | Comisión más baja |
| **Sporttrade** (USA) | Sin API pública confirmada | — | 2% s/ profit | NJ/AZ/CO/IA/VA; modelo share 0-100 |

### 5.3 In-play / live (latencia = edge)
- **Enterprise (sub-segundo, origen propio en estadio):** Sportradar/**Betradar**, **Stats Perform (Opta)** (WebSocket, 2.000 updates/match), **Genius Sports** (rights oficiales EPL/NFL/Serie A, <1s). Solo B2B.
- **Retail:** **Goalserve** ($500/mo, <1s claim, free trial 30 días) = lo más cercano a "near-pro"; BetsAPI (Bet365), The Odds API (más para comparación).
- **Latency arbitrage:** quien ve el estado real primero (courtsiding/feed-tier) apuesta sobre algo ya ocurrido mientras el mercado aún lo precia incierto. Exchanges defienden con **bet delay** (Betfair "Red Clock" ~5-8s). Un workflow retail derivado de TV está **estructuralmente atrás**.

### 5.4 Históricos para backtest de CLV
- **Football-Data.co.uk** (gratis, el core): CSVs por liga/temporada; columnas **`PSCH/PSCD/PSCA` = Pinnacle CLOSING** + `B365C*` + `MaxC/AvgC`. Closing desde ~2012/13. `https://www.football-data.co.uk/mmz4281/{SSSS}/{LEAGUE}.csv`.
- **Beat the Bookie** (Kaggle): >500K partidos, 1.005 ligas, 32 casas, **odds horarias 72h→cierre** (2005-2015) — ideal trayectoria opening→closing.
- OddsPortal (vía OddsHarvester/Playwright) → multi-casa, pero **viola ToS** y se rompe seguido.

### 5.5 Polymarket / Kalshi (APIs — lectura gratis, sin auth)
- **Polymarket Gamma** `https://gamma-api.polymarket.com` (metadata/`outcomePrices`); **CLOB** `https://clob.polymarket.com` (`/book`, `/midpoint`, `/price` por `token_id`). ⚠️ `py-clob-client` **archivado 2026-05-25** → usar `py-sdk` o REST directo.
- **Kalshi** `https://external-api.kalshi.com/trade-api/v2` (`/markets`, `/markets/{ticker}/orderbook`); trading con firma **RSA-PSS**.
- **Precio = probabilidad; midpoint = mejor estimador; profundidad = Σ size por nivel.** Spread ancho/size fino = señal ruidosa.

### 5.6 ✅ Verificación de acceso (hands-on, 2026-06-29 desde este entorno)
Probado con `curl`/`git` reales. Resultado:

| Fuente | Acceso | Nota operativa |
|---|---|---|
| **football-odds-mirror** (GitHub) | ✅ **funciona** (raw) | `huhao930422-debug/football-odds-mirror` — **mirror diario de football-data.co.uk**, 24 ligas, 567 CSVs desde 1993, **106 columnas con `PSCH/PSCD/PSCA` (cierre Pinnacle) poblado 380/380**. **ESTE es nuestro dataset de CLV.** |
| **The Odds API** (key real) | ✅ live (493 req/mes restantes) | FIFA World Cup + Winner disponibles. ⚠️ **`/historical` da 401** → confirmado: nuestro plan free NO incluye histórico. |
| **Polymarket Gamma** | ✅ funciona | Devuelve mercados WC en vivo (Francia 27.6%, España 11.4%…). **Requiere sandbox OFF** (el sandbox lo bloqueaba con HTTP 000). |
| **Kalshi** | ✅ alcanzable (200) | `/markets` responde; para WC filtrar por `series_ticker`. **Requiere sandbox OFF.** |
| **football-data.co.uk** (directo) | ❌ **bloqueado** | TLS *connection reset by peer* (anti-bot rechaza fingerprint de curl, no es el sandbox). **Usar el mirror de GitHub.** |
| GitHub (openfootball, repos, API) | ✅ funciona | Resultados/fixtures sin odds. |
| **Kaggle** (Beat the Bookie) | 🟡 web OK, sin CLI/creds | Falta `~/.kaggle/kaggle.json` para bajar datasets vía API. |

> **Corpus de CLV verificado:** solo top-5 ligas × 7 temporadas (2019-2026) ya da **~12.459 partidos con cierre Pinnacle**; las 24 ligas desde 2015-16 ⇒ **~40-60K partidos**. Muy por encima de los 2.000-3.000 necesarios para significancia. **El hueco de datos está resuelto, gratis.**

---

## 6. Algoritmos y modelos (estado del arte)

- **Base canónica:** Maher (1982) → **Dixon-Coles (1997)** (Poisson bivariado + ρ marcadores bajos + ventaja local + time-decay). Goddard (2005). **Es exactamente nuestro stack.**
- **xG:** logística calibrada (lo que hace Opta); xG post-partido = mejor predictor single (RPS≈0.148 Bundesliga). Es nuestro `train_xg.py`.
- **ML reciente que "gana":** Wilkens (2026, peer-reviewed) ~10-15% ROI Bundesliga **pero solo en home-wins y vs odds promedio, no cierre**; varios preprints con ROIs altos **no especifican timing de odds** (red flag). pi-football (Constantinou) ≈ casas.
- **La pared:** la evidencia más replicada es que **la línea de cierre es un estimador extraordinario** y **casi nadie le gana a escala tras vig + límites de ejecución**. Margen de casas cayó de ~10.5% (90s) a ~5% (2010s). Buchdahl "Wisdom of the Crowd" (~20.000 bets) rindió ~3.4% **solo porque sigue al cierre**.
- **Repos útiles:** `Hicruben/world-cup-2026-prediction-model` (Elo→DC→MC, nuestra base conceptual), `ghurault/football-prediction` (DC en Stan), fivethirtyeight/data soccer-spi (archivado pero data viva), openfootball.
- **8 razones por las que los backtests "rentables" no son reales:** overfitting/p-hacking, look-ahead/leakage (xG revisado post-partido), usar odds de apertura/promedio en vez de cierre, ignorar el vig, ignorar límites de ejecución, survivorship en la literatura, colapso out-of-sample, y **si no le ganas al cierre es varianza, no edge.**

---

## 7. Panorama Mundial 2026 (estado ~29 jun, se mueve cada hora)

### 7.1 Cuotas al campeón (post-eliminación de Alemania)
- **Casas (FanDuel, 30 jun):** Francia +250 (~28.6%) · Argentina +400 (~20%) · España +650 (~13.3%) · Inglaterra +700 · Brasil +950 · **Marruecos +1900** (saltó tras eliminar a Países Bajos) · Colombia +3000.
- **Prediction markets (29 jun):** Kalshi/Polymarket → Francia ~27% · Argentina ~20-21% · España ~11% · Inglaterra ~10% · Brasil ~7%. Kalshi precia Argentina/USA algo más alto (sesgo regional US).

### 7.2 Supermodelos
- **Opta** (25k sims, knockout): Francia 18.7% · Argentina 16.3% · España 13.5% · Inglaterra 9.7%. Anfitriones a cuartos: USA 42.5%, MEX 28.3%, CAN 25.2%.
- **PELE / Nate Silver** (ex-538, ahora Silver Bulletin, 100k sims): probabilidades equipo tras paywall; **marcó Paraguay 22% de avanzar vs ~15% mercado → eliminó a Alemania (value confirmado)**.
- **Académico Groll/Zeileis/Hvattum** (RF híbrido + Transfermarkt): pre-torneo, ya obsoleto (Alemania fuera). Metodología y código abiertos.

### 7.3 Dónde se ve value (con cautela)
1. **España posiblemente infravalorada** en PM (~11%) vs modelos (Opta 13.5%, académico 14.5%, ScoreGPT campeón).
2. **Francia posiblemente sobre-apostada** por el público (mercado ~27% vs Opta 18.7%).
3. **Underdogs de cuadro** (Paraguay, Marruecos) ya validaron que los modelos detectan value que el mercado tarda en preciar.
4. **Props in-play** (timing de re-precio post-gol/roja) y **tarjetas por árbitro** = ineficiencias más explotables estructuralmente.

### 7.4 Formato 48 = más varianza
12 grupos de 4 → top 2 + 8 mejores terceros → **Ronda de 32** (nueva) → 104 partidos. Ronda extra a un partido = más exposición a penales/upsets. Upsets R32: **Paraguay elimina a Alemania (pen)**, **Marruecos a Países Bajos (pen)**, Brasil sobrevive 2-1 a Japón. Rutas de cuadro asimétricas (terceros débiles) que el mercado tarda en ajustar = value en el lado más blando.

---

## 8. Veredicto y plan para Orbital / MOVA

### 8.1 Respuesta directa a la pregunta
- **¿Ganar consistente apostando al Mundial con nuestro modelo en mercados principales?** → **No.** Estamos a nivel de mercado; tras el vig es EV negativo. Apostar al campeón/octavos esperando ganar plata = perder a largo plazo.
- **¿Hay alguna estrategia +EV sostenible?** → **Sí, pero no es predictiva, es de microestructura,** y las realistas para nosotros son: (a) **CLV como brújula/validación**, (b) **Polymarket market-making + arbitraje** durante el Mundial, (c) value/arb en casas blandas con la limitación del gubbing.
- **La polla ≠ la casa.** Donde sí tenemos edge limpio es **la polla** (sin vig, contra humanos sesgados): valor/ownership/camino de bracket/regresión. Ese sigue siendo el juego ganable de este repo.

### 8.2 Plan accionable por fases (de menor a mayor riesgo)
1. **Fase A — Tracker de CLV (gratis, sin arriesgar capital). PRIMERO.**
   Registrar "apuestas teóricas" del modelo y medir CLV vs cierre de Pinnacle (de-vigado). Datos: The Odds API (ya integrada) + Football-Data.co.uk para histórico. **Si en 50-100 mercados batimos el cierre → edge probado; si no → confirmamos que no hay que apostar.** Es la jugada inteligente, barata y honesta. *Esto zanja empíricamente todo el debate antes de tocar un peso.*
2. **Fase B — Scanner de valor/arb (alerta, no ejecución automática).**
   Cruzar The Odds API (40+ casas) contra Pinnacle de-vigado → alertas de líneas desalineadas + surebets. Edge real pero montos chicos + riesgo de gubbing.
3. **Fase C — Polymarket: explorar microestructura (paper first).**
   Bot read-only sobre `py-sdk`/REST monitoreando los 244 mercados del Mundial: detectar arbs intra-platform (Σ outcomes <$1), cross-platform PM↔Kalshi, y simular market making en colas (sin capital real). Medir edge bruto y netear fees/slippage. **Solo tras verificar legalidad/acceso desde Colombia.**

### 8.3 Lo que NO vamos a hacer (y por qué)
- No prometer +EV en mercados principales (no lo tenemos).
- No apostar direccional al campeón con el modelo.
- No usar "tipsters"/sistemas vendidos (survivorship bias; si fuera escalable lo apostarían, no lo venderían).
- No operar Polymarket con capital real sin (1) edge probado en paper y (2) claridad legal en Colombia.

---

## 9. Matriz final — edge real vs ilusión

| Estrategia | ¿Edge real? | Cuello de botella | Para nosotros |
|---|---|---|---|
| Predecir mejor que el mercado (1X2/campeón) | ❌ | Mercado eficiente | Solo para *la polla*, no para apostar |
| **CLV como validación** | ✅ (diagnóstico) | Necesita muestra + datos de cierre | **Fase A — hacer ya** |
| Value betting casas blandas | ✅ ~2-4% yield | Gubbing rápido | Fase B (alertas) |
| Arbitraje casas | ✅ 1-3% | Palpable errors, capital fragmentado, gubbing | Fase B (con cautela) |
| **Polymarket market making** | ✅ (el más sólido) | Adverse selection, inventory, capital, bot | **Fase C — explorar paper** |
| Polymarket resolution-edge | ✅ | Capital paciente, leer certeza | Fase C |
| Polymarket/Kalshi arb | ✅ comprimido | Ventanas ~30s, bot, fees | Fase C |
| Longshot bias retail | 🟡 fino | Volumen, disciplina | Observar |
| In-play latency arb | ✅ (pros) | Feed sub-segundo (enterprise) | ❌ fuera de alcance retail |

---

## 10. Fuentes clave (verificadas)

**Matemática/CLV/eficiencia:** Whelan, *Estimating Expected Loss Rates in Betting Markets* (karlwhelan.com/Papers/Overround.pdf) · Buchdahl vía Pinnacle Odds Dropper (CLV) · VSiN, Pikkit, Unabated (CLV) · Forrest & Simmons (eficiencia).
**Referentes:** Wikipedia (Bloom, Benham, Benter, Voulgaris) · Benter 1994 paper (gwern.net/doc/statistics/decision/1994-benter.pdf) + anotación Acta Machina · theesk.org (Starlizard/Benham analysis) · Pinnacle author page (Buchdahl).
**Tools value/arb:** rebelbetting.com, oddsjam.com, tradematesports.com, betburger.com · reviews thetradingreview.com, punter2pro.com · palpable errors: caanberry.com, sportsarbitrageguide.com.
**Polymarket/Kalshi:** docs.polymarket.com, docs.kalshi.com · Reichenbach & Walther (SSRN) · QuantPedia (systematic edges) · The Defiant / Yahoo (84%/70% pierden) · Akey et al. "Who Wins and Who Loses" (SSRN) · CryptoSlate (longshot trap WC) · CCN (países restringidos).
**ML/modelos:** Dixon-Coles 1997 (DOI 10.1111/1467-9876.00065) · Maher 1982 · Wilkens 2026 (Sage) · survey arXiv:2410.21484 · repos Hicruben/ghurault/openfootball.
**Datos:** the-odds-api.com, football-data.co.uk, Beat the Bookie (Kaggle), Betfair API-NG, Goalserve, Sportradar/StatsPerform/Genius.
**WC2026:** theanalyst.com (Opta), natesilver.net (PELE), zeileis.org, FanDuel/FOX, polymarket.com/fifa-world-cup, ESPN best bets.

> Informes crudos completos (sin resumir) en `scratchpad/research-*.md` de la sesión de investigación (13 archivos).
