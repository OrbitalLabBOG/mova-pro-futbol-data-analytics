# The Odds API — exploración y diseño

> Explorado 2026-06-28. Key en `.env.local` (`ODDS_API_KEY`, gitignored). Plan **free: 500 créditos/mes** (sin tarjeta, **sin** odds históricas).

## Modelo de créditos (confirmado en vivo)

**1 crédito = 1 región × 1 mercado** por request (la lista de partidos viene completa en ese request). La lista de sports (`/v4/sports`) es **gratis**. La API devuelve en headers `x-requests-remaining` / `x-requests-used` → los logueamos para nunca pasarnos.

| Pull | Costo |
|---|---|
| `soccer_fifa_world_cup_winner` outrights, 1 región | 1 |
| `soccer_fifa_world_cup` h2h+totals+spreads, 1 región | 3 |
| **Snapshot diario (1 región)** | **~4/día → ~84/mes** ✅ holgado |

## Endpoints y estructura real

```
GET /v4/sports/?apiKey=K&all=true                         # gratis; keys de deportes
GET /v4/sports/soccer_fifa_world_cup_winner/odds?apiKey=K&regions=eu&markets=outrights&oddsFormat=decimal
GET /v4/sports/soccer_fifa_world_cup/odds?apiKey=K&regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal
```

- **Ganador (outrights):** 1 "evento" con `bookmakers[]` (betfair_ex_eu, williamhill…), cada uno `markets[0].outcomes[] = {name: equipo, price: decimal}`. France 4.7, Argentina 5.2…
- **Partidos:** `events[]` con `id, home_team, away_team, commence_time, bookmakers[]` (**25 casas** en `eu`). Cada bookmaker → `markets[{key: h2h|totals|spreads}].outcomes[{name, price, point}]`.
- **Odds decimal** → prob. implícita = `1/price` (sin normalizar el overround; guardamos `price` crudo también).

## Diseño de tablas (informado por lo explorado)

Como The Odds API trae **muchas casas por partido**, guardamos **granular** (no se pierde nada — "todos los datos"):

```sql
odds_quotes(
  source, captured_at, scope,        -- scope: 'winner' | 'match'
  event_id, commence_time, home_team, away_team,
  bookmaker, market, outcome, price, point,
  PRIMARY KEY (source, captured_at, scope, event_id, bookmaker, market, outcome)
)
```

Además, para comparar con Kalshi/Polymarket en la misma vista, escribimos un **consenso del ganador** en `market_odds` (source='oddsapi', `prob` = mediana de `1/price` entre casas).

Raw crudo también se cachea en `data/raw/oddsapi/` por si queremos re-procesar.

## Uso (credit-aware)

```bash
python scripts/collect_odds.py                 # winner + match (eu) ≈ 4 créditos
python scripts/collect_odds.py --regions eu,uk # más casas (más créditos)
python scripts/collect_odds.py --winner-only   # solo ganador (1 crédito)
```

> Es **complementaria**: Kalshi/Polymarket/ESPN ya dan mercado gratis e ilimitado. The Odds API añade **consenso multi-casa + Pinnacle/Betfair**. Por presupuesto, corre 1×/día (no en el `collect_context.py` ilimitado).
