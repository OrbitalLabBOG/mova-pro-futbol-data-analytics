# Browser FPL en el VPS

Usa este runbook para la ruta principal de `fpl-web-ops`. El browser tiene su propia imagen,
red y perfil; no comparte el runtime del engine ni monta `ops.db`.

## Identidad del runtime

| Campo | Valor |
| --- | --- |
| VPS | `ubuntu@72.60.245.2` |
| Repo | `/opt/orbital/services/mova-fpl` |
| Servicio Compose | `browser` con profile `browser` |
| Sesión agent-browser | `mova-fpl` |
| Perfil persistente | `/var/lib/mova-fpl/browser-profile` |
| noVNC | `127.0.0.1:6080` del VPS |
| CDP | `127.0.0.1:9222` sólo dentro del contenedor |

Chromium arranca directamente en `/en/my-team` para evitar cargar y abandonar
la portada durante el arranque. Esto es navegación GET; una ruta correcta no prueba
login ni que la cancha haya terminado de renderizar.

Ejecuta `agent-browser skills get core --full` dentro del contenedor cuando cambie la imagen;
la documentación debe corresponder a la versión instalada, actualmente 0.26.0.

## Inicio y login supervisado

En el VPS:

```bash
cd /opt/orbital/services/mova-fpl
deploy/bin/browser-session.sh login
```

En el PC del operador, mantén abierto este túnel:

```bash
ssh -N -L 6080:127.0.0.1:6080 ubuntu@72.60.245.2
```

Abre `http://127.0.0.1:6080/vnc.html`. Julián completa cualquier email, contraseña, OTP,
MFA o consentimiento en la ventana visible. El Chromium lo inicia supervisord como navegador
normal para que Google OAuth no reciba las señales del launcher automatizado. El agente puede
esperar y luego verificar, pero nunca pide, recibe ni escribe esos secretos.

## Verificación de sesión

Después del login, desde el VPS:

```bash
cd /opt/orbital/services/mova-fpl
deploy/bin/browser-session.sh read
```

La salida debe mostrar FPL autenticado. Navega a `/en/my-team`, toma snapshot fresco y
verifica visualmente `losmillosFPL` y `entry_id=3609854` cuando la UI lo exponga. Confirma
persistencia recargando y repitiendo la lectura. No guardes el snapshot autenticado en logs
permanentes.

Para operaciones agent-browser adicionales usa siempre la imagen:

```bash
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl --cdp 9222 snapshot -i
```

El flag `--cdp 9222` es obligatorio: omitirlo puede lanzar otro Chromium y bloquear el perfil.
La sesión persiste porque cookies, IndexedDB y tokens permanecen en el volumen del perfil. No
exportes `state`, cookies ni storage. Un logout impuesto por Google o FPL requiere repetir el
login humano; no se intenta eludir esa política.

Agrupa navegación y lectura con `batch --bail`; para clicks dinámicos conserva el ciclo
snapshot → interacción → wait específica → snapshot. No reutilices refs después de render,
modal, navegación, reload o cambio de tab.

## Gate de escritura

Antes de abrir `transfers`, activar un chip, cambiar capitán/vice, ordenar banca o guardar:

```bash
curl -fsS http://127.0.0.1:8787/api/v1/status
```

Detente si `kill_switch` es verdadero, `browser_writes` es falso, compliance no está en
`passed`, el action level no permite la operación o no hay decisión aprobada para esa GW.
El estado actual `shadow A0` autoriza únicamente login y lectura.

## Cierre

```bash
cd /opt/orbital/services/mova-fpl
deploy/bin/browser-session.sh stop
```

Comprueba que `127.0.0.1:6080` dejó de escuchar. No borres el perfil al cerrar: ésa es la
persistencia de la sesión. No lo incluyas en backups generales ni lo copies fuera del VPS.

## Modo Windows

Usa Windows/CDP sólo si el browser VPS no puede completar un flujo que requiere interacción
visible y después de leer `recovery.md`. No mezcles cookies o perfiles entre Windows y VPS.

## Probe de cancha por etapas

`deploy/bin/browser-session.sh probe` usa el helper del host
`browser-pick-team-probe.py` y el contrato `fpl-pick-team-a11y-2026.10.1`.
Cada llamada CDP termina en máximo 25 s y el helper tiene un reloj monotónico
total de 90 s. La carga de la SPA se verifica con evaluaciones cortas y
reserva 40 s para la inspección: no se prolonga una sola evaluación hasta
agotar Runtime.evaluate.

Se requieren 15 picks privados, 15 controles visibles y 15 switches en orden
posicional; después se abre y cierra cada una de las 11 fichas titulares.
Captain y Vice Captain deben ser checkboxes nativos con labels accesibles
exactos. La inspección no los activa ni guarda. Una nueva lectura privada al
final debe conservar todos los jugadores, posiciones, capitán y vice.
HTTP 200 prueba acceso privado; por sí solo no prueba DOM ni un rehearsal.
Un timeout o una cancha incompleta termina en fail con un código sanitizado.
Nunca importar ese resultado como PASS ni contabilizar tres pruebas de la
misma GW como tres jornadas distintas.

Conservar el JSON satisfactorio sólo en el inbox protegido y usar el comando
canónico de rehearsal con actor, razón, ciclo e idempotency key. El JSON
contiene identificadores de jugadores para validar el contrato: no publicarlo
en Git ni logs de consola. El error sólo contiene código y diagnóstico acotado.
