---
type: runbook
name: MOVA FPL — recuperación en host nuevo y objetivos DR
updated: 2026-10-05
status: prepared-not-proven
---

# Recuperación en host nuevo

## Objetivos de esta iteración

| Alcance | Objetivo | Cómo se mide | Evidencia actual |
| --- | --- | --- | --- |
| Datos/modelos: pérdida máxima | RPO 7 h; cadencia 6 h | Edad del inicio de ambos snapshots, máximo de SQLite/PG | Evaluación horaria de metadatos; no sustituye restore |
| Restore externo aislado | RTO 15 min | Desde descarga hasta integridad/modelos/paridad | 380 s el 05/10 en acd84a9; 8/8 PASS |
| Servicios del mismo host | Recuperación de endpoints en 5 min | Parada a endpoint disponible; API requiere medición independiente | API 25 s, PG 19 s, browser 17 s, combinado 57 s el 05/10 en acd84a9 |
| Reconstrucción de host | RTO objetivo 120 min | Inicio en host vacío a aceptación completa | Pendiente; no existe medición válida |

Los objetivos son la política de trabajo seleccionada para esta iteración, no SLA
contractual ni una promesa de recuperación. Seis horas de cadencia dejan margen de
una hora para jitter, ejecución y transferencia. No hay garantía si fallan corridas:
`dr-status.sh` detecta el incumplimiento horario y systemd conserva el fallo.
No acredita checksum remoto ni reemplaza el restore de ocho controles.

La [acta del SHA final](../decisions/2026-27/harness-release-20261004-dcf98b8.md)
conserva jobs, hashes y horarios originales. Estos restores y drills del host vivo
no acreditan reboot ni el RTO desde host vacío.

## Inventario y separación del VPS vivo

`deploy/bin/dr-status.sh` consulta metadatos restic, manifiestos v2, edad del snapshot,
revisión de checkout/imágenes, nueve timers operativos, disco y API. Produce
`/var/lib/mova-dr/status.json` con timestamps y checks; no exporta credenciales,
contenido de bases ni perfil browser. El servicio `mova-fpl-dr-status` corre cada hora.
Su resultado se consulta por systemd/journal y JSON. El motor acd84a9 desplegado
el 5 de octubre incorpora su proyección al status/cockpit/doctor y al contrato del
watchdog: sólo timestamp, revisión, estados
de seis checks y edades locales/externas al host-probe. El engine extrapola esas
edades con el tiempo transcurrido, aplica RPO 7 h y caduca el reporte tras 90 min.
Missing/invalid/stale/future, revisión distinta y checks blocked requieren atención;
el watchdog abre un P1 deduplicado y sólo lo resuelve tras una observación vigente
válida. `doctor.recent_backup` usa el snapshot medido, nunca mtime de directorios
de releases. Ninguno de esos checks afirma reconstrucción de host vacío.

Para aceptar un host distinto:

```bash
sudo python3 deploy/bin/dr-preflight.py --mode recovered-host \
  --expected-revision <sha-del-release-recuperado> \
  --snapshots <inventario-restic-protegido.json> \
  --source-host-fingerprint <sha256-del-machine-id-del-host-origen>
```

El modo recovered-host rechaza la misma identidad o identidad de origen desconocida.
Doctor sin WARN/FAIL y observabilidad disponible son obligatorios. Incluso pasando
los checks técnicos, `host_reconstruction_proven=false`: la aceptación completa
requiere evidencia original de los pasos siguientes. No importarlo como un drill
`reboot_recovery` ni usarlo para elevar autonomía.

## Ensayo reproducible por fases

1. Registrar hora de inicio UTC, SHA completo del runtime, fingerprint del host
   origen, imagen/digest de engine/browser/PostgreSQL, timers y caps efectivos.
   Usar `dr-status.sh` y `docker inspect` con campos allowlisted; nunca exportar
   `.env`, llaves ni perfiles a Git o al catálogo. Registrar sistema operativo,
   Docker/Compose, Python, restic y Git instalados en el destino.
2. Crear **otro host aislado**, sin DNS productivo ni tareas programadas activas.
   Reservar 2 CPU, 8 GiB RAM y espacio para 20 GiB libres después del restore.
   Sus servicios sólo escuchan en loopback. No usar el host vivo como destino.
3. Obtener el SHA aprobado de Git y las imágenes del release. No reconstruir
   silenciosamente dependencias flotantes: comparar digests con el inventario
   fuente o documentar la desviación y repetir aceptación. Instalar carpetas con
   `bootstrap-host.sh`; no ejecutar todavía `install-systemd.sh`, que activa stack
   y timers inmediatamente. Replicar `deploy/compose.capacity.yaml` y los drop-ins
   efectivos de cadencia/capacidad conservando los locks y budgets.
4. Recuperar contraseña restic desde Secret Manager con identidad administrativa;
   emitir una llave nueva acotada al bucket. Provisionar `/etc/mova-fpl/` por el
   canal autorizado. La identidad del VPS perdido no puede leer Secret Manager.
   Runtime/deploy env de ejemplo contienen defaults, no la configuración final:
   contrastar modelos 1.1.0, caps, proveedor/modelos agentic, modo shadow/A0 y gates.
5. Listar snapshots, seleccionar el snapshot MOVA con exactamente los dos conjuntos
   y descargarlo a una ruta protegida. Usar los validadores v2 y los restores
   aislados antes de instalar datos. Verificar hashes de las tres SQLite, ambos
   joblib, dump PG y paridad completa. Registrar inicio del snapshot y tiempos
   de descarga/restauración; no medir RPO desde la hora de upload.
6. **En el destino vacío solamente**, instalar las SQLite/modelos verificados
   manteniendo su estructura y propietarios. Crear PG nuevo y restaurar dump
   con credenciales nuevas/roles separados; conservar inventario y comprobar
   paridad. No montar los datos productivos del origen ni sobrescribir un runtime.
7. Reconciliar rutas del ledger con artefactos de auditoría externos al backup.
   Decisiones, research, permisos, receipts y evidencia pueden referenciar rutas
   que el conjunto DB/modelos no incluye. Recuperar del archivo privado autorizado
   o declarar cada hueco; no fabricar archivos ni marcar una fila como verificada.
8. Arrancar API/PG/modelos, verificar doctor, controles A0 y GET de proveedores.
   Reautenticar browser/Codex bajo supervisión: sus credenciales/perfiles quedan
   excluidos de backups. No reutilizar tombstones/requests archivados como cola
   pendiente: inventariar el ledger y comprobar la integridad de cola antes de
   permitir trabajo. Mantener las escrituras FPL deshabilitadas.
9. Activar timers sólo después de revisar estado/control/cola, observar tick nuevo,
   collectors reales, paridad y backup externo desde destino. Ejecutar preflight
   recovered-host, registrar hora final y duración. Apagar el entorno de ensayo
   o dejarlo aislado; no cambiar DNS/autoridad como efecto del ensayo.

## Criterios de aceptación

Acta y JSON propios del host vacío: source/target distintos, release e imágenes,
tiempos originales, hashes/manifiestos/restic ID, restore completo, artefactos
externos reconciliados, auth supervisada, lecturas de proveedores, cola intacta,
API/timers/tick/modelos, controles A0, RPO/RTO observado y cleanup. La revisión
manual de esta evidencia es obligatoria para declarar recuperación del host.

## Reboot del mismo VPS

La preparación dura diez minutos una vez sellada. Se ejecuta **al final**, cuando
Julián pueda decidir el reinicio; preparar ahora durante una sesión larga dejaría
caducar el sello. `reboot-recovery-prepare.sh` toma backups y valida A0, paridad,
timers y boot ID. Después debe solicitarse autorización separada, exigida por la
skill `mova-fpl-operator`: afecta todos los servicios del VPS. Nunca encadenar
`reboot`, programarlo, ni añadirlo a la preparación. Al volver, verificar doctor,
safety y evidencia original. Un reboot no prueba reconstrucción en host vacío.
