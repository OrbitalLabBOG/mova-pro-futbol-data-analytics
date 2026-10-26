---
type: adr
name: ADR-019 — Protección manual por ciclo y aceptación de campaña research
created: 2026-10-23
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Alcance

Julián recibió el plan del 23/10 y ordenó «procede ajusta». Esta entrega implementa
continuidad semanal y research. Conserva A2/autonomous/progressive-lineup-v1,
mismos quince, cero transferencias/hits/chips automáticos y cuotas reales.
Instalar código no activa A3, R3 ni registra una nueva cohorte.

# Problemas comprobados

La protección manual GW8 usó delivery_scope=null y dependió del chat para
restaurarlo. El watchdog sólo reconocía el recibo nativo y podía producir un P0
falso. Research acumula continuaciones, pero ADR-011 evalúa la primera corrida:
un inicio parcial impedía acreditar una campaña posteriormente completa.

# Decisión

El recibo manual v2 importado es un hold de su ciclo. Dispatcher, preflight,
claim y begin bloquean otra escritura; tick conserva la decisión. La siguiente
GW no hereda el hold y continúa con la autorización permanente y gates normales.
El operador no apaga el scope para proteger un manual; usa guarded durante la
operación autorizada y después restaura su A2/autonomous previo.

Watchdog reconoce evidencia íntegra, cuatro checks, quince posiciones y audit
sellado. Status expone manual_receipt por separado: no fabrica un Save nativo.
Evidencia dañada mantiene el hold sin acreditar entrega. Un manual no oculta
Save ambiguo; no puede importarse con claim/apply/ambigüedad nativos activos.
Claim y begin comprueban el hold dentro de su transacción. Un scope=null explícito
sigue siendo revocación y nunca se restaura automáticamente.

Se añade mova-research-acceptance-manifest-v2 opt-in. v1 conserva la selección
inmutable de primera corrida. La cohorte fallida GW7/8/9 y sus cargos no cambian.
v2 exige aprobación trazable, tres GWs futuras no inferidas ni inscritas,
contrato/ventanas/hashes preregistrados y contabilidad exacta.

v2 evalúa todas las corridas operacionales. Una entrega parcial válida queda
pendiente antes del deadline; fallo físico, rechazo, deriva o consumo incierto
bloquea aunque haya un éxito posterior. Al cutoff exige procesados >=90%,
evidencia verificada >=80%, cero conflictos pendientes a tiempo, cuotas reales
y broad/refresh/final importados en sus ventanas. Procesado por límite de fuentes
no equivale a evidencia válida. Se reconstruye con manifest/imports previos al
cutoff y TTL de ese instante; imports o resoluciones posteriores no reparan el
pasado. No se elige la mejor corrida ni hay promoción automática.

Las continuaciones conservan sólo pistas de pendientes y metadata de fuentes,
sin reenviar cuerpos ya procesados. Originales y cargos permanecen sellados;
citar una URL requiere nueva lectura/verificación. No se rebaja la admisión de
un job completo ni se crea otra request para eludir completion_budget_exhausted.

# Aceptación

Pruebas de hold/rollover sin cambiar controles, evidencia alterada, carreras,
campaña parcial, refresh obligatorio, fallo seguido de éxito, consumo incierto,
hash/contrato inválidos e import tardío. Suite completa e imagen antes del rollout;
doctor y rollback verificables. Preparar una cohorte no la registra ni completa.
No se inventan cierres GW6/7 ni un Save físico de una revisión nueva.
