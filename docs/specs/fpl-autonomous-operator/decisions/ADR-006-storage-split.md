---
type: decision
name: "ADR-006 — Tres SQLite y artefactos locales en el VPS"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, sqlite, vps]
status: proposed
---

# ADR-006 — Tres SQLite y artefactos locales en el VPS

## Decisión

Conservar `fpl_canonical.db` como autoridad de training, `trace.db` como traza experimental,
crear `ops.db` en WAL para coordinación/auditoría y almacenar bytes/modelos/evidencia como
artefactos locales por hash. Todo vive en el VPS. Supabase solo recibe seguimiento PM por
fuera del runtime.

Todas las conexiones productivas usan SQLite ≥3.51.3 dentro de `mova-engine`; el SQLite
3.45.1 del host queda excluido por el bug upstream de WAL-reset.

## Alternativas

- Postgres local: resuelve concurrencia no existente y añade RAM, credenciales y backups;
- Supabase: contradice la frontera operativa y acopla el runtime a un servicio externo;
- un solo SQLite: mezcla entrenamiento, laboratorio y estado mutable;
- tres SQLite + artefactos: seleccionada por aislamiento y simplicidad.

## Consecuencias

El engine es el único escritor de `ops.db`; systemd/`flock` serializa ticks. Se requieren
manifests, backups SQLite consistentes y restore drills. Un segundo host escritor obligaría
a reconsiderar Postgres. Supabase no recibe datos operativos.
