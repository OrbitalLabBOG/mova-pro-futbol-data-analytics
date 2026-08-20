# Recuperación de FPL Web Ops

Lee este archivo solo cuando falle el flujo normal.

## Restablecer Chrome real y CDP

En WSL/Orbital:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File C:\\Temp\\boot-chrome-cdp.ps1

win_host=$(ip route show default | awk '{print $3}')
nohup socat TCP-LISTEN:9222,bind=127.0.0.1,reuseaddr,fork \
  TCP:"$win_host":9222 >/tmp/socat-cdp.log 2>&1 &

curl -sS --max-time 3 http://127.0.0.1:9222/json/version
agent-browser connect 9222
agent-browser tab
```

No uses una comprobación de procesos que pueda coincidir con el propio comando. La prueba
real es que `/json/version` responda y `agent-browser tab` liste las pestañas visibles.

## `tab new` deja una sesión `about:blank`

Reconecta al CDP y navega una pestaña existente:

```bash
agent-browser connect 9222
agent-browser tab
agent-browser open https://fantasy.premierleague.com/es/my-team
```

Después registra el tab FPL estable. No cierres todas las sesiones si eso desvincula el
Chrome real.

## El usuario cambió la pestaña activa

Síntomas: `get url` devuelve otro sitio, snapshot extraño, refs desconocidas o timeout.

Recuperación:

```bash
agent-browser connect 9222 >/dev/null
agent-browser tab
agent-browser tab tN >/dev/null
agent-browser snapshot -i
```

Usa únicamente refs del último snapshot tomado después de `tab tN`. Para acciones dinámicas
sobre jugadores prefiere el selector por texto de `operations.md`.

## Ref desconocida o modal equivocado

No reintentes la ref. Reancla tab, snapshot, inspecciona el heading del modal y obtén refs
nuevas. Si hay modo selección incierto, pulsa **Cancelar** o cierra el modal, verifica la
cancha y reinicia solamente ese swap.

## Login

FPL usa Premier League Account. Se permite hacer clic en **Iniciar sesión con Google** y en
una cuenta ya precargada del perfil. En el selector de Google el primer click puede enfocar
la fila; si la URL no cambia, un segundo click sobre la misma cuenta completa el flujo.

Nunca escribas email/contraseña, OTP ni MFA. Si Google no muestra una cuenta reconocible o
pide un secreto, pausa para que el usuario autentique en la ventana visible. Confirma el
login por identidad/equipo esperado, no solo por el link `Cerrar sesión`.

## Picks públicos en 404

Antes del deadline, `/api/entry/{id}/event/{gw}/picks/` puede responder `Not found` porque
FPL oculta la jornada activa. No es un fallo que se resuelva reintentando. Usa la UI
autenticada, captura posterior a recarga y `live.team`/`live.team_history` para controles
complementarios.
