# Runbook — operar una jornada de FPL

Para la persona que tiene que emitir el acta antes del cierre, incluso si algo se rompió.

---

## 0. Lo que hay que saber antes de tocar nada

- **El motor no escribe en FPL y no puede.** La única primitiva de red del paquete es un
  `GET` (`data/sources.py`), verificado por `tests/test_readonly_http.py`. El acta es un
  documento; el equipo lo introduce una persona. Si el motor se equivoca, el daño máximo es
  una recomendación mala, nunca una transferencia gastada.
- **La única acta que cuenta es la última.** Los precios se mueven a diario y el parte
  médico cambia hasta minutos antes del cierre. Un acta emitida con más de dos días de
  antelación se marca sola como borrador.
- **El deadline no se mueve.** GW1 de 2026/27: `2026-08-21T17:30:00Z` = 12:30 en Bogotá.

## 1. Correr una jornada

```bash
cd ~/code/orbital-lab/mova-pro-futbol-data-analytics

# ensayo: escribe el acta pero no toca la traza
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0 --dry-run

# de verdad: persiste la decisión en la traza como `committed`
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0
```

El acta queda en `outputs/fpl/2026-27/gwNN_decision.md`. Tarda unos **5 segundos**.

| Opción | Para qué | Recomendado |
|---|---|---|
| `--horizon N` | Jornadas que mira hacia adelante | **3** (ver §5) |
| `--top-k 0` | Sin recorte de mercado: optimalidad garantizada | **0** en vivo |
| `--policy` | `milp` u `greedy-stub` | `milp`; la voraz es el plan B |
| `--dry-run` | No escribe en la traza | Para ensayar |

## 2. Cuándo correrla

| Momento | Qué hacer |
|---|---|
| Al abrir la temporada | Una corrida para ver por dónde va el equipo. Es un borrador. |
| 48 h antes del cierre | Otra corrida. Empiezan a salir las ruedas de prensa. |
| **Dentro de las 24 h previas** | **La corrida que vale.** Esta es la que se introduce. |
| Después del cierre | Nada. El acta ya no sirve; la siguiente jornada es otra corrida. |

## 3. Reentrenar los modelos

Los artefactos `.joblib` no están en Git (son regenerables y pesan). Después de clonar, o
cuando entren datos nuevos:

```bash
python -m mova_fpl.data.ingest --all          # almacén canónico, idempotente
python -m mova_fpl.cli.train_minutes --holdout 2025-26
python -m mova_fpl.cli.train_points  --holdout 2025-26
```

`--holdout` es la temporada que **no** entra al ajuste. Para operar 2026/27 el holdout es
`2025-26`, lo que en la práctica significa: ajusta con las nueve temporadas anteriores y usa
2025-26 como estado del jugador. Cambiarlo sin pensarlo mete leakage.

## 4. Si algo falla antes del deadline

### La API de FPL no responde

`data/sources.py` reintenta cinco veces con espera creciente. Si aun así falla:

1. **Comprobar que es la fuente y no la red:**
   `curl -s -o /dev/null -w "%{http_code}\n" https://fantasy.premierleague.com/api/bootstrap-static/`
2. **Si la API está caída**, no hay estado público que leer y el motor no puede decidir con
   datos frescos. El plan B es manual: abrir la web de FPL, que suele seguir en pie aunque la
   API pública falle, y armar el equipo con el acta más reciente como guía. Está para eso.
3. **Nunca inventar datos** para que el pipeline corra. Un acta con precios de hace una
   semana es peor que ninguna, porque parece fresca.

### El optimizador dice `Infeasible`

Trae la lista de motivos. Los tres reales:

| Motivo | Qué significa | Salida |
|---|---|---|
| `solo N GKP en el mercado` | El catálogo llegó incompleto | Reintentar; si persiste, es la fuente |
| `la plantilla más barata cuesta X` | El presupuesto no alcanza | Solo puede pasar con estado corrupto |
| `con máximo 3 por club...` | Muy pocos clubes juegan | Jornada con muchos blancos: bajar `--horizon` |

### El acta sale marcada como INVÁLIDA

`validate_squad` encontró una violación. **No introducir ese equipo.** El acta lista los
códigos exactos. Correr con `--policy greedy-stub`, que es la heurística probada de WP-003, y
comparar. Si las dos fallan, es un problema de datos, no de política.

### Falta el `.joblib` de un modelo

```
FileNotFoundError: models/points/points-1.0.0.joblib
```

Reentrenar (§3). Toma menos de dos minutos.

## 5. Qué horizonte usar

**Por defecto 3.** No porque esté demostrado que es el mejor, sino porque:

| Horizonte | 2025-26 con `minutes` | 2025-26 con `points` |
|---:|---:|---:|
| 1 | 2.014 | 2.178 |
| **3** | 2.010 | **2.217** |
| 5 | **2.131** | 2.207 |
| 8 | 2.080 | — |

El orden **se invirtió** al mejorar el proyector: con un modelo, ganaba 5 y perdía 3; con el
otro, al revés. Diferencias que cambian de orden al tocar otra pieza del sistema están dentro
del ruido de una sola temporada. Es la pregunta abierta **Q-05**.

Mientras no se resuelva con más temporadas, se usa **3**: es el mejor con el modelo vigente
y está en el medio del rango, que es donde conviene estar cuando no se sabe.

## 6. Verificar que todo sigue en pie

```bash
pytest -q                                     # 509 pruebas
pytest -m slow -q                             # temporada completa, ~3 min
pytest tests/test_readonly_http.py -v         # solo GET contra FPL
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points --horizon 3
```

El backtest completo tarda unos dos minutos y debe dar **2.217** puntos con la semilla 42. Si
da otra cosa, algo cambió y hay que averiguar qué antes de operar.

## 7. Consultar lo ya decidido

```python
from mova_fpl.trace.query import runs, decisions
runs()                                        # todas las corridas
decisions("2026-27-live-milp-h3")             # decisiones de la corrida en vivo
```

La traza vive en `data/processed/trace.db`. Cada decisión guarda su huella
(`fingerprint`), que permite comprobar si dos corridas decidieron lo mismo.

## 8. Desde la GW2

Hace falta el **`entry_id`** del equipo de Julián para leer el estado real: plantilla
vigente, banco, transferencias libres acumuladas y chips ya gastados (pregunta abierta
**Q-01**). Sin él, de la GW2 en adelante el motor no sabe de qué plantilla parte y solo
puede proponer un equipo desde cero, que no es la decisión que toca.

Se obtiene entrando a la web de FPL con la cuenta: el número aparece en la URL de
`/entry/<ID>/event/<GW>/`.
