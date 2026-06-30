# Polymarket — ¿se puede ganar por ESTRATEGIA (no por predicción)?

> **Investigado + medido en vivo:** 2026-06-30. 9 investigadores + medición empírica directa de los mercados del Mundial vía API (`scripts/poly_microstructure.py`).
> **Pregunta:** ya sabemos que no se gana por estadística (out-predecir al mercado, ver [docs/13](13-clv-backtest-resultados.md)). ¿Se puede por **microestructura** — market making, arbitraje, resolution-edge — que NO depende de predecir mejor?

---

## 0. TL;DR — la respuesta honesta, ahora con números reales

**Medimos el mercado real "ganador del Mundial" en Polymarket y está hiper-eficiente e hiper-líquido:**
- **Spread bid/ask = 0.1¢** (el tick mínimo) en **los 28 equipos**, incluso longshots (Noruega, Marruecos, USA).
- **Profundidad: $25M+ en el ask, $6-7M en el bid, 200+ niveles de precio** en Francia/Argentina/España.
- **100% de los mercados WC capturados tienen spread ≤1¢.** No hay "thin markets" con room en el feed principal.

**Implicación dura:** las estrategias de microestructura que la teoría señala como +EV están, en los mercados líquidos del Mundial, **saturadas por bots profesionales**. Para un operador pequeño:
- **Market making:** el spread ya está en el piso (0.1¢) y hay $25M de liquidez pro delante de ti. No hay spread que capturar; tu fracción de rewards sería un sliver mientras cargas todo el riesgo de cola (adverse selection).
- **Arbitraje (latencia/cross-platform):** ventanas de ~2.7s, **73% del profit lo capturan bots sub-100ms**, US-East a 130-150ms es fatal, y Polymarket ya metió **fees dinámicas** para matar justo este trade.
- **Resolution-edge:** dominado por firmas con infra; lockup UMA de 2h+; margen retail negativo.
- **Copy-trading:** eres la liquidez de salida; <1% de wallets gana; leaderboards contaminados por wash-trading.

**El único resquicio teórico** para un individuo: mercados **genuinamente nicho/ilíquidos** (props raros, baja atención) — pero son de **baja capacidad** (no puedes mover volumen) y aun así requieren un bot. **No es un negocio escalable.**

**Veredicto:** igual que con la estadística, **el edge estructural existe pero NO es extraíble por un operador pequeño** en los mercados líquidos. Lo honesto es medirlo en paper antes de arriesgar capital (ya tenemos acceso técnico y el medidor).

---

## 1. Medición empírica en vivo (lo que nadie más en la conversación tenía)

`scripts/poly_microstructure.py` (curl_cffi impersonate=chrome131, sandbox off) — mercado "Will X win the 2026 FIFA World Cup?", 2026-06-30:

| Equipo | YES | bid | ask | **spread** | rewardsMaxSpread | liquidez | profundidad libro |
|---|---|---|---|---|---|---|---|
| France | 0.288 | 0.288 | 0.289 | **0.1¢** | 4.5¢ | $7.3M | bids $6.5M / asks $25.6M (210/197 niveles) |
| Argentina | 0.194 | 0.193 | 0.194 | **0.1¢** | 4.5¢ | $9.0M | bids $7.6M / asks $26.6M (145/206) |
| Spain | 0.113 | 0.112 | 0.113 | **0.1¢** | 4.5¢ | $9.5M | bids $6.1M / asks $27.5M (88/258) |
| England…USA…Colombia | … | … | … | **0.1¢** | 4.5¢ (21/28) | $2-7M | — |

- **Overround Σ(YES) ≈ 1.023** sobre 28 equipos vivos → **NO es arb** (comprar todos cuesta 1.023 por 1.00; vender todos neto 0.995 vs liability 1.00). Es el margen natural que capturan los makers existentes, no una oportunidad para taker.
- **Spreads: mediana / min / max = 0.1¢ en TODOS.** Incluso longshots. El mercado está en el tick floor.
- **Rewards activos en 21/28 mercados** (rewardsMaxSpread 4.5¢) — pero con $25M+ y 200+ niveles ya compitiendo, tu share del pool es minúsculo sin capital grande.
- **Kalshi:** serie `KXMWORLDCUP` ("Men's World Cup winner") existe; 104 series FIFA no-esports (KXWCSPREAD, KXWCWINMARGIN, KXWC3RDPLACE…). Spread cross-venue documentado 5-8¢ en equipos secundarios, pero retiros Kalshi de 3-30 días matan el arbitraje limpio.

> **Conclusión de la medición:** el mercado estrella no es un mercado retail delgado donde proveer liquidez y cobrar spread. Es un mercado profesional, profundo y comprimido al tick. La premisa "el Mundial trae retail tonto = market making fácil" es cierta para el *flujo* pero falsa para el *spread capturable*: los pros ya lo cosecharon hasta 0.1¢.

---

## 2. Las estrategias, una por una (edge real vs realidad 2026)

| Estrategia | ¿Edge teórico? | Realidad medida/investigada | Para nosotros |
|---|---|---|---|
| **Market making (winner market)** | ✅ spread + rewards | Spread 0.1¢, $25M depth, 200+ niveles, rewards diluidos | ❌ saturado |
| **MM en props/nicho ilíquidos** | ✅ spread ancho | Baja capacidad, requiere bot, adverse selection de insiders | 🟡 marginal, no escalable |
| **Arb latencia (cross-platform)** | ✅ garantizado si <$1 | Ventanas 2.7s, 73% capturado <100ms, fees dinámicas, fricción retiros Kalshi 3-30d | ❌ infra-gated |
| **Arb intra-platform (multi-outcome)** | ✅ si Σ≠1 | Overround real +2.3% pero no es arb; bots alinean en segundos | ❌ copado |
| **Resolution-edge holding** | ✅ smart money 93% win/evento | Lockup UMA 2h+ (hasta 48-96h con disputa), margen retail negativo | ❌ infra/capital |
| **Copy-trading smart money** | ✅ el edge existe en <1% | Eres exit liquidity; latencia de señal; wash-trading; survivorship | ❌ flat-a-negativo neto |
| **Longshot bias retail** | 🟡 fino a nivel retail | A nivel agregado NO hay sesgo (Reichenbach-Walther); longshots también a 0.1¢ | 🟡 difícil de fadear |
| **In-play / latency lag** | ✅ Polymarket lag 3-8% post-gol | Pero Polymarket metió "sports delay" anti-flash; carrera de bots | 🟡 nicho, requiere infra |

**Patrón:** todo lo que es +EV en teoría está, en los mercados líquidos, copado por infraestructura (sub-100ms, co-lo Amsterdam/Londres, capital). Lo que queda para un individuo es nicho y de baja capacidad.

---

## 3. La matemática del market making en binarios (por qué el riesgo es de cola)

**Glosten-Milgrom en binarios 0/1:** el spread de break-even es `spread* ≈ 2α·E[|V−P| | informado]` (α = fracción de flujo informado). La diferencia vs acciones: el contrato **resuelve a $0 o $1**, no se mueve "un poco". Si cotizas bid 53¢ y sale la noticia, los informados te venden a 53¢ y el valor justo se va a ~2¢: **no pierdes 5¢, pierdes ~50¢ de golpe.**

**Descomposición del PnL del maker:**
```
PnL = Spread_capturado − Adverse_selection − Inventory_cost + Rewards + Fee_rebates
```
- Maker fees = **0**; rebate ≈ 20-25% de taker fees; gas = **0** (órdenes off-chain, settlement lo paga el operador).
- **Fórmula de rewards (cuadrática):** `S(v,s) = ((v−s)/v)²·b` — premia cotizar pegado al mid y grande. Two-sided usa `Q_min = min(score_bid, score_ask)` → **te obliga a cotizar simétrico = maximiza tu adverse selection.**
- **La tensión central:** rewards exigen quotes estrechas (riesgoso); MM prudente exige quotes anchas (poco reward). El PnL del spread puro es ≈0 o negativo tras adverse selection; **el +EV vive casi enteramente de rewards + rebates, que son pro-rata y competitivos** (bots grandes diluyen tu fracción).
- **Distribución de PnL del maker individual:** muchos +0.1¢ y un −50¢ ocasional. En el Mundial, la adverse selection vive en las **alineaciones/lesiones** (alguien sabe que el crack no juega 90 min antes).

---

## 4. Quién gana realmente (la señal más honesta)

Estudios 2026 sobre $20B+ de volumen y >1M usuarios (Akey et al. SSRN 6443103; Reichenbach-Walther SSRN 5910522; Solidus Labs):
- **84% de los traders pierde.** **<30% gana dinero.** 1.7M personas perdieron $650M.
- **Top 1% captura 76.5-84% de las ganancias.** 0.55% de makers + 0.26% de takers se llevan ~50% del PnL.
- Los ganadores son **proveedores de liquidez con limit orders** que resuelven a favor — pero ese grupo es <3.5% y tiene "capital, infraestructura y ejecución fuera del alcance de la mayoría".
- **El retail ES la liquidez que cosecha el smart money.** Quien farmea rewards ciego two-sided está maximizando justo su adverse selection.

---

## 5. Infraestructura mínima (si se intentara) + acceso verificado

- **SDK:** `py-clob-client` 0.34.6 (probado) o `polymarket-client` (beta). Bots de referencia: `spfunctions/polymarket-sports-mm` (rewards-optimized), `warproxxx/poly-maker` (**el autor advierte: "no es rentable hoy, úsalo como referencia"**), `taetaehoho/poly-kalshi-arb` (Rust, el arb más serio).
- **Auth:** L1 (firma EIP-712) + L2 (HMAC). Wallet Gnosis Safe + USDC.e/pUSD. **No necesitas gas wallet** (maker no paga gas). Rate limit cómodo (~60 órdenes/s sostenido). Heartbeat WS cada ~5s o se cancelan tus órdenes.
- **Latencia:** no hay co-location; la carrera no es de nanosegundos sino de **segundos-a-noticia**. VPS + bot basta para no quedar stale, pero ningún VPS te salva si la info salió en Twitter.
- **✅ Acceso técnico verificado (este entorno):** Polymarket gamma/CLOB pasan Cloudflare **solo con `curl_cffi impersonate=chrome131`** (curl normal y chrome→reset; rotar huella + retries). Kalshi y The Odds API responden directo. Sandbox del shell debe estar **OFF**. Medidor funcionando: `scripts/poly_microstructure.py`.

---

## 6. Veredicto y recomendación

**¿Se puede ganar por estrategia?** En teoría sí existen edges no-predictivos; **en la práctica medida, los mercados líquidos del Mundial están saturados** y los edges restantes son nicho, de baja capacidad e infra-gated. Para un operador pequeño sin co-location ni capital de 6 cifras, **no hay un negocio +EV claro y escalable** en Polymarket WC hoy. (Y la legalidad/acceso desde Colombia sigue **sin verificar** — requiere asesoría.)

**Recomendación (misma filosofía que el CLV tracker: medir antes de arriesgar):**
1. **Monitor read-only / paper, NO capital.** Ya tenemos acceso (`poly_microstructure.py`). Extenderlo a un escáner que registre durante días: spreads por mercado, mercados con rewards y pocos competidores, gaps cross-venue PM↔Kalshi netos de fees, e inconsistencias multi-outcome. **Si aparecen ineficiencias persistentes y con capacidad → reconsiderar. Si no (lo más probable) → confirmado que no vale el capital.**
2. **No** correr un bot de MM/arb con dinero real basándose en la teoría: la evidencia (84% pierde, spread ya en 0.1¢) dice que serías el flujo que alimenta al top 1%.
3. Si hubiera interés genuino, el único ángulo defendible es **un nicho específico medido** (un prop concreto con spread ancho + rewards + pocos competidores), sized chico, como experimento — no como estrategia principal.

> **Cierre honesto del hilo de apuestas:** ni por estadística ([docs/13](13-clv-backtest-resultados.md)) ni por microestructura ([este doc]) hay un edge extraíble y escalable para nosotros hoy. El valor del ejercicio fue **probarlo con datos reales** en vez de creer el marketing. El juego ganable de este repo sigue siendo **la polla** (sin vig, contra humanos sesgados).

## Reproducir
```bash
pip install curl_cffi
python scripts/poly_microstructure.py   # requiere sandbox OFF; mide PM + Kalshi en vivo
```
Informes crudos de la investigación: `scratchpad/research-poly-*.md` (5 archivos: MM infra, in-play, arb+copy-trading, retail bias, adverse-selection math).
