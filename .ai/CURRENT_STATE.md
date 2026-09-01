# ESTADO ACTUAL — ZANTIA

> Snapshot. Se sobrescribe, no se acumula — la historia completa vive en `docs/changelog/`. Este archivo responde: "si entro ahora mismo, ¿qué necesito saber para no romper nada ni repetir trabajo?"

**Última actualización**: 2026-09-01 (construcción del Core ZANTIA MVP)

## Qué está desplegado

| Componente | Versión/commit | Entorno | Estado |
|---|---|---|---|
| — | — | — | Nada desplegado todavía. El Core existe como código local con tests pasando (34/34), sin canal ni servidor expuesto. |

## Trabajo en curso sin commitear

Ver `git status` al momento de leer esto — esta sesión construyó el Core completo (`core/`, `state/`, `memory/`, `knowledge/`, `tools/`, `guardrails/`, `observability/`, `agents/demo/`, `domains/*` stubs, `channels/` contrato, `tests/`) y actualizó la identidad conceptual de la documentación operativa a ZANTIA. Ver `/Users/enzoalfonso/recado/006-construccion-zantia.md` para el detalle completo.

## Conocido roto / pendiente de verificación

- Canal exacto de mensajería (WhatsApp/Telegram/etc.) sin decidir — `channels/contract.py` define la interfaz, sin implementación real.
- Jurisdicción/marco legal exacto para la regla de habeas data sin confirmar (ver `.claude/rules/proteccion-datos-personales.md`).
- `domains/{health,emergency,sales,citizen}/` son solo contratos — ningún dominio real implementado.
- `core/brain.py:AnthropicBrain` es código real pero no probado en vivo (sin `ANTHROPIC_API_KEY` en esta sesión) — los tests usan `FakeBrain`.
- Protocolo clínico de riesgo/urgencia por dominio: sigue PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL (heredado de 003/004) — el Core solo tiene el mecanismo (campo `senal_de_urgencia`, guardrail que lo protege), no el criterio real.
- Mecanismo de acceso/eliminación de datos personales por parte del usuario final (exigido por `.claude/rules/proteccion-datos-personales.md`): no implementado, `memory/user_memory.py` es deliberadamente parcial.

## Progreso reciente

Resumen breve de las últimas sesiones relevantes. El detalle completo, sesión por sesión, vive en `docs/changelog/` (rotado por período — ver `.claude/rules/documentacion-y-memoria.md`).

- 2026-08-31: Proyecto creado desde `PROJECT-TEMPLATE` (commit `6fd36c7`) vía `/new-project`. Tipo: agente conversacional. Topología: monorepo único. Regla de dominio adicional: habeas data. Aislamiento verificado sin resultados.
- 2026-08-31 a 2026-09-01: Serie de auditorías de solo lectura (recados 001-005 en `/Users/enzoalfonso/recado/`) sobre Dani (agente de ventas de referencia) y diseño conceptual de arquitectura para ICACO/ZANTIA — sin tocar código.
- 2026-09-01: Construcción del Core ZANTIA MVP. `git init` + primer commit del estado heredado. Stack elegido: Python 3.9 + pydantic + pytest + `sqlite3`. Implementados: `ConversationState` (pydantic), máquina de estados formal, `StateStore` (SQLite con concurrencia optimista), `Orchestrator` (principio LLM-propone/sistema-decide), `GuardrailEngine` con 3 reglas reales, `ToolRegistry` + 3 tools de demostración, `EventLog` de observabilidad, agente de demostración de extremo a extremo. 34 tests, todos pasando. Identidad conceptual de la documentación operativa actualizada a ZANTIA (carpeta física sigue siendo `icaco`). Ver recado `006-construccion-zantia.md`.
