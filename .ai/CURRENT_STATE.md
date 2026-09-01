# ESTADO ACTUAL — ZANTIA

> Snapshot. Se sobrescribe, no se acumula — la historia completa vive en `docs/changelog/`. Este archivo responde: "si entro ahora mismo, ¿qué necesito saber para no romper nada ni repetir trabajo?"

**Última actualización**: 2026-09-01 (integración real con hrmm-backend, sin probar contra red real)

## Qué está desplegado

| Componente | Versión/commit | Entorno | Estado |
|---|---|---|---|
| — | — | — | Nada desplegado todavía. El Core + dominio salud (incluido el adaptador real a hrmm-backend) existen como código local con 91 tests pasando + 1 deshabilitado a propósito, sin canal ni servidor expuesto. |

## Trabajo en curso sin commitear

Ver `git status` al momento de leer esto. Ver `/Users/enzoalfonso/recado/` (recados de esta sesión, numerados) para el detalle completo de cada fase.

## Conocido roto / pendiente de verificación

- Canal exacto de mensajería (WhatsApp/Telegram/etc.) sin decidir — `channels/contract.py` define la interfaz; `MockChannel` demuestra el contrato, sin implementación real.
- Jurisdicción/marco legal exacto para la regla de habeas data sin confirmar (ver `.claude/rules/proteccion-datos-personales.md`).
- `domains/{emergency,sales,citizen}/` son solo contratos — `domains/health/` ya es real, con adaptador real a hrmm-backend construido (ver `docs/health-demand-agent.md`).
- `core/brain.py:AnthropicBrain` es código real pero no probado en vivo (sin `ANTHROPIC_API_KEY` en esta sesión) — los tests usan `FakeBrain`/`HealthBrain` (ambos deterministas).
- Protocolo clínico de riesgo/urgencia real: sigue PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL (heredado de 003/004) — `domains/health/` reutiliza el mecanismo genérico no-clínico del Core, no un criterio médico real.
- Mecanismo de acceso/eliminación de datos personales por parte del usuario final (exigido por `.claude/rules/proteccion-datos-personales.md`): no implementado, `memory/user_memory.py` es deliberadamente parcial.
- **`HrmmAppointmentService` (adaptador real a hrmm-backend) está construido y probado contra una capa HTTP FALSA (`FakeHttpClient`), pero NUNCA se ejecutó contra la red real ni con un secreto real** — decisión explícita del usuario para esta fase ("todavía no ejecutar pruebas de red real"). No existe entorno de staging documentado para hrmm-backend (confirmado por investigación de código) — antes de cualquier prueba real, falta decidir si se prueba contra producción con datos claramente marcados, con el mismo rigor de backup/verificación de sesiones previas de HRMM (no auditables desde esta sesión).
- No hay scheduler real que dispare recordatorios a su hora — `fire_reminder` se invoca explícitamente en este MVP.
- No hay un mecanismo real que conecte `HrmmAppointmentService` al resto del sistema (falta una capa de configuración que lea `HRMM_BACKEND_ENV`/`URL`/`SECRET` y decida instanciar Mock vs. Hrmm real) — no construida en esta fase.

## Progreso reciente

Resumen breve de las últimas sesiones relevantes. El detalle completo, sesión por sesión, vive en `docs/changelog/` (rotado por período — ver `.claude/rules/documentacion-y-memoria.md`).

- 2026-08-31: Proyecto creado desde `PROJECT-TEMPLATE` (commit `6fd36c7`) vía `/new-project`. Tipo: agente conversacional. Topología: monorepo único. Regla de dominio adicional: habeas data. Aislamiento verificado sin resultados.
- 2026-08-31 a 2026-09-01: Serie de auditorías de solo lectura (recados 001-005) sobre Dani (agente de ventas de referencia) y diseño conceptual de arquitectura para ICACO/ZANTIA — sin tocar código.
- 2026-09-01 (fase 1): Construcción del Core ZANTIA MVP. `git init` + primer commit. Stack: Python 3.9 + pydantic + pytest + `sqlite3`. `ConversationState`, máquina de estados, `StateStore` con concurrencia optimista, `Orchestrator`, `GuardrailEngine` (3 reglas), `ToolRegistry` + 3 tools demo, `EventLog`, agente de demostración. 34 tests. Ver recado `006-construccion-zantia.md`.
- 2026-09-01 (fase 2): Primer agente de dominio real sobre el Core existente — `domains/health/` (demanda inducida y gestión de citas para una IPS). Activity con 3 capas de estado separadas (D-3), AppointmentService/ActivitySource/ActivityResultSink (Mock), ReminderManager determinista (72h/24h/8h), HealthBrain. 2 defectos reales del Core corregidos y documentados. 29 tests nuevos (63/63). Ver recado `007-agente-demanda-inducida-zantia.md`.
- 2026-09-01 (fase 3): Evolución bidireccional — `domains/health/gateway.py` (correlación inbound/outbound, `PatientRequest`, clasificación de intención, cierre determinista de Activities sintéticas). 8 tests nuevos (71/71). Ver recado `008-acceso-bidireccional-zantia-health.md`.
- 2026-09-01 (fase 4): `HrmmAppointmentService` — adaptador real contra la API de agenda de hrmm-backend (verificada leyendo su código fuente real, solo lectura). Identidad por documento, espejo de catálogo (servicios/médicos), idempotencia de reserva reforzada, y sub-flujo de verificación por código de 6 dígitos (obligatorio de hrmm-backend para cancelar/reprogramar, descubierto durante esta fase — no estaba en el pedido original) construido enteramente en `gateway.py`, sin tocar `HealthBrain`. 20 tests nuevos (91 pasando + 1 deshabilitado a propósito). Sin pruebas de red real (decisión explícita del usuario). Ver recado de esta fase.
