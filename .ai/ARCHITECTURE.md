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
| Contrato de canal | Python (solo interfaz) + `MockChannel` + **`ChatwootChannel`** (real, decisión D-5) + **`TelegramChannel`** (real, decisión D-7) + **`WebChannel`** (real, recado 078/079) | `ChatwootChannel` implementa el contrato contra la API de Chatwoot (webhook `message_created` + respuesta). `TelegramChannel` (recado 022) implementa el mismo contrato contra la Bot API de Telegram, también por webhook — sin tabla de correlación interna (el `chat.id` de Telegram YA es el identificador que necesita para responder). `WebChannel` (recado 079) implementa el contrato para el widget de `chat.semcolombia.com` (`eis-chat-hrmm`, repo separado) — el MÁS SIMPLE de los tres: ciclo request/response síncrono de un solo paso (sin envío de respuesta como llamada de red separada), `sessionId` (persistente en `localStorage` del navegador desde `eis-chat-hrmm` commit `c83d3d9`) como identificador de canal, SIN `secret_token`/autenticación de origen (decisión explícita, ver `.ai/RISKS.md` R-26). Los 3 probados solo con fixtures/mocks/`TestClient` — ninguno conectado a un consumidor de producción real todavía salvo `WebChannel` (a desplegar en EasyPanel, recado 079) | `channels/`, `channels/chatwoot_channel.py`, `channels/telegram_channel.py`, `channels/web_channel.py` |
| **service/app.py** (transporte HTTP) | FastAPI + uvicorn (decisión D-5 — única excepción al stdlib-only de D-1, solo en esta capa) | `GET /health` + `POST /webhook/chatwoot` (Chatwoot OPCIONAL desde D-8/recado 024 — `503` si no está configurado) + `POST /webhook/telegram` (recado 022, obligatorio configurar si se usa este canal) + `POST /webhook/web` (recado 079, sin configuración/secreto que exigir — ver R-26); compone `AppointmentService` una sola vez al arrancar vía `domains.health.config.build_appointment_service()`. Los 3 canales comparten el MISMO `HealthGateway`/`identity_store` | `service/app.py`, `Dockerfile` |

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
- 🟡 Brecha de identidad teléfono↔documento (`domains/health/gateway.py:_gestionar_identificacion`/`_identidad_resuelta`, extendida en `domains/health/brain.py` para beneficiarios y en `domains/health/identity_store.py` para persistencia entre conversaciones) — RESUELTA A NIVEL DE DISEÑO en recados `012`/`013`/`014`/`016`: con un canal en `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO` (`"chatwoot"`, desde recado 022 `"telegram"`, y desde recado 079 `"web"`), se pide el documento al paciente antes de cualquier otra intención, se confirma contra `buscar-paciente`, se exige un código de verificación por correo (014), y solo entonces se asocia — tanto en memoria (`_identidad_resuelta`, esta conversación) como en `identidad_canal` (persistente, con vencimiento a 180 días y eliminación a pedido, recado 016); `HealthBrain` reconoce además gestión "en nombre de otro paciente" (`_PARA_OTRO`), validando y confirmando el documento del beneficiario antes de usarlo en la reserva. Sigue en 🟡 (no 🟢) porque: (a) nunca se probó contra la red real ni con `HRMM_BACKEND_ENV=production` de verdad; (b) `buscar-paciente` solo encuentra pacientes con historial previo en hrmm-backend — un paciente genuinamente nuevo (titular o beneficiario) sería rechazado, decisión de producto sin resolver; (c) reprogramar/cancelar vía el wizard de verificación (Hrmm) todavía no distingue beneficiario. Ver `.ai/RISKS.md` R-15.
- 🟡 `domains/health/brain.py` — desde recado `013` YA NO es un archivo "sin tocar" (excepción explícita autorizada por el usuario para esa extensión, reconfirmada en recado 016). Cualquier cambio futuro debe volver a confirmar explícitamente si sigue autorizado a tocarse, no asumirlo por precedente.
- 🟢 `POST /webhook/telegram` (`service/app.py`, recado 022) — a diferencia de `POST /webhook/chatwoot` (sigue 🟡, R-18 ABIERTO), este SÍ autentica el origen desde recado 023: `TelegramChannel.verificar_secreto_webhook` valida `X-Telegram-Bot-Api-Secret-Token` contra `TELEGRAM_WEBHOOK_SECRET` (obligatoria al arrancar) antes de procesar cualquier payload — ver `.ai/RISKS.md` R-23 (RESUELTO).
- 🟡 `POST /webhook/web` (`service/app.py`, `channels/web_channel.py`, recado 079) — sin ninguna autenticación de origen (decisión explícita del usuario, riesgo documentado y ACEPTADO para el despliegue de hoy, no un descuido) — ver `.ai/RISKS.md` R-26. Único de los 3 webhooks sin ningún mecanismo de verificación disponible ni planeado para esta primera versión — cualquier mejora futura (secreto compartido con `eis-chat-hrmm`) requiere coordinar un cambio en AMBOS repos.
