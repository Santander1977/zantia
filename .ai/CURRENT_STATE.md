# ESTADO ACTUAL — ZANTIA

> Snapshot. Se sobrescribe, no se acumula — la historia completa vive en `docs/changelog/`. Este archivo responde: "si entro ahora mismo, ¿qué necesito saber para no romper nada ni repetir trabajo?"

**Última actualización**: 2026-09-01 (primer agente de dominio real: demanda inducida en salud)

## Qué está desplegado

| Componente | Versión/commit | Entorno | Estado |
|---|---|---|---|
| — | — | — | Nada desplegado todavía. El Core + dominio salud existen como código local con tests pasando (63/63), sin canal ni servidor expuesto. |

## Trabajo en curso sin commitear

Ver `git status` al momento de leer esto — esta sesión agregó `domains/health/` (Activity, AppointmentService, ReminderManager, ActivityResult, HealthBrain), `channels/mock_channel.py`, `docs/health-demand-agent.md`, `docs/decisions/d-3-*.md`, y corrigió 2 defectos reales del Core (`core/orchestrator.py`, `state/machine.py`). Ver `/Users/enzoalfonso/recado/007-agente-demanda-inducida-zantia.md` para el detalle completo.

## Conocido roto / pendiente de verificación

- Canal exacto de mensajería (WhatsApp/Telegram/etc.) sin decidir — `channels/contract.py` define la interfaz; `MockChannel` demuestra el contrato, sin implementación real.
- Jurisdicción/marco legal exacto para la regla de habeas data sin confirmar (ver `.claude/rules/proteccion-datos-personales.md`).
- `domains/{emergency,sales,citizen}/` son solo contratos — `domains/health/` ya es real (ver `docs/health-demand-agent.md`).
- `core/brain.py:AnthropicBrain` es código real pero no probado en vivo (sin `ANTHROPIC_API_KEY` en esta sesión) — los tests usan `FakeBrain`/`HealthBrain` (ambos deterministas).
- Protocolo clínico de riesgo/urgencia real: sigue PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL (heredado de 003/004) — `domains/health/` reutiliza el mecanismo genérico no-clínico del Core, no un criterio médico real.
- Mecanismo de acceso/eliminación de datos personales por parte del usuario final (exigido por `.claude/rules/proteccion-datos-personales.md`): no implementado, `memory/user_memory.py` es deliberadamente parcial.
- `ActivitySource`/`AppointmentService`/`ActivityResultSink` reales (hoy Mock) — contratos ya listos para sustituir sin tocar el Brain (ver `docs/health-demand-agent.md`, sección Integraciones).
- No hay scheduler real que dispare recordatorios a su hora — `fire_reminder` se invoca explícitamente en este MVP.

## Progreso reciente

Resumen breve de las últimas sesiones relevantes. El detalle completo, sesión por sesión, vive en `docs/changelog/` (rotado por período — ver `.claude/rules/documentacion-y-memoria.md`).

- 2026-08-31: Proyecto creado desde `PROJECT-TEMPLATE` (commit `6fd36c7`) vía `/new-project`. Tipo: agente conversacional. Topología: monorepo único. Regla de dominio adicional: habeas data. Aislamiento verificado sin resultados.
- 2026-08-31 a 2026-09-01: Serie de auditorías de solo lectura (recados 001-005) sobre Dani (agente de ventas de referencia) y diseño conceptual de arquitectura para ICACO/ZANTIA — sin tocar código.
- 2026-09-01 (fase 1): Construcción del Core ZANTIA MVP. `git init` + primer commit. Stack: Python 3.9 + pydantic + pytest + `sqlite3`. `ConversationState`, máquina de estados, `StateStore` con concurrencia optimista, `Orchestrator`, `GuardrailEngine` (3 reglas), `ToolRegistry` + 3 tools demo, `EventLog`, agente de demostración. 34 tests. Ver recado `006-construccion-zantia.md`.
- 2026-09-01 (fase 2): Primer agente de dominio real sobre el Core existente — `domains/health/` (demanda inducida y gestión de citas para una IPS). Activity con 3 capas de estado separadas (D-3), AppointmentService/ActivitySource/ActivityResultSink (Mock), ReminderManager determinista (72h/24h/8h), HealthBrain. 2 defectos reales del Core corregidos y documentados (`core/orchestrator.py`: no declarar éxito sin confirmación real; `state/machine.py`: transiciones síncronas dentro de un turno). 29 tests nuevos (63/63 en total), incluidos 2 escenarios end-to-end completos. Ver recado `007-agente-demanda-inducida-zantia.md` y `docs/health-demand-agent.md`.
