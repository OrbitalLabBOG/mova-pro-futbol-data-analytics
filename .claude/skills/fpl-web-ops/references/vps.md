# Browser FPL en el VPS

Usa este runbook para la ruta principal de `fpl-web-ops`. El browser tiene su propia imagen,
red y perfil; no comparte el runtime del engine ni monta `ops.db`.

## Identidad del runtime

| Campo | Valor |
| --- | --- |
| VPS | `root@72.60.245.2` |
| Repo | `/opt/orbital/services/mova-fpl` |
| Servicio Compose | `browser` con profile `browser` |
| Sesión agent-browser | `mova-fpl` |
| Perfil persistente | `/var/lib/mova-fpl/browser-profile` |
| noVNC | `127.0.0.1:6080` del VPS |

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
ssh -N -L 6080:127.0.0.1:6080 root@72.60.245.2
```

Abre `http://127.0.0.1:6080/vnc.html`. Julián completa cualquier email, contraseña, OTP,
MFA o consentimiento en la ventana visible. El agente puede esperar y luego verificar, pero
nunca pide, recibe ni escribe esos secretos.

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
  agent-browser --session mova-fpl snapshot -i
```

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
