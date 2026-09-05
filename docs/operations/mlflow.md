---
title: MOVA — MLflow y versionamiento MLOps
status: active
owner: MOVA Fantasy
---

# Tracking privado y evidencia reproducible

MLflow 3.16.0 corre como servicio separado de FPL en
`https://mlflow.72-60-245-2.sslip.io`, detrás de Caddy, con autenticación obligatoria.
El origen es `127.0.0.1:5050`; PostgreSQL 17.11 no publica puertos. La versión exacta
y los hashes de dependencias están en `deploy/mlflow/requirements.lock`.

El tracking conserva experimentos y artefactos; el benchmark en Git define las
comparaciones válidas. La promoción a FPL sigue perteneciendo al harness.
No hay alias MLflow que cambie un modelo activo ni endpoint de serving automático.

## Qué se registra

- 98 registros de la consolidación inicial: política, predicción e inventario;
  19 experimentos MLflow separados por protocolo y población.
- 17 versiones descriptivas de políticas enlazadas a su evidencia. Estos
  descriptores JSON **no son modelos ejecutables** ni equivalen a 17 modelos entrenados.
- Archivo de los modelos `minutes` y `points` disponibles y del manifest
  `season_value` sellado. Sus binarios se verifican por hash sin deserializar pickle.
  Se conservan versión semántica, SHA y fecha originales cuando están registrados.
  Los modelos 1.0.0 no tenían hash histórico: se calcula al archivarlos y se marca
  `digest_provenance=computed_at_archive`, sin fabricar una verificación histórica.

El contador de versiones de MLflow no reemplaza la versión semántica del modelo.
Un archivo antiguo cargado hoy queda etiquetado `historical_import` o
`verified_artifact_archive`; las fechas MLflow corresponden a la importación.
Los metadatos faltantes permanecen `not_recorded`. Un directorio incompleto no
se presenta como entrenamiento exitoso: `FINISHED` sólo acredita la importación.

Para evaluar progreso, elegir el experimento/protocolo, filtrar `aggregation=summary`
y comparar `mean_pva_38`, `ci95_low/high`, victorias y número de temporadas.
`aggregation=season` muestra los puntos netos y deltas de cada temporada.
Los paneles de CRPS/Brier/log-loss están separados; un menor error no acredita
por sí solo más puntos. No ordenar todas las generaciones como un leaderboard global.

## Acceso y permisos

- `julian`: administrador del tracking.
- `mova-writer`: escritor de experimentos y registro de artefactos.
- `mova-reader`: lectura de los experimentos/modelos existentes; no puede editar sus runs.

MLflow permite a usuarios autenticados crear recursos propios según su contrato;
el rol lector protege los experimentos existentes, no es una cuenta pública anónima.
Se usa `NO_PERMISSIONS` por defecto y roles explícitos. En MLflow 3.16,
el modo fail-closed devuelve 403 en la raíz UI a no administradores; el lector
usa la API y Julián accede a la UI como administrador. No se desactiva ese
control global para habilitar una ruta de presentación. El cache de autenticación
dura cinco segundos: una revocación puede tardar hasta ese tiempo en todos los procesos.

Credenciales del servidor: `/etc/mova-mlflow/` (root, grupo del contenedor, 0640).
Credenciales cliente del operador WSL: `~/.config/mova-mlflow/access.json` (0600).
No imprimirlas ni ponerlas en argumentos, Git o publicaciones. La copia cliente
no contiene contraseña de PostgreSQL ni secreto CSRF. Rotar con la API de auth;
no cambiar sólo el archivo inicial después de crear las cuentas.

## Registrar la siguiente versión del benchmark

Primero ejecutar el protocolo del [benchmark](../../experiments/benchmark/README.md).
El registro MLflow es opcional para el motor y se habilita explícitamente en el
entorno de investigación con `pip install -e '.[mlops]'`.

```bash
python -m experiments.benchmark.run \
  --root ../mova-fpl-experiments --output experiments/benchmark/snapshots/v2 \
  --tracking-uri https://mlflow.72-60-245-2.sslip.io \
  --tracking-credentials "$HOME/.config/mova-mlflow/access.json" \
  --tracking-lock /tmp/mova-benchmark-tracking.lock \
  --actor julian --reason "Registrar nuevo benchmark verificado"
```

Si MLflow falla, el snapshot local ya generado se conserva y el comando falla
explícitamente; se reintenta con `--check` y los mismos argumentos. No se vuelve
a ejecutar la temporada para reparar un fallo de tracking. La identidad incluye
protocolo, métricas y evidencia; una modificación produce otra identidad.

El importador oficial se serializa con `flock`. Usar **un solo escritor/importador**
a la vez; locks en máquinas distintas no coordinan entre sí. El VPS es la vía
canónica de importación compartida. No ejecutar simultáneamente importadores
independientes sobre los mismos IDs. Los tags MLflow no son una restricción UNIQUE.

Desde el VPS:

```bash
sudo mova-mlflow ps
sudo mova-mlflow exec -T tracking python -m experiments.benchmark.tracking sync \
  --snapshot /app/experiments/benchmark/snapshots/v1/catalog.json \
  --tracking-uri http://127.0.0.1:5000 \
  --credentials /run/secrets/mlflow/credentials.json \
  --actor codex --reason "Sincronizar evidencia sellada" \
  --output /imports/benchmark-v1-receipt.json
sudo mova-mlflow exec -T tracking python -m experiments.benchmark.tracking verify \
  --snapshot /app/experiments/benchmark/snapshots/v1/catalog.json \
  --tracking-uri http://127.0.0.1:5000 \
  --credentials /run/secrets/mlflow/credentials.json
```

`verify` contrasta métricas, tags y el contenido de todos los artefactos con el
snapshot. El importador reanuda una importación interrumpida; rechaza duplicados
ambiguos o métricas alteradas de un run finalizado. Las versiones descriptivas se
buscan por identidad antes de crearlas. Reimportar no añade temporadas independientes.

## Infraestructura y mantenimiento

| Recurso | Ubicación |
| --- | --- |
| Fuente desplegada | `/opt/orbital/services/mova-mlflow` |
| Configuración privada | `/etc/mova-mlflow` |
| PostgreSQL | `/var/lib/mova-mlflow/postgres` |
| Artefactos | `/var/lib/mova-mlflow/artifacts` |
| Receipts, lock e importación | `/var/lib/mova-mlflow/imports` |
| Backup local | `/opt/orbital/backups/mova-mlflow/<UTC>` |
| Fragmento Caddy | `/etc/caddy/mova-mlflow.caddy` |

Compose fija límites de recursos y usa un worker. La ejecución de jobs internos
MLflow está deshabilitada: este servicio almacena tracking; no ejecuta entrenamiento
ni tareas de evaluación LLM en el VPS. Los experimentos siguen usando su runner.

El timer `mova-mlflow-backup.timer` hace respaldo diario. El script toma el lock,
pausa sólo tracking, exporta las bases `mlflow` y `mlflow_auth`, copia artefactos y
configuración y restaura el servicio mediante trap. Los backups contienen secretos
y permanecen root-only; no son paquetes de publicación. No hay backup off-host
configurado y esta copia no protege frente a pérdida del VPS completo.

```bash
sudo /opt/orbital/services/mova-mlflow/deploy/mlflow/backup.sh codex "Backup verificado"
sudo /opt/orbital/services/mova-mlflow/deploy/mlflow/restore-drill.sh /opt/orbital/backups/mova-mlflow/FECHA
```

El restore drill usa un PostgreSQL efímero, sin red, compara el número de runs y
verifica los hashes de la evidencia extraída; elimina sólo sus recursos temporales.
No restaura encima de producción. Para rollback del código, seleccionar el tag previo
en `/etc/mova-mlflow/deploy.env` y recrear tracking. Antes de actualizar MLflow,
respaldar ambas bases: una migración de schema puede impedir rollback sólo de imagen.
Nunca borrar volúmenes con `down -v` para arreglar un despliegue.

## Preparar una publicación

```bash
python -m experiments.benchmark.tracking export \
  --snapshot experiments/benchmark/snapshots/v1/catalog.json \
  --output /ruta/nueva/publication-candidate.json
```

El exportador incluye únicamente el contrato de benchmark, resultados y referencias;
no recorre carpetas raw, entornos, snapshots privados ni binarios de la cuenta.
Declara `publication_approved=false`. Es un candidato privado: falta revisión,
licencias de datos y empaquetado reproducible antes de publicar una web/release/DOI.
El servidor MLflow no se convierte en una web anónima para esa publicación.

Fuentes: [Tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/),
[autenticación](https://mlflow.org/docs/latest/self-hosting/security/basic-http-auth/).
