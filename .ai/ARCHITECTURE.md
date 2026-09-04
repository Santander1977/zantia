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
| StateStore | `sqlite3` (stdlib) | Persistencia real con concurrencia optimista por versión — conectada por `core/agent_contract.py:build_orchestrator` vía `ZANTIA_DB_PATH` (recado 021; antes hardcodeado a `":memory:"`, brecha de wiring documentada en R-11/R-22 y descrita también en `docs/decisions/d-6-identidad-canal-persistente.md`). Sin la variable, cae a `":memory:"` con un `logger.warning` explícito, nunca en silencio | `state/store.py`, `core/agent_contract.py` |
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
| Capa de configuración salud | Python (stdlib) | Único punto que decide Mock vs. `HrmmAppointmentService` según `HRMM_BACKEND_ENV` — falla al arrancar si faltan variables, nunca degrada en silencio | `domains/health/config.py` |
| **Identidad de canal persistente** (recado 014) | Python + `sqlite3` (stdlib) | Tabla `identidad_canal` (teléfono→documento verificado), INDEPENDIENTE del `ConversationState` por Activity — vive a nivel de `HealthGateway` (proceso), sobrevive a un reinicio si `ZANTIA_IDENTIDAD_DB_PATH` apunta a un archivo real | `domains/health/identity_store.py` |
| Contrato de canal | Python (solo interfaz) + `MockChannel` + **`ChatwootChannel`** (real, decisión D-5) | `ChatwootChannel` implementa el contrato contra la API de Chatwoot (webhook `message_created` + respuesta). Probado con fixtures y con un servidor uvicorn real vía curl — nunca conectado a un inbox de producción en esta sesión | `channels/`, `channels/chatwoot_channel.py` |
| **service/app.py** (transporte HTTP) | FastAPI + uvicorn (decisión D-5 — única excepción al stdlib-only de D-1, solo en esta capa) | `GET /health` + `POST /webhook/chatwoot`; compone `AppointmentService` una sola vez al arrancar vía `domains.health.config.build_appointment_service()` | `service/app.py`, `Dockerfile` |

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
- 🟡 Brecha de identidad teléfono↔documento (`domains/health/gateway.py:_gestionar_identificacion`/`_identidad_resuelta`, extendida en `domains/health/brain.py` para beneficiarios y en `domains/health/identity_store.py` para persistencia entre conversaciones) — RESUELTA A NIVEL DE DISEÑO en recados `012`/`013`/`014`: con un canal en `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO` (hoy solo `"chatwoot"`), se pide el documento al paciente antes de cualquier otra intención, se confirma contra `buscar-paciente`, se exige un código de verificación por correo (014), y solo entonces se asocia — tanto en memoria (`_identidad_resuelta`, esta conversación) como en `identidad_canal` (persistente, conversaciones futuras); `HealthBrain` reconoce además gestión "en nombre de otro paciente" (`_PARA_OTRO`), validando y confirmando el documento del beneficiario antes de usarlo en la reserva. Sigue en 🟡 (no 🟢) porque: (a) nunca se probó contra la red real ni con `HRMM_BACKEND_ENV=production` de verdad; (b) `buscar-paciente` solo encuentra pacientes con historial previo en hrmm-backend — un paciente genuinamente nuevo (titular o beneficiario) sería rechazado, decisión de producto sin resolver; (c) reprogramar/cancelar vía el wizard de verificación (Hrmm) todavía no distingue beneficiario; (d) el paso de código de 014 depende de `POST /api/agenda/verificacion/confirmar` en hrmm-backend, que TODAVÍA NO EXISTE ahí — ver R-19. Ver `.ai/RISKS.md` R-15.
- 🟡 `domains/health/brain.py` — desde recado `013` YA NO es un archivo "sin tocar" (excepción explícita autorizada por el usuario para esta extensión, distinta de todas las fases anteriores 007-012 donde estuvo protegido). Cualquier cambio futuro debe volver a confirmar explícitamente si sigue autorizado a tocarse, no asumirlo por precedente.
- 🔴 `POST /api/agenda/verificacion/confirmar` (hrmm-backend, fuera de este repo) — endpoint PROPUESTO por `domains/health/hrmm_appointment_service.py:HrmmAppointmentService.confirm_verification_code` (recado 014), coordinado con el usuario, pero NO IMPLEMENTADO todavía del lado de hrmm-backend. El gate de identidad de canal (`_procesar_codigo_de_identificacion`) queda bloqueado en producción real hasta que exista — ver R-19.
