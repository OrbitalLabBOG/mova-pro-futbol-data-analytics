# MOVA Mundial 2026 — Predictor de la Polla

Modelo de predicción de resultados para la **Copa Mundial FIFA 2026** (USA/México/Canadá, 48 equipos).
Objetivo práctico: maximizar el puntaje esperado en la polla. Objetivo técnico: pipeline reutilizable de analítica deportiva (vertical **MOVA**).

> Estado: **arranque** · Creado 2026-06-28 (justo al cierre de fase de grupos, inicio de Ronda de 32).

## Tesis del proyecto

El formato de 48 equipos ha **subido la varianza** (más empates, más debutantes, calor y viajes castigando a favoritos). En polla con alta varianza conviene mezclar *chalk* (favoritos sólidos) con apuestas de valor controlado, no clavar todos los favoritos.

## Enfoque de modelamiento (planeado)

Stack inspirado en lo que la evidencia dice que funciona:

1. **Elo / Power Ratings** — el driver dominante (~80% del poder predictivo según comparativas de 10+ modelos).
2. **Dixon-Coles** — modelo de goles (Poisson bivariado con corrección para marcadores bajos) → probabilidades por partido.
3. **Ajuste por xG / suerte** — corregir sobre/sub-rendimiento de la fase de grupos (regresión a la media).
4. **Ajustes de contexto** — ventaja local (anfitriones), calor, viajes entre sedes, descanso.
5. **Monte Carlo del bracket** — simular la Ronda de 32 → final N veces para win-probabilities y bracket óptimo.
6. **Calibración vs. mercado** — contrastar con Kalshi/Polymarket/Opta para detectar *value* y errores del modelo.

## Estructura

```
mova-mundial-2026/
├── README.md
├── docs/
│   └── 01-panorama.md      # Investigación inicial: resultados, upsets, xG, modelos, mercados
├── data/
│   ├── raw/                # Datos crudos (resultados, rankings Elo, xG, odds)
│   └── processed/          # Datasets limpios para el modelo
├── src/                    # Código del modelo (Elo, Dixon-Coles, Monte Carlo)
├── notebooks/              # Exploración y prototipos
├── models/                 # Artefactos entrenados / parámetros
└── outputs/                # Predicciones, brackets, reportes
```

## Documentación

| Doc | Contenido |
|-----|-----------|
| [docs/01-panorama.md](docs/01-panorama.md) | Resultados fase grupos, upsets, tabla xG/suerte, modelos, mercados |
| [docs/02-fuentes-datos.md](docs/02-fuentes-datos.md) | **Disponibilidad de datos públicos/gratis, endpoints verificados, stack recomendado** |
| [docs/03-supermodelos-referencia.md](docs/03-supermodelos-referencia.md) | Probabilidades actuales de Opta/Kalshi/Polymarket/casas + divergencias = value |

## Stack de datos (gratis + permanente) — resumen

> ⚠️ **Clave:** el 20-ene-2026 FBref perdió la licencia Opta y Stats Perform quedó como distribuidor **exclusivo** de datos WC2026 → **no hay event data crudo gratis del Mundial 2026**. Estrategia: entrenar con histórico gratis + alimentar WC2026 con xG agregado. Detalle en [docs/02-fuentes-datos.md](docs/02-fuentes-datos.md).

- **Resultados/live**: ESPN hidden API + FIFA v3 (sin key, en vivo) + football-data.org (fallback).
- **Event data (train)**: StatsBomb Open Data (`statsbombpy`, hasta WC2022).
- **Event data (WC2026)**: Kaggle `mominullptr` (CC0, xG agregado diario).
- **Ratings**: eloratings.net/World.tsv (sin key) — el gap de Elo es el predictor #1.
- **Mercados**: Kalshi `KXMENWORLDCUP` (sin auth) + The Odds API (500/mes) + Polymarket Gamma.
- **Open-source base**: github.com/Hicruben/world-cup-2026-prediction-model (Elo + Dixon-Coles + Monte Carlo).

## Entorno

Python vía conda: `/home/jzuluaga/miniconda3/bin/python3` (3.13). Libs previstas: pandas, numpy, scipy, statsmodels, requests/httpx, matplotlib.
