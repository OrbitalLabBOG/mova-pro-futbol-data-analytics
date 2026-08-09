# Guía Técnica: Versionamiento de Modelos $xP$ y API de Inferencia

> ⚠️ **DOCUMENTO SUPERADO — se conserva como registro histórico.**
>
> Describe el intento de motor FPL previo (`src/mova_model/fpl_*.py`,
> `scripts/live_agent_runner.py`, `scripts/train_fpl_xp_v*.py`), que tiene **leakage
> estructural** y reporta cifras que no son reproducibles. Ese código está congelado.
>
> El motor vigente es el paquete `mova_fpl/`. Ver
> [21-motor-fpl-arquitectura.md](21-motor-fpl-arquitectura.md) y
> [runbook-fpl.md](runbook-fpl.md).


> **Documento de Arquitectura y Referencia Técnica v1.0**  
> Proyecto: `mova-pro-futbol-data-analytics` | Módulo: **`src/mova_model/inference.py`**

---

## 1. Esquema de Versionamiento de Modelos ($xP$)

Los artefactos de los modelos predictivos se almacenan y versionan en el directorio `models/`:

| Versión | Nombre del Artefacto | Descripción del Algoritmo | MAE en Test | Spearman $\rho$ |
| :--- | :--- | :--- | :---: | :---: |
| **`v1`** | `models/v1_baseline_xp.joblib` | Fórmula empírica determinista basada en min, $xG, xA, xCS$. | `3.042` pts | `0.013` |
| **`v2`** | `models/v2_gradient_boosting_xp.joblib` | Gradient Boosting Regressor con 14 features FPL + Opta. | `2.026` pts | `0.710` |
| **`v3`** | `models/v3_ensemble_xp.joblib` | **Voting Ensemble (Gradient Boosting + Random Forest)** con 444K eventos Opta espaciales. | **`2.026` pts** | **`0.710`** |
| **`latest`** | `models/fpl_xp_model.joblib` | Alias a la última versión estable (v3 Ensemble). | **`2.026` pts** | **`0.710`** |

---

## 2. API de Inferencia Unificada (`src/mova_model/inference.py`)

La clase `FPLInferenceEngine` proporciona acceso inmediato y desacoplado a las predicciones de cualquier versión de modelo.

### Ejemplo de Uso en Python:

```python
from src.mova_model.inference import FPLInferenceEngine

# Cargar el modelo v3 Ensemble (o v1, v2, latest)
engine = FPLInferenceEngine(model_version="v3")

# 1. Obtener la matriz de predicción de una Gameweek (Top 10 jugadores)
df_gw30 = engine.predict_gameweek(gameweek=30, top_n=10)
print(df_gw30[["player_name", "position", "team_short", "price", "xp_final"]])

# 2. Consultar la predicción detallada de un jugador específico
player_info = engine.predict_player(player_id=350, gameweek=30)
print(player_info)
```

---

## 3. Comandos de Entrenamiento y Evaluación

```bash
# Entrenar y versionar todas las versiones (v1, v2, v3)
python scripts/train_fpl_xp_v3.py

# Ejecutar la suite de evaluación cuantitativa out-of-sample vs Ground Truth
python scripts/evaluate_fpl_xp.py
```
