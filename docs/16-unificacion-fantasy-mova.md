# Arquitectura Unificada: MOVA Pro Fútbol Data Analytics & Capa Fantasy

> **Documento de Arquitectura v2.0 (2026-08-07)**  
> Consolidador universal de analítica deportiva para la vertical **MOVA** (Orbital Lab).

---

## 1. Contexto y Decisión de Arquitectura

Se ha **unificado y universalizado** el repositorio [`mova-pro-futbol-data-analytics`](file:///home/jzuluaga/code/orbital-lab/mova-pro-futbol-data-analytics) como la plataforma canónica para datos deportivos de fútbol (Mundial, Premier League, Fantasy Premier League, apuestas y modelos probabilísticos).

El repositorio legacy `premier-league` / `premier-league-ml1` queda **deprecado** y toda la ingesta, colectores y vistas maestras han sido integrados en este proyecto.

---

## 2. Inventario de Datos Unificados (`data/mundial.db`)

| Tipo de Dato | Cantidad de Filas | Colector / Fuente |
| :--- | :--- | :--- |
| **Eventos Opta con Coordenadas $(x,y)$** | **607,930** | WhoScored (Mundial + Premier League) |
| **Eventos StatsBomb (Entrenamiento $xG$)** | **462,462** | StatsBomb Open Data (WC2018/2022) |
| **Historial Jugadores Fantasy (GW a GW)** | **19,375** | FPL API (`fpl_player_history`) |
| **Jugadores Fantasy Activos** | **841** | FPL API (`fpl_players`) |
| **Partidos Registrados** | **379** | WhoScored + football-data |
| **Cuotas de Casas de Apuestas** | **1,931** | The Odds API / Kalshi / Polymarket |

---

## 3. Colector Universal (`src/mova_data/collectors/fpl.py`)

La capa de recolección desacopla descarga e ingesta mediante la interfaz `BaseCollector`:
- **`FPLCollector`**: Maneja descargas idempotentes de `bootstrap-static`, `fixtures` y `element-summary/{player_id}`.
- **`FPLLoader`**: Procesa los JSONs descargados en caché y realiza la ingesta relacional en SQLite.
- **CLI:** `python scripts/collect_fpl.py --all`

---

## 4. Vistas Maestras de Analítica

### A. **`v_master_player_gw`**
Unifica el rendimiento individual por jugador y jornada:
```sql
SELECT player_name, position_name, team_short, cost_millions, total_selected_pct, current_form 
FROM v_master_player_gw 
ORDER BY total_selected_pct DESC;
```

### B. **`v_master_match_analytics`**
Unifica partidos con estadísticas de tiro, goles acumulados y probabilidades de mercado:
```sql
SELECT match_id, competition, home_team, away_team, n_events, n_shots, p_home_win 
FROM v_master_match_analytics;
```

---

## 5. Deprecación del Repositorio Legacy (`premier-league`)

- Todo el código de ingesta y despliegue del VPS en `/opt/orbital/services/premier-league-api/` fue migrado a la estructura `src/mova_data/` de este repositorio.
- Las consultas del curso ML1 y modelos de la U. Externado pueden consumir los endpoints directamente desde `v_master_player_gw` y `v_master_match_analytics`.
