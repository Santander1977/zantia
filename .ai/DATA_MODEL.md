# MODELO DE DATOS — ZANTIA

> Dominios de datos y, para cada uno, quién es la fuente de verdad (ver `.claude/rules/fuente-de-verdad.md`). No se documenta el detalle exhaustivo de cada columna aquí si el proyecto ya tiene migraciones versionadas — se documenta la relación y la decisión de diseño, remitiendo a las migraciones para el detalle exacto.

## Dominios

| Dominio | Fuente de verdad (tabla/schema/servicio) | Notas |
|---|---|---|
| Citas médicas (agenda) | **hrmm-backend** (proyecto externo — `Cita` en su propia base de datos) cuando `HrmmAppointmentService` está activo; `MockAppointmentService` (memoria de proceso) en el MVP de demostración | ZANTIA nunca es el sistema maestro de la cita — `domains/health/models.py:Appointment` es solo una referencia/copia de lectura. Confirmado leyendo `.claude/rules/fuente-de-verdad.md`: se documenta aquí explícitamente para no duplicar silenciosamente el dominio "citas" |
| Catálogo de servicios/médicos | **hrmm-backend** (`GET /api/agenda/servicios`, `/medicos`) | `domains/health/hrmm_catalog.py:CatalogMirror` es un espejo de solo lectura, sincronizado bajo demanda — nunca la fuente de verdad, nunca inventado por el Brain |
| Identidad del paciente (documento) | **hrmm-backend** (vía `buscar-paciente`) cuando hay historial previo; si no, la conversación misma (paciente nuevo) | Convención documentada en `hrmm_appointment_service.py`: `patient_reference` (interno de ZANTIA) = `documento_paciente` real cuando `HrmmAppointmentService` está activo |
| `ConversationState`, `Activity`, `PatientRequest` | ZANTIA (SQLite / memoria de proceso, ver `.ai/ARCHITECTURE.md`) | Estado operativo del agente — no compite con hrmm-backend, son dominios distintos (estado de la conversación vs. estado real de la cita) |
| Identidad del CANAL (teléfono→documento, VERIFICADO por código) | ZANTIA — tabla `identidad_canal` (SQLite propio, `domains/health/identity_store.py`, recado 014) | Distinto del "titular"/"gestor"/"beneficiario" de más abajo: esos son conceptos de UNA conversación; `identidad_canal` es la asociación teléfono↔documento en sí, válida para TODAS las conversaciones futuras de ese teléfono. Fuente de verdad de "¿ya verificamos que este número es dueño de este documento?" — nunca hrmm-backend (que no tiene noción de "número de WhatsApp") ni `ConversationState` (que muere con la conversación) |

## Relaciones clave entre dominios

[Completar.]

## Advertencia de nombres ambiguos

**"Titular del canal" vs. "gestor" vs. "beneficiario"** (recado 013, extensión de R-15) — tres conceptos de identidad DISTINTOS que coexisten en `domains/health/`, ninguno es la fuente de verdad del otro:

- **Titular del canal**: quién tiene el número/canal por el que se escribe — resuelto por `domains/health/gateway.py:_gestionar_identificacion` (R-15) contra `buscar-paciente`, vive en `HealthGateway._identidad_resuelta` (en memoria de proceso, por conversación).
- **Gestor**: el titular del canal, en el momento específico de una gestión — es quien aparece como `Activity.patient_reference` para una Activity sintética iniciada por el paciente. Sigue siendo SIEMPRE el titular, incluso cuando la gestión es para un beneficiario.
- **Beneficiario**: la persona para quien es la cita, cuando es DISTINTA del titular ("es para mi mamá") — vive en `ConversationState.datos_recopilados["beneficiario_documento"]`/`["beneficiario_nombre"]` (por conversación, `domains/health/brain.py`), validado contra `buscar-paciente` antes de aceptarse, y confirmado explícitamente por el titular antes de usarse.

`AppointmentService` (reserva/disponibilidad) SIEMPRE recibe el documento del BENEFICIARIO cuando existe, nunca el del gestor — pero el EventLog (`observability/events.py`, vía `agent.py`) registra AMBOS, en campos separados (`gestor_documento`, `beneficiario_documento`), nunca fusionados, precisamente para que esta distinción no se pierda en la auditoría. Ver `.ai/RISKS.md` R-15.

## Política de retención por tipo de dato (`.claude/rules/proteccion-datos-personales.md`)

| Dato | Retención | Estado |
|---|---|---|
| `identidad_canal` (teléfono↔documento verificado, recado 014) | **Vencimiento automático a 180 días** de `verificado_en` (`domains/health/identity_store.py:RETENCION_IDENTIDAD_DIAS`) — vencida, se trata como si no existiera (sin mensaje especial), el wizard de verificación se repite igual que con un teléfono nuevo. **Eliminación a pedido del paciente en cualquier momento**: frases como "olvida mi información" (`domains/health/brain.py:_OLVIDAR`), detectadas en cualquier etapa de una conversación abierta, con confirmación explícita obligatoria antes de un borrado REAL de la fila (`gateway.py:_procesar_olvido_si_corresponde`) — decisiones de producto del usuario, recado 016 (2026-09-03) | **MITIGADO** — ver `.ai/RISKS.md` R-20 |
| `ConversationState`/`Activity`/`PatientRequest` | Sin política definida — mismo estado que el resto del proyecto (R-3, R-11) | PENDIENTE |
| Datos reenviados a hrmm-backend (documento, nombre, teléfono) | Gobernados por la política de retención de **hrmm-backend**, no de ZANTIA — ZANTIA no guarda una copia de sistema-maestro (ver dominio "Citas médicas" arriba) | Fuera del alcance de este proyecto |
