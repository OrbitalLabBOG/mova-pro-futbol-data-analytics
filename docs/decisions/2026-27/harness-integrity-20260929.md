---
type: adr
name: MOVA harness — financing, wait states and research comparison
created: 2026-09-29
status: released-shadow
owner: Julián Zuluaga
---

# Integridad del ciclo y experimentos comparables

Un closeout reconstruido con precios de mercado podía rechazar un roster valorizado
contra el presupuesto inicial, mientras su atribución por jugador omitía BB/TC. El
workflow confundía stages todavía no elegibles con acciones pendientes y exigía una
lección para completar aprendizaje. El laboratorio no exigía presupuestos iguales ni
metering válido del baseline.

Se introduce `mova-fpl-autonomous-closeout-v2` con financiación versionada de ambos
escenarios, estado previo vinculado al manifest y posterior verificado, banco en décimas
y origen causal de precios. Sólo después de validar este contrato se omite el control
inaplicable de compra inicial dentro del cierre; el motor general conserva ese control.
La procedencia se verifica contra artifacts/ledger y batch aprobado. Free Hit declara
reversión futura pendiente; esta iteración no implementa su executor ni la acredita.
Los cierres legacy se preservan y no cuentan como prueba del contrato v2.

El motor entrega multiplicadores que el cierre reutiliza para atribución. Expectativa y
oracles declaran chips/hits. Probabilidades faltantes generan métrica nula con motivo.
Los estados de espera comparten la ventana con la admisión existente y exponen razones;
fuentes alteradas, stale, fallos y contradicciones conservan su bloqueo. Una revisión
causal sin propuestas o con todas rechazadas puede terminar sin una lección positiva.

El comparador exige condiciones compatibles, consumos exactos dentro del mismo límite
por job y una tentativa completa por brazo. La hipótesis `focus_completion_v1` queda
registrada como Researcher 1.11.0 experimental; la activa conserva 1.10.0 hasta evaluación
online válida. El corpus offline usa extractos previamente verificados, hashes y fechas,
sin publicar nuevos signals ni contar GWs. El ensayo de 2M se difiere por reserva de
capacidad operativa con el presupuesto observado; no se incrementan allowances.

No se modifican autoridades, compliance, writers ni activación del browser. Las pruebas
locales/DOM no sustituyen rehearsals vivos ni el ciclo desatendido. Validación y
limitaciones están en `experiments/research/20260929-harness/README.md`; el roadmap
canónico conserva AC01/02/03/04 y las tareas PM correspondientes.

La implementación se integró en `main` y se desplegó como `7144cdd` con autoridad A0
preservada. La [verificación de release](release-20260929-7144cdd.md) conserva evidencia
y límites; el laboratorio anterior no se reetiqueta como evidencia de operación natural.
