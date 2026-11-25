---
name: fpl-web-ops
description: "Operar la cuenta real de Fantasy Premier League con agent-browser: crear o reemplazar la plantilla, ordenar titulares y banca, asignar capitán y vice, guardar y producir evidencia pre/post verificable para `mova execute manual-package`. Usar solo para aplicar en la web un plan que Julián aprobó explícitamente en el chat, o para leer estado privado no expuesto por la API pública."
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-11-25
---

# FPL Web Ops

Opera `fantasy.premierleague.com` mediante el browser aislado de MOVA en el VPS. El modo
Windows/CDP queda únicamente como fallback manual. Esta skill no decide jugadores: puede
leer estado privado y, cuando exista autorización, ejecutar una spec o acta aprobada sin
improvisar y demostrar que quedó persistida.

Cuenta conocida: `losmillosFPL`, `entry_id=3609854`.

## Gate: OK explícito de Julián (ADR-021)

En el modelo copiloto esta skill es la **única tool `write-fpl`**. Solo se ejecuta cuando:

1. el operador presentó un plan concreto para la GW (15, XI, banca en orden, C/VC,
   transferencias, hits, chip) con sus razones;
2. Julián respondió en el chat con un OK explícito sobre **ese** plan exacto, para esa GW y
   antes del deadline;
3. el plan no cambió después del OK (si cambió, se vuelve a pedir).

Un "ok" genérico, el silencio, un OK de otra GW, salud verde, cobertura research o un acta
nueva no autorizan nada. Anota la hora del OK: es `--approved-at` del paquete manual.

`browser_writes`, `action_level` y `delivery_scope` gobiernan el driver automático legacy;
en copiloto quedan fail-closed (`browser_writes=false`, A0) y **no** se cambian para operar
esta skill. La cadena automática (dispatch/driver R2) está retirada y no se usa como atajo.
Si `mova status --json` muestra `operating_model` distinto de `copilot` o un intento de
entrega abierto en `mova execute status`, detente y avisa.

## Carga y autorización

Antes de operar:

1. Carga `agent-browser` y su core desde el entorno que ejecutará el navegador. En el VPS,
   usa la versión fijada dentro de la imagen, no una instalación del host.
2. Lee [references/vps.md](references/vps.md) para arrancar, autenticar, inspeccionar y
   detener la sesión persistente.
3. Lee [references/operations.md](references/operations.md) para crear, transferir o editar
   el equipo.
4. Lee [references/recovery.md](references/recovery.md) únicamente si falla CDP, el login,
   una ref o el usuario cambia de pestaña.
5. Obtén la fuente de verdad: el plan aprobado por Julián (15 jugadores, XI, banca, capitán,
   vice, transferencias y chip), idealmente ya guardado como nota `decision`
   (`mova memory note list --gw N --kind decision --json`).

Autenticar o leer el equipo no autoriza mutaciones. Montar o transferir jugadores modifica
una cuenta externa: requiere el OK explícito de Julián sobre ese plan. No actives chips,
confirmes transferencias con coste ni cambies la decisión deportiva por inferencia.

## Entorno y gates

El modo principal es `vps`; usa el Compose bajo `/opt/orbital/services/mova-fpl`, sesión
`mova-fpl` y perfil persistente `/var/lib/mova-fpl/browser-profile`. Supervisord lanza un
único Chromium visible y normal; `agent-browser` se adjunta después por CDP interno `9222`.
Nunca dejes que agent-browser lance una segunda instancia: Google puede rechazarla y el
perfil puede bloquearse. El perfil no entra en Git, `ops.db` ni backups generales. noVNC
sólo escucha en loopback y se abre mediante túnel SSH temporal. CDP no se publica y el
contenedor browser no monta la base operativa.

Antes de cualquier click que pueda mutar FPL, lee `/api/v1/status` desde el host y detente si:

- `kill_switch=true`;
- `operating_model` no es `copilot` o hay un intento de entrega automática abierto;
- no existe el OK explícito de Julián para este plan y esta GW, o el deadline ya pasó;
- el estado privado actual (pre-state) no coincide con el que se usó para proponer.

Sin OK solo se permite login, lectura, snapshot y verificación. No uses `docker exec` directo
para eludir un gate ni edites controles para "habilitar" el browser.

## Invariantes

- `mova_fpl` no escribe en FPL. Toda mutación se hace visualmente en el navegador real.
- Nunca escribas contraseña, OTP ni código MFA. El selector de una cuenta Google ya
  autenticada sí puede clicarse; si pide secreto, pausa para el usuario.
- Nunca ejecutes `cookies`, `storage`, `state save`, HAR o trazas sobre la sesión autenticada;
  pueden materializar secretos fuera del perfil protegido.
- No uses nombres recordados: compara cada jugador, orden y capitanía con la spec.
- Las refs caducan con cualquier render, modal, navegación o cambio de pestaña.
- Antes de cada interacción por ref: ancla la pestaña FPL y toma un snapshot fresco.
- En la cancha dinámica, identifica jugadores por texto dentro de
  `button[data-pitch-element=true]`; no dependas de una ref antigua.
- Los checkboxes de capitán/vice se operan con `focus` + `Space` y se verifican.
- Un cambio no existe en servidor hasta pulsar **Guardar equipo** o confirmar la plantilla.
- El éxito exige: mensaje de guardado, recarga, segunda comparación y captura completa.

## Ruta rápida VPS

### 1. Anclar la sesión

```bash
cd /opt/orbital/services/mova-fpl
deploy/bin/browser-session.sh start
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl --cdp 9222 batch --bail \
  'open https://fantasy.premierleague.com/en/my-team' \
  'get url' 'get title'
```

La salida debe corresponder a FPL. Si aparece login, usa el flujo humano de `vps.md` y no
escribas credenciales. Desde ese momento, cada unidad de trabajo empieza con URL y snapshot
frescos dentro de la misma sesión:

```bash
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl --cdp 9222 batch --bail \
  'get url' 'snapshot -i'
```

Usa un tab FPL estable si hay más de uno. Después de cambiar de tab toma snapshot nuevo: las
refs pertenecen al tab activo y caducan con cualquier render.

### 2. Ejecutar por bloques verificables

Antes del primer click, captura el **pre-state**: fuerza una lectura privada
(`sudo deploy/bin/collect-private-team-state.sh --force` desde
`/opt/orbital/services/mova-fpl`) y anota el
`artifact_path` del snapshot nuevo (`/api/v1/team-state`, bajo
`MOVA_ARTIFACT_ROOT/team_state/`). Debe coincidir con la plantilla sobre la que se propuso.

Orden recomendado:

1. Plantilla o transferencias: completar los 15 y confirmar el modal solo después de comparar.
2. XI y formación: hacer swaps banca↔campo.
3. Orden de banca: portero, suplente 1, 2 y 3.
4. Capitán y vicecapitán.
5. Chip, únicamente si la spec lo ordena y está autorizado.
6. Snapshot final contra la spec.
7. **Guardar equipo**.

Mantén cada bloque corto: interacción → espera específica → snapshot → comparación. No
encadenes muchos clicks ciegos.

### 3. Cerrar con evidencia

Después de guardar:

```bash
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl --cdp 9222 wait --text "Equipo guardado"
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl --cdp 9222 batch --bail \
  'reload' 'wait --load domcontentloaded' 'snapshot -i' \
  'screenshot --full /tmp/gwNN_final_mounted.png'
```

Copia únicamente la captura aprobada fuera del contenedor y calcula SHA-256. No vuelques el
DOM autenticado, cookies, storage o perfil como evidencia. Con
`MOVA_BROWSER_KEEP_RUNNING=1`, conserva Chromium y su perfil; cerrar el browser
no es el final rutinario del flujo. `stop` se reserva para una parada autorizada
o el modo on-demand expresamente configurado.

La recarga debe mostrar:

- los 15 jugadores correctos;
- XI y formación correctos;
- badges de capitán y vice correctos;
- banca en orden exacto;
- presupuesto y banco esperados;
- ningún botón **Guardar equipo** por cambios pendientes;
- chip correcto o ninguno.

Completa la evidencia con lecturas públicas, cuando estén disponibles:

```python
from mova_fpl.data import live
live.team(3609854)
live.team_history(3609854)
```

El endpoint público de picks puede devolver 404 antes del deadline; la verificación visual
autenticada es entonces la evidencia canónica.

### 4. Entregar evidencia para el registro manual

1. Captura el **post-state** con otra lectura privada forzada (mismo script) y anota su
   `artifact_path`.
2. Escribe un JSON de evidencia bajo `MOVA_ARTIFACT_ROOT/manual/` con el SHA-256 de la
   captura final, hora del Save, URL `/en/my-team` y comparación contra el plan. Sin DOM,
   cookies ni storage.
3. Devuelve al operador las rutas pre/post/evidencia y la hora del OK. El operador corre
   `mova execute manual-package --gw N --approved-by julian --approved-at <OK>
   --operations <lineup,captaincy,...> --pre-state <dir> --post-state <dir> --evidence <json>
   --rationale "..."` y después `mova execute record-manual --package ...`.
4. Si el collector privado falla (`FPL_AUTH_REQUIRED`), dilo: sin pre/post no hay paquete
   manual; la nota `decision` queda como única memoria de la GW.

## Criterio de parada

Detente y reporta antes de confirmar si:

- el modal no coincide exactamente con la spec;
- aparece un coste en puntos no aprobado;
- FPL cambió precio, disponibilidad o fixture de forma material;
- se requiere contraseña/MFA;
- falta un jugador o la plantilla viola presupuesto/club/posición;
- no puedes demostrar persistencia tras recargar;
- el plan en pantalla difiere del que Julián aprobó.
