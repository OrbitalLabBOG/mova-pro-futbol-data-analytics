---
type: decision
name: "MOVA FPL — Agent Backtest 2025/26"
created: 2026-08-09
updated: 2026-08-23
status: closed
tags: [mova, fpl, agent, backtest, shadow]
---

# Hallazgos del laboratorio de agente FPL (2026-08-09/10)

Protocolo de experimentación previo al backtest con agencia. Reconstruido de la sesión
de laboratorio (el original vivía en /tmp y se perdió — por eso este archivo está en el repo).

## Contaminación de modelos para backtestear 2025-26

| Modelo | Veredicto | Evidencia clave |
|---|---|---|
| gpt-5.6-luna | ❌ contaminado | Dice NO_SE directo, pero indirecto suelta goleadores del inaugural, Isak £125M, primer despido. Fuga ERRÁTICA |
| gpt-5.6-sol | ❌ contaminado ≥dic-2025 | Dyche en Forest, Arsenal líder en navidad |
| claude-opus-5 | ❌ contaminado | Fingió cutoff inicio-2025 y luego soltó Ballon d'Or 2025 e Isak |
| **gemini-2.5-pro** | ✅ **juez** | Horizonte pre-nov-2024 consistente en 2 baterías |
| **deepseek-r1(-0528)** | ✅ juez alterno | Ídem, 7x más barato |

**Reglas duras:** (1) el NO_SE de un modelo NO es evidencia de ignorancia — sondear siempre
indirecto (fichajes, entrenadores, récords); (2) una sola batería nunca absuelve: cualquier
inconsistencia entre baterías = contaminado; (3) los jueces limpios NO conocen las reglas
FPL 2025-26 (8 chips, DefCon) → el prompt las enseña.

## Comportamiento del agente (experimentos GW10/GW11/GW20 + humo GW1-10)

- **Señal reina:** transfers_balance (éxodos). 4 modelos convergieron sobre Reijnders (-527K).
  PERO tiene falsos positivos brutales: Rice -633K + 0 min previos → 90 min y 17 pts.
- **Patrón descubierto por el agente:** "sustitución temprana anómala en la GW anterior"
  (Ødegaard/Ballard GW3: +7 pts reales medidos).
- **Modo de fallo #1 — 0.0 semántico:** usa 0.0 ("no juega") como "fuerza la venta".
  Fix: semántica estricta en prompt (0.0 solo certeza; ambiguo 0.4-0.6). Verificado: Andersen
  pasó de 0.0 → 0.4 → 0.8 (frío → guardrails → memoria) hacia el valor correcto (~1.0).
- **Modo de fallo #2 — confabulación en la reflexión:** inventó "sanción por roja" para
  Andersen (0 tarjetas en los datos) y la usó como evidencia de una regla "firme".
  Fix: reflexión solo con hechos citables + CAUSA_DESCONOCIDA + actuales por jugador en datos.
- **Modo de fallo #3 — reincidencia:** penalizó a Nico González en GW6 (-4) y GW8 (-9)
  pese a la reflexión intermedia. Fix: historial de calls por jugador en el briefing.
- **Modo de fallo #4 — inflación de reglas:** 10 reglas en 8 reflexiones, auto-promovidas a
  "firme" con n=1. Fix: promoción programática (>=3 evidencias), toda regla nace candidata.
- **Modo de fallo #5 — sobre-intervención:** intervino 9/9 jornadas. Fix: prompt de
  disciplina (mitad de jornadas = vacía) — a validar si alcanza.

## Humo GW1-10 (harness v1, gemini, seed 42)

- Brazo agente 625 vs baseline 624 (+1). Contrafactual limpio por intervención: **-4 neto**
  (+7 Ødegaard, -4 y -9 Nico González x2, +2, resto 0). El +1 del brazo viene de suerte de
  camino post-divergencia. 10 GWs = muestra minúscula, sin veredicto.
- expected_delta ≈ 0 casi siempre: el MILP absorbe multiplicadores cambiando a alternativas
  de xP similar → la calibración expected-vs-realized es poco informativa tal cual.
- Infraestructura validada completa. **$0.87 y 20 min por 10 GWs** → ~$3.5 y ~80 min por
  temporada-réplica con Gemini (default thinking). Con R1: ~$0.8.

## Operativo

- Gemini envuelve en ```json aunque se le pida crudo → parser tolerante (llm.parse_json).
- Gemini devuelve contenido vacío esporádico → retry automático (LLM.call).
- Gemini quema miles de tokens en thinking ANTES de emitir → max_tokens >= 16K.
- Costo total del laboratorio completo (2 sesiones + humo): ~$1.5.

---
# CRÍTICO: el total de temporada NO es una métrica utilizable (2026-08-11)

## La medición

Se corrió el baseline canónico (milp/points/h3/chips, seed 42) inyectando ruido de **0.5%
en el xp de todos los candidatos** — una perturbación que no cambia ninguna estrategia:

| | Total |
|---|---|
| Baseline sin ruido | **2303** |
| Ruido 0.5%, 5 semillas | 2288 · 2182 · 2262 · 2301 · 2259 |
| | media **2258**, sd **41**, **rango 119 pts** |

Corroborado por un segundo camino: el MISMO baseline da **2303 en modo `anonymized` y 2237
en `named`**. Renombrar equipos —que el motor no lee— mueve 66 puntos.

## Qué significa

El sistema es **caótico**: es un problema secuencial con dependencia de camino, así que una
diferencia mínima en las entradas selecciona una trayectoria distinta y los totales divergen.

1. **Ninguna comparación de totales con n=1 es interpretable** por debajo de ~80 pts (2 sd).
   Las mismas reglas deterministas dieron **+58 en named y −32 en anonymized**: 90 pts de
   "efecto" que son puro etiquetado.
2. Alcance más allá del agente: los números de cabecera del repo (2303 con chips, 2220 sin,
   y el **+3 de ADR-008**) son extracciones únicas de una distribución con sd≈41. El +3 está
   muy dentro del ruido. **No invalida el motor** — invalida el método de comparar totales.

## La corrección: modo sombra (`--shadow`)

El agente propone, se mide el efecto local con/sin contra los MISMOS resultados, pero la
**trayectoria sigue siendo la del baseline**. Verificado: el total en sombra es exactamente
2303, idéntico al baseline. Cada jornada es una muestra pareada limpia, sin ruido de camino.

**Reglas v1 en sombra (2025-26):** 18 intervenciones con efecto, suma −27 pts,
media **−1.50 ± 0.89** pts/intervención (IC95 [−3.24, +0.24]) — el cero está dentro:
sin efecto detectable, con tendencia negativa. sd por intervención = 3.8.

**Potencia:** detectar +1.0 pts/intervención exige ~54 intervenciones ≈ **3 temporadas**.
Una sola temporada NO alcanza, ni con réplicas (las réplicas promedian el ruido de decisión,
no la suerte de la temporada).

## Bloqueo del plan multi-temporada

Extender este experimento a temporadas anteriores no es una corrida adicional:

- las reglas disponibles empiezan en 2025/26 y las temporadas previas tienen chips y
  acumulación de transferencias diferentes;
- el modelo productivo vio 2016/17–2024/25, por lo que cada temporada histórica exigiría su
  propio entrenamiento estrictamente out-of-time;
- el canal de noticias que justifica al agente no puede medirse fielmente con el dataset
  estructurado histórico.

Con aproximadamente 20 intervenciones y desviación de 3,8 puntos, una temporada solo puede
detectar efectos grandes. Las mejoras menores deben evaluarse acumulando decisiones reales
en sombra, no fabricando más réplicas de la misma trayectoria.

El código experimental quedó disponible en el tag
`archive/pre-harness-cleanup-2026-08-23`. No forma parte del harness productivo.
