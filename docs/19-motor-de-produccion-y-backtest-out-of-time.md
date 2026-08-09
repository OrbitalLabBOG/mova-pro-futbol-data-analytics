# Guía Operativa: Validación Out-of-Time y Ejecución en Producción (`live_agent_runner.py`)

> ⚠️ **DOCUMENTO SUPERADO — se conserva como registro histórico.**
>
> Describe el intento de motor FPL previo (`src/mova_model/fpl_*.py`,
> `scripts/live_agent_runner.py`, `scripts/train_fpl_xp_v*.py`), que tiene **leakage
> estructural** y reporta cifras que no son reproducibles. Ese código está congelado.
>
> El motor vigente es el paquete `mova_fpl/`. Ver
> [21-motor-fpl-arquitectura.md](21-motor-fpl-arquitectura.md) y
> [runbook-fpl.md](runbook-fpl.md).


> **Manual de Operación en Vivo v1.0**  
> Proyecto: `mova-pro-futbol-data-analytics` | Operador: **Agente Autónomo MOVA**

---

## 1. Validación Out-of-Time (A Ciegas / Blindfold Cross-Validation)

Para verificar qué tan bueno es el modelo **sin sesgos ni data leakage** de cara al arranque de la Premier League en 2 semanas, implementamos el protocolo `src/mova_model/out_of_time_xp.py`:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Entorno de Entrenamiento (GW 1 a 15)  ──► Modelo Congelado (MIP + GBDT) │
│                                                │                         │
│                                                ▼                         │
│ Evaluación a Ciegas (GW 16 a 30)      ──► Puntos Reales: 2,001.5 pts    │
└──────────────────────────────────────────────────────────────────────────┘
```

### Resultados de la Evaluación Out-of-Time (GW 16 a 30):
- **Entrenamiento:** Únicamente con partidos pasados ($GW \le 15$).
- **Evaluación a Ciegas:** $GW 16 \dots 30$ congeladas sin ver ningún dato futuro.
- **Puntos Reales Ganados (15 GWs):** **`790` pts** (`52.67` pts/GW).
- **Proyección Temporada Completa:** **`2,001.5` pts** (superando al mánager humano promedio de `1,900` pts).

---

## 2. Guía de Operación en Producción (En 2 Semanas)

Cuando la nueva temporada de la Premier League arranque en 2 semanas, el agente operará automáticamente ejecutando el script `scripts/live_agent_runner.py`:

```bash
# 1. Ejecutar en modo simulación de producción (Dry-Run para GW1)
python scripts/live_agent_runner.py --gameweek 1 --dry-run

# 2. Ejecutar para la Gameweek en vivo
python scripts/live_agent_runner.py --gameweek 1
```

### Flujo de Producción del Runner:
1. **Descarga en Tiempo Real:** Se conecta a `https://fantasy.premierleague.com/api/bootstrap-static/` y `fixtures/`.
2. **Matriz de Inferencia $xP$:** Genera la predicción de $xP$ utilizando `FPLInferenceEngine`.
3. **Solucionador MILP:** Ejecuta la optimización combinatoria en < 0.1 segundos (£100M, máx 3 por club).
4. **Emisión de Acta:** Genera el informe oficial con los 11 titulares, capitán, banca y transferencias en `outputs/live_decision_GW{gw}.md`.
