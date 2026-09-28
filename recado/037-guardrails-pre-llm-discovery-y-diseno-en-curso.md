# 037 — Guardrails pre-LLM (Core): implementado, probado, documentado

**Fecha**: 2026-09-06
**Estado**: implementado y con suite completa en verde (272 passed, 2 skipped) — **sin commitear todavía**, pendiente de tu revisión (este trabajo no incluye mensajes nuevos al paciente que requieran aprobación de tono, pero sigue el mismo criterio de nunca comitear sin que lo pidas explícitamente).
**Continúa**: pedido explícito de construir, en el Core (agnóstico de dominio), los guardrails que deben estar sólidos ANTES de conectar cualquier LLM real. **Ningún LLM se conectó en este trabajo** — es exclusivamente la capa de seguridad previa.

## Resumen ejecutivo

De las 5 partes pedidas, **4 quedaron implementadas y probadas** (Partes 1, 2, 3, 5) y **1 quedó como diseño documentado sin implementar el criterio clínico**, tal como se pidió explícitamente (Parte 4) — más una corrección de robustez real encontrada al investigar la Parte 4, sí implementada porque no requería ninguna decisión clínica.

---

## PARTE 1 — Persistencia real de EventLog y ConversationMemory (R-11)

### Diseño

Mismo patrón EXACTO que `ConversationState`/`ZANTIA_DB_PATH` (recado 021):

- **`SQLiteEventLog`** (`observability/events.py`) — nueva variable `ZANTIA_EVENTS_DB_PATH`. Esquema: tabla `events` con `seq` autoincremental (orden de inserción, no confiar en timestamp para desempatar), `event_id`, `conversation_id`, `type`, `payload` (JSON), `timestamp`. `record()`/`for_conversation()`/`all()` — mismo contrato que la clase en memoria.
- **`SQLiteConversationMemory`** (`memory/conversation_memory.py`) — nueva variable `ZANTIA_MEMORY_DB_PATH`. Tabla `conversation_turns`. Decisión explícita (requisito #2 del pedido, "documenta por qué deben persistir juntos si no lo es"): **sí es técnicamente separable** de `ConversationState` (clave/forma distintas, igual que `identity_store` lo es — ver D-6, recado 021) — se separó en su propia clase, su propia tabla, su propia variable de entorno.
- **Decisión de retención** (no pedida explícitamente, pero necesaria para no inventar una política nueva sin que quede documentada): `get_recent()` sigue devolviendo como máximo `window_size` turnos — igual contrato que la versión en memoria (Capa B, nunca autoridad de decisión, 004 sección 3). La TABLA en sí conserva el historial completo sin truncar — la ventana se aplica solo en la lectura. Esto es lo que permite, en el futuro, auditar qué dijo realmente un LLM en un turno que ya salió de la ventana reciente. La política de retención de esta tabla queda con el MISMO estado "PENDIENTE" que ya tenía `ConversationState` en `.ai/DATA_MODEL.md` — no se resuelve aquí, no se inventa una nueva regla de negocio.
- Ambos con `EventLogProtocol`/`ConversationMemoryProtocol` (Protocols explícitos, mismo criterio que `state.store.StateStore`) para dejar el contrato duck-typed documentado, no implícito.
- Único punto de construcción real: `core/agent_contract.py:build_orchestrator` — mismo `logger.warning` explícito si la variable no está configurada (nunca en silencio), uno por cada una de las 2 variables nuevas.
- **`domains/health/` no se tocó** para esto — reutiliza `build_orchestrator` tal cual (mismo patrón que R-22/recado 021), así que hereda la persistencia automáticamente.

### Verificación

- `tests/observability/test_events_persistencia.py` (3 tests): EventLog sobrevive a un "reinicio del proceso" real (misma Activity, nuevo `Orchestrator`, mismo archivo); comportamiento por defecto sin la variable (`:memory:` + warning); sin warning cuando SÍ está configurada.
- `tests/memory/test_conversation_memory_persistencia.py` (3 tests): mismo patrón para ConversationMemory, más un test dedicado confirmando que la ventana de lectura se mantiene acotada aunque la tabla tenga más filas que `window_size`.

---

## PARTE 2 — `DatoInventadoGuardrail`

### Diseño

**Decisión de diseño clave** (no explícita en el pedido, pero necesaria para que fuera genuinamente agnóstica): en vez de que el Core intente RECONOCER qué es una fecha/servicio/consultorio (imposible sin conocimiento de dominio), es el propio Brain/dominio quien declara, por turno, una lista de `VerificacionDeDatos` (`guardrails/base.py`) — cada una con: `nombre_categoria` (solo para el mensaje de error), `patron` (una regex que el DOMINIO define, nunca el Core), y `valores_permitidos` (los valores reales confirmados ese turno). El Core solo sabe: "aplicar este patrón sobre este texto libre, y comparar cada coincidencia contra esta lista" — exactamente el contrato pedido ("el Core no debe saber qué es una cita").

`BrainOutput.verificaciones_de_datos: List[VerificacionDeDatos] = []` — si el Brain no declara ninguna (caso de hoy, con Brain determinista), el guardrail es un ALLOW inmediato, nunca un falso positivo sobre un dominio que no lo usa todavía.

**No se retroalimentó a `HealthBrain`** — decisión deliberada, documentada: el Brain determinista de salud nunca inventa nada (solo elige de listas reales ya confirmadas contra `AppointmentService`), así que declarar `verificaciones_de_datos` ahí sería, literalmente, lo que tú mismo señalaste en el pedido: "redundante pero inofensivo". Se deja como trabajo natural para el día que se conecte un Brain basado en LLM al dominio salud (fuera de alcance de este recado).

### Verificación

`tests/guardrails/test_guardrails_pre_llm.py` (4 tests para este guardrail) — deliberadamente con un ejemplo NO relacionado con salud ("número de pedido") para demostrar que el mecanismo es genuinamente agnóstico, más un test con 2 categorías simultáneas (fecha + hora) y otro confirmando el ALLOW por default sin declaración.

---

## PARTE 3 — `ConfirmacionEstructuradaRequeridaParaWriteGuardrail`

### Hallazgo real al revisar el punto 1 del pedido

Revisé TODOS los puntos donde se propone una tool WRITE (`grep` sobre `tool_requerida=.*name.*book_appointment\|reschedule_appointment\|cancel_appointment\|schedule_event`):

- `domains/health/brain.py:_interpretar_horario` (book_appointment) — confirmación determinista YA existía: ordinal elegido de una lista real (`_elegir_opcion`).
- `domains/health/brain.py:_interpretar_seleccion_reprogramacion` (reschedule_appointment, solo Mock) — mismo patrón, ordinal.
- `domains/health/brain.py:_cancelar` (cancel_appointment, solo Mock) — frase imperativa exacta (`_CANCELAR`), determinista pero de un tipo distinto (sin segundo turno de "¿confirmas?") — documentado explícitamente como diferencia deliberada, nunca alcanzable por un paciente real (el cancelar real SIEMPRE pasa por el sub-flujo de código de verificación, ver abajo).
- `core/brain.py:FakeBrain` (schedule_event, demo del Core) — **este SÍ tenía el hueco real**: ejecutaba la tool WRITE en el mismo turno donde se completaban los 2 datos (evento+fecha), sin ningún paso de confirmación — la definición MÁS débil de "estructurada" de todo el sistema.

**El hallazgo más importante, estructural**: nada de esto estaba protegido por el CORE mismo — la seguridad de hoy existe enteramente porque cada Brain, por su propia disciplina, nunca propuso una tool WRITE sin haber confirmado antes. Si un futuro Brain basado en LLM tuviera un bug (o alucinara una confirmación), el `Orchestrator` la habría ejecutado igual — `ConsentimientoRequeridoParaWriteGuardrail` (ya existente) solo verifica un consentimiento GENERAL de una sola vez, nunca una confirmación específica de ESTA acción.

### Corrección aplicada

1. `BrainOutput.confirmacion_estructurada_para_write: bool = False` — el Brain debe declararlo EXPLÍCITAMENTE en el mismo `return` donde ya ocurrió la confirmación determinista.
2. `ConfirmacionEstructuradaRequeridaParaWriteGuardrail` (`guardrails/rules.py`) — **fail-safe por diseño**: si la tool propuesta es WRITE y el flag no es `True`, BLOCK. Convierte una suposición implícita en un contrato explícito y auditable.
3. Los 3 puntos reales de `domains/health/brain.py` ahora declaran el flag exactamente donde ya ocurría la confirmación (sin cambiar NINGUNA lógica de negocio existente).
4. `core/brain.py:FakeBrain` — corregido de verdad: ahora pide una confirmación explícita ("¿Confirmas que agendo 'X' para 'Y'? Responde sí o no.") ANTES de proponer `schedule_event`, con un chequeo determinista de "sí"/"si" por límite de palabra (`_es_confirmacion_positiva`, sin depender de nada de `domains/health/`). Esto agrega UN turno más al demo del Core — 3 tests existentes actualizados (ver Migración abajo).

### Nota sobre el sub-flujo REAL de cancelar/reprogramar (hrmm-backend)

`gateway.py:_procesar_intento_de_codigo` (cancelar/reprogramar reales, con `HrmmAppointmentService`) **NO pasa por este guardrail** — es, por diseño ya documentado en el propio código ("wizard determinista, no una conversación que pase por Core"), una llamada directa de Python a `cancel_appointment_verified`/`reschedule_appointment_verified`, gateada por un ordinal + un código de verificación de 6 dígitos confirmado por hrmm-backend. Es, de hecho, el camino MÁS seguro de todo el sistema (no hay ningún Brain/LLM que pudiera interponerse) — documentado aquí explícitamente para que quede registrada la asimetría: si `gateway.py` alguna vez se reescribe para pasar por Core/Brain (ej. para reusar un LLM en la redacción), este guardrail debería extenderse para cubrirlo también.

### Migración de tests (3 archivos, Core)

`tests/core/test_orchestrator_e2e.py`, `tests/core/test_agent_contract_persistencia.py`, `tests/observability/test_events.py` — los 3 que llegaban hasta la ejecución real de `schedule_event` necesitaron un turno "sí" adicional antes de la aserción final. Ninguna aserción de fondo cambió — mismo patrón de migración que el recado 035 aplicó a `domains/health/`.

### Verificación

- `tests/guardrails/test_guardrails_pre_llm.py` (4 tests para este guardrail, aislados).
- `tests/domains/health/test_confirmacion_estructurada_write.py` (4 tests): 3 unitarios confirmando que `_interpretar_horario`/`_cancelar`/`_interpretar_seleccion_reprogramacion` declaran el flag, y 1 de integración de extremo a extremo (reserva real completa) — si el flag faltara en cualquiera de los 3 puntos, este test habría fallado (el guardrail habría bloqueado la reserva).

---

## PARTE 4 — Riesgo/escalamiento: revisión + diseño (sin implementar criterio clínico)

### Revisión de la extensión en `domains/health/` (punto 1 del pedido)

`[CONFIRMADO con grep]`: **`domains/health/` NO tiene ninguna lista de riesgo propia/extendida.** Hereda tal cual el `RISK_KEYWORDS_DEMO` genérico del Core (4 frases: "urgente", "emergencia", "ayuda inmediata", "muy grave") vía `core/orchestrator.py:detect_risk_keywords`. `.ai/RISKS.md` R-1 ya documentaba esto correctamente ("heredado del Core") — actualizado con la confirmación explícita de esta sesión, sin cambiar su estado (sigue ABIERTO, sigue pendiente de validación clínica/legal).

### Hallazgo real de robustez (no una decisión clínica — corregido, no solo diseñado)

Al revisar la arquitectura para diseñar la "capa separada" pedida, encontré que **ya es una capa separada** en el sentido correcto: `detect_risk_keywords()` corre en el `Orchestrator`, nunca en el Brain, y su resultado NUNCA depende de lo que el Brain haya propuesto. Pero encontré un defecto de ORDEN: `core/orchestrator.py:handle_message` calculaba `riesgo_detectado = detect_risk_keywords(text)` **DESPUÉS** de invocar `self._brain.interpret(...)`. Con el Brain determinista de hoy esto nunca importó (nunca lanza una excepción). Pero un Brain real basado en LLM SÍ puede fallar (timeout de red, error de API, JSON inválido — `AnthropicBrain.interpret()` no tiene ningún try/except propio) — y si fallara ANTES de que se calculara el riesgo, un mensaje genuinamente urgente se habría perdido en un crash sin escalar nunca.

**Corregido** (no requiere ningún criterio clínico, es pura robustez de orquestación):
1. `riesgo_detectado` se calcula ANTES de invocar al Brain.
2. La llamada al Brain quedó envuelta en `try/except`: si falla, se registra el error en `EventLog` y se escala (urgente si había riesgo detectado, estándar si no) — nunca se propaga la excepción sin control hacia quien llama.

### Diseño propuesto para una capa de riesgo verdaderamente independiente `[PROPUESTO, no implementado]`

Para el día en que se conecte un LLM real, más allá de la corrección de orden de arriba:

1. **Vocabulario extensible por dominio, sin que el Core conozca el dominio**: agregar un campo opcional a `AgentDefinition` (ej. `risk_keywords_adicionales: Tuple[str, ...] = ()`) que cada dominio pueda declarar al construirse — el Core seguiría siendo quien EJECUTA la verificación (nunca delegada al Brain), solo el vocabulario se volvería configurable. Esto no resuelve R-1 (sigue siendo palabras clave, no un protocolo clínico validado) — solo evita que cada dominio tenga que bifurcar `detect_risk_keywords` para agregar sus propias señales.
2. **Clasificador de riesgo dedicado, separado del Brain conversacional**: cuando exista un LLM real, la detección de riesgo NO debería migrar a ser "una instrucción más" del mismo prompt conversacional — debería ser una llamada aparte (un clasificador más simple/barato, o un modelo fine-tuneado, o el mismo mecanismo de palabras clave con vocabulario validado clínicamente), ejecutada por el `Orchestrator` de forma independiente, ANTES o EN PARALELO a la llamada al Brain conversacional — nunca como parte de la misma respuesta que el LLM conversacional genera. Si ese clasificador dedicado fallara, la política de fail-safe debería ser conservadora: tratar como riesgo desconocido y escalar, nunca asumir "sin riesgo" por defecto ante un fallo.
3. Ninguno de los dos puntos anteriores se implementó — son PROPUESTA de arquitectura, documentada para cuando corresponda. La pieza que de verdad falta (el vocabulario/criterio clínico real) sigue, correctamente, fuera del alcance de cualquier sesión de código (R-1).

### Verificación

`tests/core/test_riesgo_independiente_del_brain.py` (3 tests, con un Brain de prueba que siempre lanza una excepción): mensaje con palabra de riesgo escala urgente aunque el Brain falle; mensaje sin riesgo escala estándar en vez de crashear; el fallo del Brain queda auditado en EventLog.

---

## PARTE 5 — `FueraDeAlcanceGuardrail`

### Diseño

Revisa el **mensaje entrante** del paciente (nuevo campo `GuardrailContext.mensaje_entrante`, poblado siempre por el Orchestrator con el `text` real de cada turno) contra una lista fija de frases de manipulación conocidas ("ignora tus instrucciones", "ignore previous instructions", "muéstrame tu system prompt", etc. — español e inglés). Si encuentra alguna, decisión `MODIFY`: reemplaza la respuesta propuesta por un mensaje de redirección seguro ("Solo puedo ayudarte con la gestión de tu cita..."), sin importar qué haya propuesto el Brain para ese turno.

Se decidió revisar el mensaje ENTRANTE (no solo la respuesta propuesta, aunque el pedido lo mencionaba como "respuesta propuesta") porque el ataque en sí vive en lo que escribe el paciente — con un Brain determinista, además, ninguna de estas frases coincide con ningún patrón de intención real, así que hoy es 100% redundante (documentado explícitamente, igual que pediste).

### Verificación

`tests/guardrails/test_guardrails_pre_llm.py` (3 tests): redirige un intento en español, permite un mensaje normal, reconoce una variante en inglés.

---

## Cambio transversal: `reglas_core_por_defecto()`

`guardrails/rules.py` — nueva función que centraliza la lista canónica de guardrails de Core (las 3 originales + las 3 nuevas). Antes existían DOS listas hardcodeadas que podían divergir en silencio (`core/orchestrator.py:Orchestrator.__init__` y `core/agent_contract.py:build_orchestrator`) — corregido para que ambas usen la misma fuente (`.claude/rules/fuente-de-verdad.md`), no porque el pedido lo exigiera, sino porque agregar 3 guardrails nuevos en dos lugares por separado habría sido exactamente el tipo de duplicación que esa regla pide evitar.

## Verificación general (los 5 puntos pedidos)

1. ✅ Persistencia real de EventLog tras reinicio de proceso — `tests/observability/test_events_persistencia.py`.
2. ✅ Guardrail de datos inventados bloquea y reemplaza — `tests/guardrails/test_guardrails_pre_llm.py::test_dato_inventado_bloquea_si_menciona_valor_no_permitido` (el `Orchestrator` convierte un BLOCK en el mensaje seguro "No puedo continuar con esa acción todavía: ...", nunca deja pasar el texto original).
3. ✅ Ninguna tool WRITE se ejecuta sin confirmación estructurada — `tests/domains/health/test_confirmacion_estructurada_write.py` + `tests/guardrails/test_guardrails_pre_llm.py`.
4. ✅ Intento de manipulación bloqueado/redirigido — `tests/guardrails/test_guardrails_pre_llm.py::test_redirige_intento_de_manipulacion_ignora_instrucciones`.
5. ✅ Suite completa: **272 passed, 2 skipped** (248 antes de este recado + 24 nuevos). Cero regresiones.

## Archivos tocados

**Core** (agnóstico de dominio): `core/agent_contract.py`, `core/brain.py`, `core/config.py`, `core/orchestrator.py`, `guardrails/__init__.py`, `guardrails/base.py`, `guardrails/rules.py`, `memory/__init__.py`, `memory/conversation_memory.py`, `observability/__init__.py`, `observability/events.py`, `.env.example`.

**`domains/health/`** (solo donde el pedido lo indicaba explícitamente — Parte 3, declarar el flag de confirmación en los 3 puntos ya deterministas): `domains/health/brain.py` — ninguna lógica de negocio nueva, solo el flag agregado a `BrainOutput`s que ya existían.

**Tests nuevos** (7 archivos, 24 tests): `tests/observability/test_events_persistencia.py`, `tests/memory/test_conversation_memory_persistencia.py`, `tests/guardrails/test_guardrails_pre_llm.py`, `tests/domains/health/test_confirmacion_estructurada_write.py`, `tests/core/test_riesgo_independiente_del_brain.py`.

**Tests migrados** (3 archivos, turno adicional de confirmación): `tests/core/test_orchestrator_e2e.py`, `tests/core/test_agent_contract_persistencia.py`, `tests/observability/test_events.py`.

**Documentación**: `.ai/RISKS.md` (R-11 → RESUELTO; R-1 revisado sin cambio de estado; R-25 nueva).

## Pendiente de tu revisión

1. Ningún mensaje nuevo al paciente requiere aprobación de tono (los únicos mensajes nuevos — confirmación del demo Core y redirección de `FueraDeAlcanceGuardrail` — no los ve ningún paciente real de `domains/health/` todavía, ya que no se retroalimentaron a `HealthBrain`).
2. Revisar si quieres que commitee y pushee este trabajo, o si prefieres revisarlo primero.
3. Ver recado 033, actualizado con el resumen de qué de la lista de 5 guardrails quedó resuelto antes de considerar conectar un LLM real.
