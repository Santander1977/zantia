# AGENTES DE IA — ZANTIA

## agents/demo — agente de demostración del Core

**No es un agente de dominio real** — existe únicamente para validar que el Core (Orchestrator, ConversationState, Memory, Knowledge, Tools, Guardrails, Observability) funciona de extremo a extremo (prompt maestro, sección 27). No debe usarse como base de un dominio real sin rediseñar Brain, Tools y Knowledge para ese dominio.

- **Propósito**: probar el flujo "recibir → interpretar → consultar estado → razonar → validar → ejecutar tool → actualizar estado → registrar eventos → responder" (sección 40).
- **Entradas**: texto libre de un canal genérico (`canal="demo"`), sin canal real conectado.
- **Salidas**: texto de respuesta + `ConversationState` actualizado.
- **Brain**: `FakeBrain` (`core/brain.py`) — determinista, basado en palabras clave, no es NLU real.
- **Herramientas**: `get_demo_info` (READ), `schedule_event` (WRITE, idempotente), `notify_team` (NOTIFY) — todas con datos ficticios (`tools/demo_tools.py`).
- **Fuente de verdad**: `InMemoryKnowledgeSource` con datos ficticios (`knowledge/fixtures.py`).
- **Permisos**: ninguna tool WRITE se ejecuta sin `consentimiento_datos = true` en el estado (verificado por `guardrails/rules.py:ConsentimientoRequeridoParaWriteGuardrail`).
- **Riesgos**: ninguno real — es un demo con datos ficticios, sin conexión a ningún sistema externo.
- **Cuándo delega / pide intervención humana**: ante una señal de riesgo (palabras clave genéricas de ejemplo en `core/brain.py:RISK_KEYWORDS_DEMO`) escala de inmediato a `ESCALADO_URGENTE`, sin excepciones ni preguntas adicionales — ver `core/orchestrator.py`.

## domains/health — Agente de Demanda Inducida y Gestión de Atención (ZANTIA Health Demand Agent)

Primer agente de dominio real. Documentación completa en `docs/health-demand-agent.md`; resumen:

- **Propósito**: gestionar pacientes identificados por una IPS como candidatos a demanda inducida — contactar, informar, facilitar programación, gestionar recordatorios/reprogramaciones, reportar resultado.
- **Entradas**: una `Activity` (creada por el sistema originador vía `ActivitySource`) + mensajes del paciente.
- **Salidas**: texto de respuesta al paciente + `Activity` actualizada + `ActivityResult` reportado al sistema originador.
- **Brain**: `HealthBrain` (`domains/health/brain.py`) — determinista por palabras clave, construido con un proveedor perezoso de la Activity vigente (no una copia congelada).
- **Herramientas**: `get_availability` (READ), `book_appointment`/`reschedule_appointment`/`cancel_appointment` (WRITE, idempotentes), `record_activity_result` (NOTIFY) — todas sobre `AppointmentService`/`ActivityResultSink` (Mock en este MVP).
- **Fuente de verdad**: `MockAppointmentService` — disponibilidad ficticia pero dinámica (se modifica al reservar/cancelar).
- **Permisos**: igual que el demo — ninguna tool WRITE sin `consentimiento_datos = true` (aquí se asume otorgado por el sistema originador al iniciar el contacto, ver `domains/health/agent.py:contact_patient`).
- **Riesgos**: ninguno real — datos y pacientes ficticios; sin conexión a sistemas de salud reales. El protocolo de riesgo/urgencia clínico real sigue **PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL** (usa el mecanismo genérico heredado del Core).
- **Cuándo delega / pide intervención humana**: el paciente solicita hablar con una persona (`ESCALATED`, vía el mismo mecanismo de escalación del Core — nunca promete contacto ni tiempo, lección de Dani); o pide información clínica no autorizada por la Activity (indica la limitación, no inventa, no escala automáticamente).
- **NO hace**: diagnosticar, prescribir, modificar tratamientos, decidir por sí mismo que un paciente necesita una intervención (la necesidad siempre viene de la `Activity`).

## Agentes de dominio pendientes

`domains/{emergency,sales,citizen}/` contienen solo el contrato (`domains/contract.py`) — documentar aquí cada uno cuando exista, con el mismo formato de arriba.
