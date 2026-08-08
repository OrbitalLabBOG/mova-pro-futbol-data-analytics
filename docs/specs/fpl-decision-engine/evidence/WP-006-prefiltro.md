# WP-006 · Evidencia — AC-WP006-006: el recorte de mercado, declarado y medido

**Fecha:** 2026-08-07 · **Temporada:** 2025-26 · **Modo:** `anonymized` · **Proyector:** `minutes`

## El problema que se está evitando

El sistema anterior filtraba el mercado a los veinte mejores por posición **sin decirlo**.
Eso rompe la garantía de optimalidad en silencio: si la mejor plantilla necesita un suplente
barato que no está entre los veinte mejores por xp, el solver nunca lo ve y devuelve un
óptimo local con cara de óptimo global. El workpack exige que, si hay recorte, su criterio
esté escrito y su efecto medido.

## Criterio declarado

`mova_fpl/optimizer/heuristics.py::shortlist` conserva, **por posición**:

1. los `top_k` mejores por xp **acumulado sobre todo el horizonte** (no sobre la jornada actual);
2. los `cheapest` más baratos — el relleno de banquillo del que depende la factibilidad presupuestal;
3. **siempre**, y al margen de lo anterior, a todo miembro de la plantilla vigente. Si el
   recorte borrara a un titular, el modelo no podría decidir *no venderlo*, que suele ser la
   decisión correcta.

`top_k = 0` desactiva el recorte por xp y deja pasar el mercado entero. Es el modo de
referencia con el que se mide todo lo de abajo.

Valores por defecto: `top_k = 30`, `cheapest = 6`. Sobre un mercado de ~800 jugadores eso
deja unos 140.

## Efecto medido sobre la optimalidad — horizonte 1

Misma jornada, mismo estado, mismo `xp`; sólo cambia `top_k`. Se compara el **valor
objetivo** del solver, que es la medida directa de optimalidad.

| GW | Mercado | top_k=15 | top_k=30 | top_k=60 | Sin recorte | Brecha de `top_k=30` |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 690 | 56.97 | 57.55 | 57.88 | 57.88 | **+0.575%** |
| 8 | 745 | 76.45 | 76.45 | 76.45 | 76.45 | 0.000% |
| 15 | 759 | 66.88 | 66.92 | 66.92 | 66.92 | 0.000% |
| 22 | 799 | 67.18 | 67.18 | 67.18 | 67.18 | 0.000% |
| 26 *(doble)* | 817 | 92.86 | 92.92 | 92.92 | 92.92 | 0.000% |
| 33 *(doble)* | 829 | 109.14 | 109.14 | 109.14 | 109.14 | 0.000% |

**La brecha es cero en cinco de seis jornadas.** La excepción es la GW1, y tiene explicación:
es el único arranque en frío, donde se eligen los quince desde cero y el presupuesto ata la
solución a jugadores baratos que el recorte por xp no prioriza. Aun así la pérdida es del
0.575% del objetivo.

`top_k = 15` sí pierde de forma visible (GW1: 56.97 contra 57.88, −1.6%). Por eso el defecto
es 30 y no 15.

## Coste en tiempo

Arranque en frío, que es el caso peor: sin plantilla previa las quince plazas están libres en
cada jornada del horizonte y el problema es combinatorio puro.

| GW | Horizonte | `top_k=30` | Sin recorte | Factor | Brecha |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0.1s | 0.2s | 2× | +0.575% |
| 8 | 1 | 0.1s | 0.5s | 5× | 0.000% |
| 26 | 1 | 0.1s | 0.3s | 3× | 0.000% |
| 8 | 3 | 0.8s | 5.9s | 7× | 0.000% |
| 26 | 3 | 0.6s | 4.2s | 7× | 0.000% |
| 8 | 5 | 71.1s | 242.7s | 3.4× | 0.000% |
| 26 | 5 | 3.5s | 52.2s | 15× | +0.015% |
| 8 | 8 | 267.4s | 601.5s | 2.2× | **−0.033%** |

### La brecha negativa importa

En GW8 con horizonte 8, la corrida **sin recorte** devolvió una solución **peor** que la
recortada. No es una contradicción: agotó el límite de 600 segundos y entregó la mejor
solución encontrada, sin haber probado optimalidad. A horizontes largos "sin recorte" deja
de ser la referencia de optimalidad y pasa a ser sólo un modelo más grande que el solver no
alcanza a cerrar.

Es un argumento a favor del recorte más fuerte que el del tiempo: **con presupuesto de
cómputo acotado, un modelo pequeño resuelto a optimalidad le gana a uno grande resuelto a
medias.**

### Temporada completa

| Configuración | 38 jornadas |
|---|---:|
| `milp` h=1, `top_k=30` | 302 s |
| `milp` h=5, `top_k=30` | 110 s |

El horizonte largo es **tres veces más rápido** que el corto, que es lo contrario de lo
esperable. La explicación es la simetría: con horizonte 1 el objetivo es plano y hay muchas
plantillas casi idénticas en valor, así que el *branch and bound* tarda en probar que ya
tiene la mejor. Con horizonte 5 el objetivo discrimina más y el árbol se poda antes. El
modelo grande no siempre es el modelo lento.

## Conclusión operativa

- **Horizonte 1:** el recorte no hace falta. Cuesta décimas de segundo resolver el mercado
  completo, así que `top_k = 0` da optimalidad garantizada gratis. Es lo recomendable para la
  decisión en vivo de una jornada.
- **Horizonte 3 a 5:** el recorte es necesario y su coste medido en optimalidad va de 0.000%
  a +0.015%. Se conserva `top_k = 30`.
- **Horizonte 8:** el recorte deja de ser una concesión y pasa a ser la mejor opción
  disponible: sin él, el solver no cierra dentro del presupuesto y entrega una solución peor.
- **La GW1 merece trato aparte.** Es el único punto donde el recorte tiene un coste medible
  y es también la decisión más importante de la temporada — se construye la plantilla entera.
  Para WP-007 se correrá con `top_k = 0`, aceptando el tiempo extra.

Todo lo anterior es reproducible: `shortlist` devuelve un `ShortlistReport` con cuánto
recortó, y ese informe queda escrito en las `notes` de cada `Decision`, es decir, en la traza
de cada jornada de cada corrida. El recorte no puede volverse invisible.
