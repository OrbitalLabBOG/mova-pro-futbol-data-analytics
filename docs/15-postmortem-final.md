# Post-mortem final — cómo le fue al modelo en el Mundial 2026

> **2026-07-20.** Torneo terminado: **🏆 España campeón** (1-0 a Argentina, 2026-07-19). Datos completos: 104/104 partidos con eventos (163.688 eventos WhoScored), `validate.py` TODO OK.
> Este doc evalúa el último pronóstico pre-eliminatorias-tardías (run `20260702T230431`, congelado el 2-jul con 16avos en curso) contra lo que terminó pasando.

## Resultado real del torneo

- **Final:** España 1-0 Argentina.
- **Semis:** Francia 0-2 España · Inglaterra 1-2 Argentina.
- **Tercer puesto:** Francia 4-6 Inglaterra.
- **Cuartofinalistas:** Francia, Marruecos, España, Bélgica, Noruega, Inglaterra, Argentina, Suiza.

## Qué tan bueno fue el pronóstico

### El bracket quedó a UN partido de la perfección en la parte alta

El modelo proyectaba **SF1: Francia vs España** y **SF2: Argentina vs Inglaterra** — las dos semifinales reales fueron exactamente esas, con los cruces exactos. Acertó el ganador de SF2 (Argentina 59% ✓) y falló solo SF1 (Francia 54%, ganó España). Ese único partido convirtió la final proyectada (Francia-Argentina, campeón Francia) en la real (España-Argentina, campeón España).

### Métricas duras

| Nivel | Resultado |
|---|---|
| Partido a partido (9 pre-match evaluables, 16avos) | **RPS 0.153, 7/9 aciertos** (mejor que el backtest histórico: 0.216) |
| Cuartofinalistas (top-8 por p_qf) | 5/8 — fallaron Suiza (28%), Noruega (34%), Bélgica (49%; dos eran coin-flips: Colombia 53%, USA 51%) |
| Semifinalistas (top-4) | 3/4 — faltó Inglaterra (31%) |
| Finalistas (top-2) | 1/2 — Argentina ✓, España era 3º (27%) |
| Campeón | 0/1 — pick Francia 29%, ganó España 16.1% |
| Brier por ronda | QF 0.098 · SF 0.042 · Final 0.038 · Campeón 0.026 — bien calibrado |

El fallo genuino a nivel partido fue **Brasil 1-2 Noruega** (modelo y mercado ~51% Brasil, RPS 0.429) — upset que nadie tenía.

### La capa de estrategia de polla SÍ acertó ✅

El pick sheet del 2-jul decía textualmente:

- Pick seguro: Francia (29%) — falló.
- **Pick de valor: España (leverage 1.31 🟢) → "diferenciador"** — **España fue campeón.**
- Evitar: Brasil (sobre-elegido, 0.74 🔴) — eliminado en octavos por Noruega. ✓
- Francia "cara" vs modelo (−3.4pp 🔴). ✓

Quien siguió la recomendación de valor le ganó al 28% del público que iba con Francia y al 22% que iba con Argentina. **La tesis central del proyecto — el edge no está en out-predecir al mercado sino en la capa de estrategia (leverage vs público) — quedó validada empíricamente.**

## Por qué se desfasó el pick de campeón

Lo irónico: **las señales propias del modelo apuntaban a España, y el anclaje al mercado las diluyó.**

1. **El ancla al mercado (w=0.65) importó el sesgo pro-Francia.** El 2-jul Kalshi/Polymarket/casas tenían a Francia en 33-34% (España 12-14%). El componente propio del modelo remaba al lado correcto — España +3.3pp sobre mercado ("🟢 infravalorado"), Francia −3.4pp ("🔴 caro") — pero el ancla lo aplastó. Es el trade-off documentado en [docs/10](10-backtest-y-critica.md): anclarse baja el error promedio, pero copia los errores del mercado cuando el mercado se equivoca.

2. **El Elo (core del modelo) ya tenía a España #1** el 2-jul (2159 vs Francia #3, 2134). El 29% de Francia no salía del rating sino del ancla + camino de bracket blando (Suecia en 16avos, mitad débil → 45% a la final).

3. **La capa de regresión xG advirtió literalmente lo de Francia.** El insight del 2-jul: Francia +4.0 goles sobre xG → "⚠️ finaliza sobre xG (regresa)". Y regresó: 0-2 con España en semis y 4-6 con Inglaterra por el tercer puesto (6 goles encajados). La señal existía; no pesaba en el ranking porque los experimentos mostraron que *en promedio* es ruido — en este caso concreto era la señal correcta.

4. **Lo demás fue varianza normal de eliminación directa.** España campeón al 16% es un evento 1-de-6. Un campeón pickeado al 29% falla 7 de cada 10 mundiales; por eso el diseño correcto era el que se hizo: pick seguro + pick de valor.

## Veredicto

El modelo rindió al nivel de su promesa: **≈ mercado, bien calibrado, bracket estructuralmente casi perfecto** (ambas semifinales exactas). El pick de campeón "seguro" falló como falla el favorito la mayoría de las veces; el pick de **valor** — la capa que este proyecto añadió sobre el mercado — señaló al campeón real.

## Lección para la próxima iteración

**Cuando Elo propio + Δ-valor vs mercado + regresión xG coinciden en contra del favorito del mercado, ese consenso interno merece bajar el peso del ancla** (w dinámico en vez de w=0.65 fijo). Las tres señales internas coincidían en España > Francia y el blend las suprimió. Candidato concreto: w = f(acuerdo entre señales internas), backtesteable con WC2018/22 + este torneo.

## Reproducibilidad

- Predicciones evaluadas: tabla `match_predictions` / `tournament_sim`, run `20260702T230431`.
- Resultados reales: tabla `matches` (status 6, 104/104).
- Los números de este doc se calcularon con RPS estándar y Brier por ronda sobre esas tablas.
