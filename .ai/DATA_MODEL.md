# MODELO DE DATOS — ZANTIA

> Dominios de datos y, para cada uno, quién es la fuente de verdad (ver `.claude/rules/fuente-de-verdad.md`). No se documenta el detalle exhaustivo de cada columna aquí si el proyecto ya tiene migraciones versionadas — se documenta la relación y la decisión de diseño, remitiendo a las migraciones para el detalle exacto.

## Dominios

| Dominio | Fuente de verdad (tabla/schema/servicio) | Notas |
|---|---|---|
| Citas médicas (agenda) | **hrmm-backend** (proyecto externo — `Cita` en su propia base de datos) cuando `HrmmAppointmentService` está activo; `MockAppointmentService` (memoria de proceso) en el MVP de demostración | ZANTIA nunca es el sistema maestro de la cita — `domains/health/models.py:Appointment` es solo una referencia/copia de lectura. Confirmado leyendo `.claude/rules/fuente-de-verdad.md`: se documenta aquí explícitamente para no duplicar silenciosamente el dominio "citas" |
| Catálogo de servicios/médicos | **hrmm-backend** (`GET /api/agenda/servicios`, `/medicos`) | `domains/health/hrmm_catalog.py:CatalogMirror` es un espejo de solo lectura, sincronizado bajo demanda — nunca la fuente de verdad, nunca inventado por el Brain |
| Identidad del paciente (documento) | **hrmm-backend** (vía `buscar-paciente`) cuando hay historial previo; si no, la conversación misma (paciente nuevo) | Convención documentada en `hrmm_appointment_service.py`: `patient_reference` (interno de ZANTIA) = `documento_paciente` real cuando `HrmmAppointmentService` está activo |
| `ConversationState`, `Activity`, `PatientRequest` | ZANTIA (SQLite / memoria de proceso, ver `.ai/ARCHITECTURE.md`) | Estado operativo del agente — no compite con hrmm-backend, son dominios distintos (estado de la conversación vs. estado real de la cita) |

## Relaciones clave entre dominios

[Completar.]

## Advertencia de nombres ambiguos

[Completar si dos dominios distintos usan un nombre similar (ej. dos tablas de "clientes" con propósitos distintos) — documentarlo aquí explícitamente evita la confusión, en vez de descubrirla por auditoría más adelante.]
