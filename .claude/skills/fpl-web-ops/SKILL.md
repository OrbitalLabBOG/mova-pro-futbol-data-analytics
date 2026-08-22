---
name: fpl-web-ops
description: "Operar rápidamente la cuenta real de Fantasy Premier League con agent-browser: crear o reemplazar la plantilla, ordenar titulares y banca, asignar capitán y vice, guardar y producir evidencia verificable. Usar solo para ejecutar en la web una decisión FPL ya aprobada o para leer estado privado no expuesto por la API pública."
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-22
---

# FPL Web Ops

Opera `fantasy.premierleague.com` mediante el browser aislado de MOVA en el VPS. El modo
Windows/CDP queda únicamente como fallback manual. Esta skill no decide jugadores: puede
leer estado privado y, cuando exista autorización, ejecutar una spec o acta aprobada sin
improvisar y demostrar que quedó persistida.

Cuenta conocida: `losmillosFPL`, `entry_id=3609854`.

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
5. Obtén la fuente de verdad: spec/acta con 15 jugadores, XI, banca, capitán, vice y chip.

Autenticar o leer el equipo no autoriza mutaciones. Montar o transferir jugadores modifica
una cuenta externa: requiere petición explícita, acta aprobada y gates efectivos. No actives
chips, confirmes transferencias con coste ni cambies la decisión deportiva por inferencia.

## Entorno y gates

El modo principal es `vps`; usa el Compose bajo `/opt/orbital/services/mova-fpl`, sesión
`mova-fpl` y perfil persistente `/var/lib/mova-fpl/browser-profile`. Ese perfil no entra en
Git, `ops.db` ni backups generales. noVNC sólo escucha en loopback y se abre mediante túnel
SSH temporal. El contenedor browser no monta la base operativa.

Antes de cualquier click que pueda mutar FPL, lee `/api/v1/status` desde el host y detente
salvo que todos los controles permitan exactamente la acción:

- `kill_switch=false`;
- `browser_writes=true`;
- `compliance_gate=passed`;
- `action_level` suficiente para la operación;
- decisión aprobada, vigente para la GW y aún no ejecutada.

Con `shadow`, `A0`, compliance pendiente o kill switch activo sólo se permite login, lectura,
snapshot y verificación. No uses `docker exec` directo para eludir un gate.

## Invariantes

- `mova_fpl` es solo lectura. Toda mutación se hace visualmente en el navegador real.
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
  agent-browser --session mova-fpl batch --bail \
  'open https://fantasy.premierleague.com/en/my-team' \
  'wait --load domcontentloaded' 'get url' 'get title' 'snapshot -i'
```

La salida debe corresponder a FPL. Si aparece login, usa el flujo humano de `vps.md` y no
escribas credenciales. Desde ese momento, cada unidad de trabajo empieza con URL y snapshot
frescos dentro de la misma sesión:

```bash
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl batch --bail \
  'get url' 'snapshot -i'
```

Usa un tab FPL estable si hay más de uno. Después de cambiar de tab toma snapshot nuevo: las
refs pertenecen al tab activo y caducan con cualquier render.

### 2. Ejecutar por bloques verificables

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
  agent-browser --session mova-fpl wait --text "Equipo guardado"
docker compose --profile browser exec -T browser \
  agent-browser --session mova-fpl batch --bail \
  'reload' 'wait --load domcontentloaded' 'snapshot -i' \
  'screenshot --full /tmp/gwNN_final_mounted.png'
```

Copia únicamente la captura aprobada fuera del contenedor y calcula SHA-256. No vuelques el
DOM autenticado, cookies, storage o perfil como evidencia. Al terminar, ejecuta
`deploy/bin/browser-session.sh stop`.

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

## Criterio de parada

Detente y reporta antes de confirmar si:

- el modal no coincide exactamente con la spec;
- aparece un coste en puntos no aprobado;
- FPL cambió precio, disponibilidad o fixture de forma material;
- se requiere contraseña/MFA;
- falta un jugador o la plantilla viola presupuesto/club/posición;
- no puedes demostrar persistencia tras recargar.
