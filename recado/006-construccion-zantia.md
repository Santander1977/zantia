# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (identidad conceptual desde 2026-09-01; carpeta física `/Users/enzoalfonso/Orangutan/icaco`, deliberadamente sin renombrar — ver decisión D-2)
Tema: Construcción real del "ZANTIA Core MVP" — primera fase de implementación tras la serie de auditorías y diseño conceptual (recados 001-005)
Objetivo: Documentar qué se construyó, cómo, con qué stack, qué funciona verificado (no solo declarado), qué falta, y qué potencial pedagógico deja esta fase para una futura "ZANTIA ACADEMY"

Este documento es autocontenido. Se apoya en `002-autopsia-cerebro-dani.md`, `003-arquitectura-cerebro-icaco.md`, `004-contrato-estado-icaco.md` y `005-migracion-icaco-a-zantia.md` (los cuatro históricos, no modificados en esta sesión). Convenciones: **HECHO** = verificado ejecutando algo en esta sesión (tests corridos, comandos ejecutados). **INFERENCIA** = conclusión razonada. **RECOMENDACIÓN** = propuesta. **PENDIENTE** = decisión aún no tomada.

---

## Resumen ejecutivo

HECHO: se construyó y se verificó en ejecución (no solo se diseñó) un Core agéntico funcional: `ConversationState` formal (pydantic), máquina de estados con transiciones válidas/inválidas, `StateStore` con persistencia real en SQLite y concurrencia optimista, `Orchestrator` que implementa el principio "el LLM propone, nunca escribe" y la prioridad "riesgo > escalamiento > dato faltante > acción > conversación normal", `GuardrailEngine` con 3 reglas deterministas reales, `ToolRegistry` con categorías READ/WRITE/NOTIFY, `EventLog` de observabilidad, y un agente de demostración que valida todo el flujo de extremo a extremo. 34 tests, **34 pasando** (`.venv/bin/pytest -q`, ejecutado en esta sesión, no una suposición).

HECHO: la identidad conceptual de la documentación operativa del proyecto (`PROJECT.md`, `README.md`, `CONTRIBUTING.md`, los 12 archivos de `.ai/`) se actualizó de "icaco" a "ZANTIA", sin renombrar la carpeta física (decisión D-2, ver `docs/decisions/d-2-nombre-fisico-icaco.md`).

HECHO: se inicializó git (no existía antes de esta sesión) y se hicieron 2 commits — uno con el estado heredado de `PROJECT-TEMPLATE` antes de tocar nada, y otro con toda la construcción — ambos reversibles individualmente.

No se modificó Dani, `PROJECT-TEMPLATE`, `orangutan-kit` ni los recados históricos `001`-`004` (verificado con hashes/mtimes al final de la sesión).

---

## Qué se construyó

### Estructura de directorios (dentro de `/Users/enzoalfonso/Orangutan/icaco`)

```
core/            orquestador, brain (LLM), configuración, contrato de agente
state/           ConversationState (pydantic), máquina de estados, StateStore (SQLite)
memory/          memoria de conversación, memoria de usuario (parcial), resumen
knowledge/       fuente de conocimiento estático/dinámico, stub de RAG
tools/           contrato de tool (READ/WRITE/NOTIFY), registro, 3 tools de demo
guardrails/      motor de guardrails + 3 reglas deterministas reales
observability/   registro append-only de eventos
agents/demo/     agente de demostración (NO es un dominio real)
domains/{health,emergency,sales,citizen}/   solo contratos, sin lógica (a propósito)
channels/        solo contrato de canal, sin implementación real
tests/           34 tests (unidad + integración end-to-end)
```

### Stack (decisión D-1, `docs/decisions/d-1-stack-core-mvp.md`)

Python 3.9.6 (el disponible en el sistema, en un `.venv` propio de este proyecto — no se reutilizó el venv de otro proyecto de Orangutan que estaba activo por defecto en el shell, `hrmm/backend/.venv`, precisamente para no violar el aislamiento entre proyectos) + `pydantic>=2,<3` + `pytest>=8,<9` + `sqlite3` de la librería estándar. `anthropic` queda listado como dependencia opcional en `requirements.txt`, comentada — no instalada, no requerida por los tests.

### Componentes, con su ruta y a qué documento de diseño responden

| Componente | Ruta | Responde a |
|---|---|---|
| `ConversationState` | `state/models.py` | 004, sección 2 (con 3 correcciones encontradas al implementar — ver más abajo) |
| Máquina de estados | `state/machine.py` | 004, secciones 6 y 9 |
| `StateStore` (SQLite + concurrencia optimista) | `state/store.py` | 004, secciones 11-12 |
| `Orchestrator` | `core/orchestrator.py` | 003, sección 5; 004, secciones 7-8, 15-17 |
| `Brain` (`FakeBrain` + `AnthropicBrain`) | `core/brain.py` | 004, sección 15 |
| `GuardrailEngine` + reglas | `guardrails/` | 004, sección 16 |
| `ToolRegistry` + tools de demo | `tools/` | 004, sección 17 |
| `ConversationMemory`/`UserMemory`/resumen | `memory/` | 004, sección 3 |
| `KnowledgeSource` | `knowledge/` | 003, sección 9 |
| `EventLog` | `observability/` | 004, sección 13 |
| Agente de demostración | `agents/demo/` | prompt maestro, sección 27 |
| Contratos de dominio/canal | `domains/`, `channels/` | prompt maestro, secciones 9 y 6 (canal) |

---

## Decisiones tomadas durante la construcción (documentadas en `.ai/DECISIONS.md`)

- **D-1**: stack del Core MVP (ver arriba). IMPLEMENTADA.
- **D-2**: conservar el nombre físico `icaco` bajo la identidad conceptual ZANTIA. IMPLEMENTADA.
- **Decisión no formalizada como D-N, pero documentada en código** (`core/agent_contract.py`, docstring): `state/`, `memory/`, `knowledge/`, `tools/`, `guardrails/`, `observability/` se implementaron como paquetes Python de primer nivel (hermanos de `core/`), no como submódulos anidados dentro de `core/`. El prompt maestro tenía cierta tensión entre su sección 7 ("el Core debe contener state/memory/knowledge/...") y su sección 21 (que los lista como carpetas top-level separadas) — se priorizó la lectura literal de la sección 21 por ser más concreta, dejando `core/` con solo `orchestrator.py`, `brain.py`, `agent_contract.py`, `config.py`.

---

## Correcciones encontradas al implementar (transparencia — sección 38 del prompt maestro)

No se ocultan, tal como pide el propio protocolo de formación (sección 24 de `005`):

1. **`nivel_de_riesgo` vs. `señal_de_urgencia` estaban casi fusionados en 004** — al modelarlos como campos pydantic separados quedó claro que uno es una escala gradual y el otro un disparador booleano. Se documentó explícitamente en `state/models.py`.
2. **`contexto` (texto narrativo) se eliminó del `ConversationState`**, reemplazado por `resumen_ref` (un puntero) — evita la duplicación que la propia auditoría de 004 ya había señalado como riesgo de diseño, esta vez confirmada al intentar implementarlo tal cual.
3. **La máquina de estados de 004 no contemplaba que, dentro de UN mismo turno, `RECOPILACION_DE_DATOS` pudiera saltar directo a `RESPUESTA`** cuando el último dato requerido llega y el Brain propone ejecutar una tool en el mismo ciclo (sin que `RAZONAMIENTO_DECISION` y `ACCION` sean paradas de `fase_actual` separadas, aunque sí quedan registradas como eventos de observabilidad). Se corrigió agregando esa transición a `state/machine.py`, con el motivo documentado en el propio código — es un hallazgo real de la fase de implementación, no un error de la fase de diseño (el diseño en papel no podía anticipar esta particularidad de "un turno, una respuesta síncrona completa").

---

## Qué está funcionando (verificado, no declarado)

HECHO — ejecutado en esta sesión, `.venv/bin/pytest -q` → `34 passed`:

- Creación y recuperación de sesión (`ConversationState`).
- Persistencia real: un `SQLiteStateStore` escrito con una conexión y leído con una conexión nueva al mismo archivo recupera el estado exacto.
- Concurrencia optimista: una escritura con versión desactualizada se rechaza (`ConcurrencyConflictError`).
- Transición válida e inválida de la máquina de estados; interrupción global permitida desde cualquier estado no terminal; estados terminales bloquean transiciones salientes.
- Guardrail que bloquea una tool WRITE sin consentimiento; guardrail que escala si se intenta bajar `senal_de_urgencia`; guardrail que reemplaza una respuesta con una promesa prohibida (lección de Dani).
- Tool READ, tool WRITE idempotente (misma `idempotency_key` no duplica efecto), tool que lanza error simulado y es capturada sin tumbar el proceso, tool NOTIFY.
- **Conversación normal de extremo a extremo**: 3 turnos (intención → recopilar dato → recopilar segundo dato + ejecutar tool) llegan a `RESPUESTA` con la tool ejecutada y el resultado persistido en el estado.
- **Interrupción prioritaria por riesgo**: un mensaje con palabra clave de riesgo interrumpe de inmediato, sin pasar por ninguna fase intermedia, llega a `ESCALADO_URGENTE`, y la respuesta nunca promete contacto ni tiempo.
- **Prioridad de riesgo sobre cualquier otra intención simultánea**: un mensaje que combina "programar evento" + "hablar con alguien" + señal de riesgo escala por riesgo, sin tocar ninguna tool.
- Idempotencia a nivel de mensaje: el mismo `message_id` procesado dos veces no duplica la transición de estado ni genera una segunda respuesta distinta.
- Observabilidad: transiciones de estado, invocaciones de tool y decisiones de guardrail (incluidos los bloqueos) quedan registrados como eventos consultables por `conversation_id`.

---

## Qué falta (PENDIENTE, no inventado)

- **Canal real**: `channels/contract.py` es solo la interfaz — ningún canal (WhatsApp/Telegram/web) está conectado.
- **`AnthropicBrain` sin probar en vivo**: el código existe y es real, pero no se ejecutó con una API key en esta sesión (correctamente, no había una configurada, y los tests deben ser deterministas). PENDIENTE de una prueba de integración separada cuando se decida activarlo.
- **Protocolo clínico de riesgo/urgencia por dominio**: `RISK_KEYWORDS_DEMO` en `core/brain.py` es una lista de ejemplo genérica, explícitamente no médica (sección 27 del prompt maestro) — el criterio real sigue **PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL**, heredado de `003` y `004`.
- **Dominios reales**: `domains/{health,emergency,sales,citizen}/` son contratos vacíos a propósito (sección 9 del prompt maestro lo prohibía explícitamente en esta fase).
- **Mecanismo de acceso/eliminación de datos personales por el usuario final**: exigido por `.claude/rules/proteccion-datos-personales.md`, no implementado — `memory/user_memory.py` es deliberadamente parcial.
- **Persistencia de memoria de conversación y de eventos de observabilidad entre procesos**: hoy viven en memoria de proceso (`ConversationMemory`, `EventLog`); solo el `ConversationState` tiene persistencia real en disco (SQLite).
- **Deduplicación de mensajes persistida**: hoy vive en un diccionario en memoria del `Orchestrator` (`_respuestas_por_mensaje`), no en el `StateStore` — documentado como simplificación de MVP en el propio código.
- **Reintentos de tool con backoff real**: el manejo de error de tool actual es de un solo intento; no hay política de reintento configurable todavía.

---

## Problemas encontrados

Ninguno bloqueante. El único hallazgo fue la corrección de máquina de estados ya descrita arriba (sección "Correcciones encontradas al implementar"), resuelta en la misma sesión.

---

## Decisiones futuras (no tomadas aquí, a propósito)

- Elegir canal de mensajería real.
- Decidir si `AnthropicBrain` se activa con una API key real y en qué entorno.
- Diseñar el primer dominio real (probablemente `health`, dado el objetivo original del proyecto) — requiere el protocolo clínico de riesgo, todavía pendiente de validación humana.
- Decidir si/cuándo ejecutar el renombrado físico de la carpeta (D-2 lo difiere, no lo descarta).
- Decidir política de retención y mecanismo de auditoría persistente (hoy `EventLog` es solo de proceso).

---

## Potencial pedagógico para ZANTIA Academy

Continuando el protocolo adoptado en `005` (documentación técnica separada de la pedagógica — ver memoria `documentacion_pedagogica_zantia.md`): esta fase es la primera vez que el ecosistema tiene código real ejecutándose, lo cual habilita módulos que antes solo podían enseñarse en abstracto.

- **Clase**: "De un contrato de papel a un modelo `pydantic` real" — usando `state/models.py` junto a la tabla de campos de `004` sección 2, mostrando las 3 correcciones que aparecieron solo al implementar (ejemplo real de por qué el diseño y la implementación se retroalimentan).
- **Laboratorio**: "Agrega una cuarta regla de guardrail" — `guardrails/rules.py` ya tiene 3 reglas cortas y bien aisladas, ideal como plantilla de ejercicio guiado.
- **Caso de estudio**: los dos tests de `tests/core/test_orchestrator_e2e.py` son, literalmente, los dos ejemplos de `004` sección 18 convertidos en código verificable — material perfecto para mostrar "esto se diseñó en papel, esto es exactamente lo mismo corriendo".
- **Checklist**: la lista de "Qué está funcionando" de este recado, reformulada como checklist de verificación de un MVP agéntico (creación de sesión, persistencia, concurrencia, guardrails, tools por categoría, idempotencia, observabilidad, flujo end-to-end, interrupción prioritaria) — ya cubre, con evidencia real, buena parte de los "15 módulos" evaluados en `005`.
- **Diagrama**: la estructura de directorios de esta sección es ya un diagrama de arquitectura de componentes real, no solo conceptual — actualiza directamente el diagrama ASCII de `003` sección 4 con nombres de archivo verificables.
- **Evaluación**: sigue sin existir material de evaluación derivable (igual que se declaró honestamente en `005`) — no se inventa aquí tampoco.

Huecos que siguen abiertos para la Academy (coherente con la evaluación honesta de `005`): multiagentes (todavía un solo agente de demostración, ningún dominio coordinando con otro), deployment (nada desplegado), testing como módulo propio de enseñanza (existe la suite, pero no material que explique el *por qué* de cada categoría de test más allá de este recado).
