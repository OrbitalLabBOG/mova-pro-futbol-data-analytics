---
name: fpl-expert
description: Especialista cuantitativo en reglas, estrategias, estimación de Expected Points (xP) y optimización MILP para la Fantasy Premier League (FPL 2025/2026).
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
---

# FPL Expert Skill — Reglas, Optimización y Simulador Autómata

Esta skill proporciona las reglas de negocio, matriz de puntuación, restricciones de optimización combinatoria y lógica de backtesting para construir agentes autónomos de Fantasy Premier League (FPL).

---

## 1. Matriz de Puntuación FPL (Fórmula Exacta)

$$\text{Points}_i = \text{MinPts}_i + \text{GoalPts}_i + \text{AstPts}_i + \text{CSPts}_i + \text{SavePts}_i + \text{PenSavPts}_i + \text{BPSBonus}_i - \text{CardPen}_i - \text{OwnGoalPen}_i - \text{ConcededPen}_i - \text{PenMissPen}_i$$

Donde por cada jugador $i$ en la jornada $t$:
- $\text{MinPts}$: 1 pt si $1 \le \text{min} < 60$; 2 pts si $\text{min} \ge 60$.
- $\text{GoalPts}$: GKP/DEF = $6 \times \text{goles}$; MID = $5 \times \text{goles}$; FWD = $4 \times \text{goles}$.
- $\text{AstPts}$: $3 \times \text{asistencias}$.
- $\text{CSPts}$ (si $\text{min} \ge 60$ y equipo no encaja goles): GKP/DEF = +4 pts; MID = +1 pt.
- $\text{SavePts}$: $\lfloor \text{atajadas} / 3 \rfloor$ (solo GKP).
- $\text{PenSavPts}$: $+5$ pts por cada penalti detenido.
- $\text{PenMissPen}$: $-2$ pts por cada penalti fallado.
- $\text{ConcededPen}$ (solo GKP/DEF): $-\lfloor \text{goles\_concedidos} / 2 \rfloor$.
- $\text{CardPen}$: $-1$ por Tarjeta Amarilla; $-3$ por Tarjeta Roja.
- $\text{OwnGoalPen}$: $-2$ por Autogol.
- $\text{BPSBonus}$: $+3, +2, +1$ segun posición relativa en el ranking BPS del partido.

---

## 2. Restricciones del Optimizador MILP (Mochila FPL)

Para cualquier ventana de planificación $T \dots T+k$:

```python
# Definición de variables MILP con PuLP / SciPy / OR-Tools
# x[i] = 1 si jugador i está en plantilla (15)
# s[i] = 1 si jugador i es titular (11)
# c[i] = 1 si jugador i es capitán (2x / 3x con TC)

budget_limit = 1000  # £100.0M en décimas
max_per_club = 3
squad_size = 15
starters = 11

pos_counts = {1: 2, 2: 5, 3: 5, 4: 3}  # GKP:2, DEF:5, MID:5, FWD:3
min_starters = {1: 1, 2: 3, 3: 2, 4: 1}
max_starters = {1: 1, 2: 5, 3: 5, 4: 3}
```

---

## 3. Matriz de Decisión de Chips ("Poderes")

| Chip | Condición de Activación Óptima | Justificación Estadística |
| :--- | :--- | :--- |
| **Wildcard 1** | GW6–GW9 o reestructuración masiva tras ventana de transferencias | Maximizar acumulación de valor de plantilla (price rises). |
| **Wildcard 2** | GW28–GW31 antes de las Double Gameweeks (DGW) | Configurar la plantilla para maximizar partidos dobles. |
| **Free Hit** | Blank Gameweek (BGW) severa (jornadas recortadas por copas) | Evitar hits de -4 manteniendo la plantilla base intacta. |
| **Bench Boost** | Big Double Gameweek (DGW34/DGW37) | Los 15 jugadores juegan 2 partidos (30 partidos jugados en 1 GW). |
| **Triple Captain** | DGW de un activo elite ($xG+xA > 1.2/90$, ej. Haaland / Salah) | Multiplicar 3x en jornada de 2 partidos (esperado $\ge 15-20$ pts). |

---

## 4. Reglas de Transferencias (FPL 2024–2026)

- **Transfer Free Transfers (FT):** Se otorga 1 FT por jornada.
- **Límite de Acumulación:** Hasta **5 FTs gratis**.
- **Conservación con Chips:** Activar Wildcard o Free Hit **NO destruye** las FTs acumuladas.
- **Costo Extra:** Cada transferencia por encima del saldo de FTs resta **-4 puntos**.

---

## 5. Endpoints de Ingesta y Vista Maestra (`v_master_player_gw`)

```sql
-- Consulta para alimentar el modelo de Expected Points (xP)
SELECT 
    player_id, player_name, position_name, team_short, 
    cost_millions, gw_xg, gw_xa, ict_sum, total_points, current_form
FROM v_master_player_gw
WHERE gameweek = :target_gw;
```
