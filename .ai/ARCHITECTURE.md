# ARQUITECTURA — ZANTIA

> Memoria comprimida, siempre vigente. Se lee completa al empezar una sesión. El detalle largo que no quepa aquí vive en `docs/architecture/`, enlazado desde este archivo — nunca duplicado.

## Identidad rápida

Ver `PROJECT.md` para el contexto completo de negocio. Resumen: plataforma de inteligencia agéntica multi-dominio (identidad conceptual "ZANTIA" desde 2026-09-01; nació como agente conversacional de un solo dominio bajo el nombre "icaco" — ver `/Users/enzoalfonso/recado/005-migracion-icaco-a-zantia.md`). Stack del Core: Python 3.9 + pydantic + pytest + `sqlite3` (stdlib) — ver `.ai/DECISIONS.md`.

## Topología

Monorepo único (decisión confirmada el 2026-08-31, no se asume por defecto).

| Repo (nombre conceptual) | Ruta física | Remoto | Rol |
|---|---|---|---|
| ZANTIA | `/Users/enzoalfonso/Orangutan/icaco` | — (repo git local, sin remoto) | único repo del proyecto |

Nota deliberada: el nombre conceptual (ZANTIA) y el nombre de la carpeta física (`icaco`) son distintos a propósito — ver la nota de nomenclatura en `PROJECT.md`.

## Componentes

Core del MVP, ya implementado y con tests pasando (ver `.ai/TESTING.md` y `/Users/enzoalfonso/recado/006-construccion-zantia.md`):

| Componente | Tecnología | Rol | Repo/carpeta |
|---|---|---|---|
| Orchestrator | Python | Único punto de escritura del estado; coordina Brain/Guardrails/Tools/Memory (LLM propone, orquestador decide) | `core/orchestrator.py` |
| Brain | Python (FakeBrain determinista) + stub real (Anthropic, sin probar en vivo) | Interpreta el mensaje, propone cambios de estado — nunca los escribe | `core/brain.py` |
| ConversationState | pydantic | Fuente única de verdad para decisiones de flujo | `state/models.py` |
| StateStore | `sqlite3` (stdlib) | Persistencia real con concurrencia optimista por versión | `state/store.py` |
| Máquina de estados | Python | Transiciones válidas/inválidas, interrupciones globales | `state/machine.py` |
| Memory | Python (memoria de proceso) | Conversación reciente / perfil de usuario (parcial) / resumen | `memory/` |
| Knowledge | Python | Separación estático/dinámico; RAG documentado como stub, no implementado | `knowledge/` |
| Tools | Python | Contrato READ/WRITE/NOTIFY + 3 tools de demostración (datos ficticios) | `tools/` |
| Guardrails | Python | 3 reglas deterministas reales (riesgo, consentimiento, promesas prohibidas) | `guardrails/` |
| Observability | Python | Registro append-only de eventos (transiciones, tools, guardrails, errores) | `observability/` |
| Agente de demostración | Python | Valida el Core de extremo a extremo; NO es un dominio real | `agents/demo/` |
| **Dominio salud** (primer dominio real, bidireccional) | Python | Demanda inducida + acceso iniciado por el paciente (Activity/PatientRequest, correlación, AppointmentService, ReminderManager, ActivityResult). Ver `docs/health-demand-agent.md` | `domains/health/` |
| **HrmmAppointmentService** (adaptador real) | Python (`urllib` stdlib, sin dependencias nuevas) | Implementa `AppointmentService` contra la API real de hrmm-backend (otro proyecto) — identidad por documento, verificación por código para cancelar/reprogramar. Sin probar contra red real todavía | `domains/health/hrmm_appointment_service.py`, `hrmm_http.py`, `hrmm_catalog.py` |
| Contratos de dominio (resto) | Python (solo interfaz) | `domains/{emergency,sales,citizen}/` sin lógica todavía | `domains/` |
| Contrato de canal | Python (solo interfaz) + `MockChannel` | Sin canal real elegido; `MockChannel` demuestra el contrato | `channels/` |

## Capas (si aplica al tipo de proyecto)

- **Experiencia**: canal conversacional de cara al usuario final — sin decidir (ver `channels/contract.py` y `.ai/INTEGRATIONS.md`).
- **Aplicaciones**: `core/orchestrator.py` + `core/agent_contract.py` — agnósticos de dominio.
- **Integración**: `tools/` (READ/WRITE/NOTIFY) — solo tools de demostración ficticias por ahora.
- **Datos**: `state/` (ConversationState) + `memory/` — sujetos a `.claude/rules/proteccion-datos-personales.md`; ver `.ai/DATA_MODEL.md`.
- **Inteligencia**: `core/brain.py` — `FakeBrain` (determinista, usado en tests y demo) y `AnthropicBrain` (real, documentado, sin ejercer en esta sesión). Documentado en `.ai/AGENTS.md`.

## Dependencias entre componentes

```
channels (sin implementar) -> core.Orchestrator -> {
    state.StateStore, memory.ConversationMemory, core.Brain,
    tools.ToolRegistry, guardrails.GuardrailEngine, observability.EventLog
}
agents/demo -> core.agent_contract.build_orchestrator -> ensambla todo lo anterior
domains/* -> (futuro) implementarán domains.contract.DomainModule, consumiendo
             core.agent_contract.AgentDefinition — todavía no lo hacen
```

## Rutas críticas

- 🔴 `/Users/enzoalfonso/Orangutan/icaco` (la carpeta raíz en sí) — ancla la memoria de sesión de Claude Code (`~/.claude/projects/-Users-enzoalfonso-Orangutan-icaco/`). No renombrar sin plan explícito (ver recado 005).
- 🟡 `state/models.py` — cualquier cambio de campo del `ConversationState` afecta a todo el Core (Orchestrator, Guardrails, Brain, tests).
- 🟡 `state/machine.py` — cambiar `VALID_TRANSITIONS` sin actualizar `core/orchestrator.py` puede dejar transiciones huérfanas.
- 🟢 `tools/demo_tools.py`, `agents/demo/` — de demostración, seguros de modificar/eliminar cuando exista un dominio real.
- 🟢 `domains/*/README.md` — placeholders, seguros de reemplazar cuando se diseñe cada dominio (`domains/health/` ya no aplica — es real).
- 🟡 `domains/health/models.py` (`Activity`, `Appointment`, `Reminder`) — cambios de campo afectan a `agent.py`, `brain.py`, `tools.py` y toda la suite `tests/domains/health/`.
- 🔴 `domains/health/hrmm_appointment_service.py` — cualquier cambio debe re-verificarse contra el código real de `hrmm-backend` (otro proyecto, fuera de este repo) antes de confiar en él; un desajuste de contrato aquí falla contra un sistema de producción real, no contra un Mock.
