# D-4 — HrmmAppointmentService: adaptador real, identidad por documento, verificación por código obligatoria

**Decisión**: `domains/health/hrmm_appointment_service.py:HrmmAppointmentService` implementa el Protocol `AppointmentService` (sin modificarlo salvo la extensión ya aditiva de 008) contra la API real de hrmm-backend, con tres reglas de diseño no negociables:

1. `patient_reference` (concepto interno de ZANTIA) es literalmente el documento de identidad real del paciente cuando este adaptador está activo.
2. `cancel_appointment`/`reschedule_appointment` (la firma estándar del Protocol) SIEMPRE lanzan `VerificationRequiredError` — nunca ejecutan la acción real sin pasar primero por el sub-flujo de verificación por código de 6 dígitos que exige hrmm-backend.
3. `HealthBrain` no se modifica: el sub-flujo de verificación vive enteramente en `domains/health/gateway.py`, como un wizard determinista independiente de la máquina conversacional del Core.

**Motivo**: verificando el código real de hrmm-backend (solo lectura, sin modificarlo) se confirmó que `reprogramar`/`cancelar` exigen, además del header de canal de confianza (`X-Backend-Secret`), un `codigo` de verificación de 6 dígitos enviado al correo del paciente (`POST /api/agenda/verificacion/enviar`, TTL 10 min, 5 intentos, un solo uso) — un requisito que el pedido original no contemplaba y que ninguna de las tools/HealthBrain ya construidas (007/008) sabían manejar.

**Alternativas consideradas**:
- **Ampliar la firma del Protocol `AppointmentService`** (agregar `documento`/`codigo` a `cancel_appointment`/`reschedule_appointment`) — descartada explícitamente: rompería el contrato ya usado por `MockAppointmentService` y las tools existentes (`tools.py`, protegidas), violando "sin tocar ninguna otra pieza ya construida".
- **Meter la lógica de verificación dentro de `HealthBrain`** — descartada explícitamente por el usuario y por este documento: `HealthBrain` está protegido; además, la verificación por código es un requisito de INTEGRACIÓN (impuesto por hrmm-backend), no de conversación de dominio — no debería vivir en el Brain aunque no estuviera protegido.
- **Confirm_appointment como paso HTTP real separado** — descartada: hrmm-backend confirma la cita de forma atómica en el propio `POST /api/agenda/citas`; `confirm_appointment` se implementó como una relectura (`get_appointment`), preservando el contrato de dos pasos que ya exige `BookAppointmentTool` (sin tocar) sin inventar una llamada HTTP que no existe.

**Ventajas**: cero cambios a componentes protegidos; el sub-flujo de verificación es explícito, testeable de forma aislada, y reutilizable si otro dominio futuro necesita el mismo patrón de segundo factor.

**Desventajas**: el wizard de verificación vive fuera de `ConversationState`/`Orchestrator` — no se beneficia de la máquina de estados del Core (transiciones validadas, guardrails genéricos). Mitigado: es un flujo corto (2-3 turnos), determinista, con su propio manejo de reintento de código, y auditado vía `ActivityResultSink` igual que el resto del dominio.

**Riesgo**: medio mientras no se pruebe contra red real — toda la lógica está verificada contra el contrato REAL confirmado por lectura de código, pero ningún test de esta fase ejecutó una llamada HTTP real (petición explícita del usuario). Bajo una vez se validen las pruebas de integración reales (pendiente, ver recado de esta fase).

**Impacto**: cualquier futuro dominio que integre con un sistema externo que exija un segundo factor de identidad puede replicar este mismo patrón (marcador `requires_verification_code` + sub-flujo en el gateway del dominio).

**Estado**: IMPLEMENTADA (2026-09-01) — con pruebas de red real explícitamente diferidas (ver `.ai/CURRENT_STATE.md`).
