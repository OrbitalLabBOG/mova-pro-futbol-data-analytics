# WP-005 · Evaluacion por componente · 2025-26 GW20-38

Proyecciones: 15,163 · con minutos jugados: 5,299

## Calibracion por componente

| Componente | Predicho (total) | Real (total) | Sesgo | Sesgo relativo |
|---|---:|---:|---:|---:|
| `pts_aparicion` | 9,488 | 9,614 | -126 | -1.3% |
| `pts_goles` | 2,516 | 2,393 | +123 | +5.2% |
| `pts_asistencias` | 1,397 | 1,404 | -7 | -0.5% |
| `pts_cs` | 2,589 | 2,395 | +194 | +8.1% |
| `pts_encajados` | -834 | -824 | -10 | -1.2% |
| `pts_defcon` | 1,296 | 1,416 | -120 | -8.4% |
| `pts_bonus` | 992 | 1,209 | -217 | -17.9% |
| `pts_tarjetas` | -711 | -798 | +87 | +11.0% |
| `pts_paradas` | 203 | 231 | -28 | -12.1% |
| `pts_otros` | -3 | -21 | +18 | +85.0% |
| **total** | **16,933** | **17,009** | **-76** | **-0.4%** |

Correlacion xP con puntos reales: **0.590** (por jugador-jornada, 15,163 pares).

## Calibracion de la contribucion defensiva (AC-WP005-004)

ECE global **0.0110** (umbral 0,08) · Brier 0.0859 · tasa base 0.134 · n = 5,278

| Posicion | n | ECE | Predicho | Observado |
|---|---:|---:|---:|---:|
| DEF | 1,966 | 0.0188 | 0.220 | 0.202 |
| FWD | 745 | 0.0045 | 0.010 | 0.009 |
| MID | 2,567 | 0.0078 | 0.125 | 0.118 |

### Curva de calibracion

| Bin | n | Predicho | Observado |
|---|---:|---:|---:|
| 0.0-0.1 | 3,117 | 0.015 | 0.016 |
| 0.1-0.2 | 659 | 0.145 | 0.129 |
| 0.2-0.3 | 442 | 0.251 | 0.242 |
| 0.3-0.4 | 317 | 0.345 | 0.325 |
| 0.4-0.5 | 310 | 0.444 | 0.400 |
| 0.5-0.6 | 260 | 0.549 | 0.512 |
| 0.6-0.7 | 122 | 0.644 | 0.615 |
| 0.7-0.8 | 44 | 0.742 | 0.636 |
| 0.8-0.9 | 4 | 0.835 | 0.500 |
| 0.9-1.0 | 3 | 0.960 | 0.333 |

## Componente de bonus, reportado por separado (AC-WP005-006)

| | Predicho | Real |
|---|---:|---:|
| Puntos de bonus | 992 | 1,209 |
| Cuota del xP total | 5.9% | 7.1% |

El bonus se aisla porque su sesgo para 2026/27 esta identificado y no medido (R-04): el BPS cambia en cuatro reglas y la que mas pesa —CBI pasa de 1 punto por cada 2 acciones a 1 por cada 3— rebaja el BPS de defensas y porteros. El componente queda **sobreestimado para esas dos posiciones** en 2026/27, y esa parte del xP es la unica que hay que descontar mentalmente.

## Probabilidad de jugar (heredada de WP-004)

ECE de P(juega) sobre esta ventana: **0.0249**

| Bin | n | Predicho | Observado |
|---|---:|---:|---:|
| 0.0-0.1 | 6,750 | 0.021 | 0.014 |
| 0.1-0.2 | 951 | 0.145 | 0.126 |
| 0.2-0.3 | 805 | 0.247 | 0.202 |
| 0.3-0.4 | 533 | 0.347 | 0.291 |
| 0.4-0.5 | 409 | 0.449 | 0.433 |
| 0.5-0.6 | 488 | 0.554 | 0.520 |
| 0.6-0.7 | 444 | 0.648 | 0.635 |
| 0.7-0.8 | 706 | 0.761 | 0.724 |
| 0.8-0.9 | 1,114 | 0.849 | 0.794 |
| 0.9-1.0 | 2,963 | 0.941 | 0.896 |
