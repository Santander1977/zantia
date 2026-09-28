# 033 — PROPUESTO: extraer identidad al Core + ADN heredable para el próximo dominio

**Fecha**: 2026-09-06
**Tipo**: plan a futuro, `[PROPUESTO]` — **nada de esto se implementó en esta sesión**, es solo el registro del plan para retomarlo cuando corresponda. Ningún código se tocó como parte de este recado.
**Contexto**: surge tras cerrar una serie densa de bugs reales de conversación en `domains/health/` (recados 026-032, todos de la misma conversación real de Telegram) — antes de generalizar cualquier pieza de este dominio hacia el Core, conviene dejar que termine de estabilizarse en producción real.

## 1. Cuándo retomarlo

**No ahora.** Explícitamente, mientras `domains/health/` (HealthBrain, el gate de identidad, el adaptador a hrmm-backend) siga recibiendo bugs de conversación nuevos contra tráfico real — como ha sido el caso en cada una de las últimas 7 sesiones consecutivas (recados 026 a 032, todos de la MISMA conversación real de un solo paciente). Generalizar un mecanismo hacia el Core mientras su única implementación real todavía no terminó de estabilizarse arriesga cristalizar en el Protocol del Core los mismos supuestos no confirmados que ya causaron los bugs de esta serie (ver punto 3 — el patrón se repite: se asume algo del sistema externo sin validarlo contra datos reales).

**Criterio de "listo para retomar"** (propuesto, no una regla formal todavía): un período de uso real en producción sin bugs de conversación nuevos relacionados con identidad/catálogo/reserva — no un número de días fijo, sino la ausencia de hallazgos de la clase que motivó estos 7 recados.

**Actualización 2026-09-06 (recado 037)**: el criterio de "listo para retomar" de arriba sigue sin cumplirse (domains/health/ sigue en uso real, sigue siendo la única implementación) — pero la PREPARACIÓN para ese momento ya está más avanzada de lo que estaba cuando se escribió esta sección originalmente. Antes, todo lo relacionado con seguridad/guardrails para un futuro dominio era, en el mejor de los casos, un supuesto razonable sobre lo que el Core ya ofrecía. Hoy, con el trabajo del recado 037 (ver secciones nuevas más abajo), una parte concreta y verificada de lo que necesitaría CUALQUIER dominio nuevo (incluida seguridad ciudadana) — persistencia auditable real, y 3 guardrails de Core agnósticos de dominio — ya existe, ya está probada (272 tests), y ya vive en el Core, no en `domains/health/`. Esto no adelanta el "cuándo" (sigue siendo "no ahora", mismo criterio de arriba), pero sí reduce lo que quedaría por construir el día que se decida retomar.

## 2. Qué hacer

### a) Mover `identity_store.py` al Core, generalizando "documento" → `referencia_externa`

Hoy `domains/health/identity_store.py` (`SQLiteIdentidadCanalStore`, `IdentidadCanal`, `EstadoIdentidadCanal`, `RETENCION_IDENTIDAD_DIAS`) vive enteramente en el dominio salud, con el campo `documento` como concepto central — un identificador de identidad real (cédula/documento del paciente) asociado a un identificador de canal (teléfono/chat_id).

Propuesta: mover este mecanismo completo al Core (`core/` o un nuevo módulo compartido), generalizando `documento` a un campo abstracto — por ejemplo `referencia_externa: str` — que cada dominio interprete a su manera:
- `domains/health/` seguiría poniendo ahí el documento de identidad del paciente.
- Un futuro dominio de ventas podría poner ahí un ID de cliente en un CRM.
- Un futuro dominio de citizen/gobierno podría poner ahí una cédula ciudadana con un formato distinto.

Lo que SÍ es genuinamente genérico y vale la pena preservar tal cual al mover:
- El vencimiento automático a N días (`RETENCION_IDENTIDAD_DIAS`, ya parametrizable).
- El mecanismo de "olvida mi información" (eliminación real a pedido, con confirmación explícita — la lógica de CONFIRMAR antes de borrar es genérica, no específica de salud).
- El patrón de tabla propia con `PRIMARY KEY` en el identificador de canal, separada de `ConversationState` (ver punto c).

### b) Convertir el mecanismo de código de verificación en un Protocol del Core

Hoy `send_verification_code`/`confirm_verification_code` viven como métodos propios de `HrmmAppointmentService` (fuera del Protocol formal `AppointmentService`, ver `domains/health/appointment_service.py`), y `gateway.py` los invoca directamente vía duck-typing/`getattr`. Esto acopla el mecanismo de verificación de identidad a un adaptador de AGENDA — una mezcla de responsabilidades que no se notó como problema mientras solo existía un dominio, pero que sí importaría al construir un segundo dominio con su propio mecanismo de verificación (que podría no tener nada que ver con una agenda).

Propuesta: definir un Protocol del Core, algo como `IdentityVerificationProvider` (nombre tentativo, no decidido), con `send_code(referencia_externa) -> dict` / `confirm_code(referencia_externa, codigo) -> bool` — implementado por cada dominio según su propio canal de entrega (correo, SMS, lo que corresponda), en vez de estar atado a un `AppointmentService` específico.

### c) Revisar si D-6 sigue aplicando

D-6 (decisión documentada en el recado 014/021) es la razón por la que `identity_store` vive SEPARADO de `state/store.py`/`ConversationState`: ciclos de vida distintos (`identity_store` sobrevive a todas las conversaciones de un mismo teléfono, con retención de 180 días; `ConversationState` nace y muere con una Activity/conversación puntual) y claves primarias incompatibles (`telefono` vs. `conversation_id`).

Al mover `identity_store` al Core, esa razón de fondo (ciclo de vida y clave primaria distintos) **no cambia** — sigue siendo válida independientemente de en qué capa viva el código. Lo que SÍ habría que revisar en ese momento: si el Core pasa a tener DOS stores SQLite propios (`state/store.py` + el nuevo store de identidad genérico), ¿vale la pena unificar la infraestructura de conexión/mkdir (ambos ya hacen lo mismo, ver recado 029) en un helper común del Core? Es una pregunta de higiene de código, no una revisión de la decisión de fondo de D-6.

## 3. Patrones de conversación real a anticipar en el próximo Brain

Encontrados los 7, todos con evidencia real de producción — no una lista teórica. La lección explícita: el próximo Brain de dominio (o una capa común del Core, si se decide extraer parte de esto) debería nacer YA considerando estos patrones, en vez de descubrirlos uno por uno contra tráfico real como pasó con `HealthBrain`:

1. **Respuestas de sí/no sin tilde, con puntuación variable, o dentro de frases largas** — "Si claro ayúdame puedes orientarme mejor" debe reconocerse como afirmativo. Un chequeo por límite de palabra sobre texto sin tildes (no un catálogo de frases con coma/espacios exactos) es el patrón que terminó funcionando (recado 030) — considerar si esto merece ser una utilidad genérica del Core en vez de reconstruirse por dominio.
2. **Saludos o cambios de tema a mitad de conversación** — deben poder reconocerse y reorientar la conversación SIN perder la identidad ya verificada (la identidad vive en un store separado del `ConversationState`, así que esto ya es estructuralmente posible — falta que el Brain lo reconozca explícitamente en vez de tratar cualquier mensaje no reconocido como si fuera intento de responder la pregunta pendiente).
3. **Preguntas de catálogo sin nombrar una opción específica** — deben responderse con el catálogo REAL (nunca inventado) y dejar la conversación en un estado que reconozca la respuesta siguiente como una elección, no como un mensaje nuevo sin relación (recados 027/031 — el bug concreto fue no dejar ningún estado rastreable tras listar el catálogo).
4. **Confirmaciones de acciones que toman tiempo ("dame un momento")** deben resolverse con un resultado real en el MISMO turno o en un mecanismo de seguimiento explícito — nunca quedar como una promesa que ningún mensaje siguiente reporta (recado 032: la reserva se completaba de verdad contra el sistema externo, pero el chequeo de éxito nunca lo reconocía).
5. **Nunca asumir el mapeo completo de estados de un sistema externo sin validarlo contra datos reales** antes de confiar en él para lógica crítica (recado 032 — `_MAPA_ESTADO_HRMM` fue la causa raíz directa del punto 4: un valor real ("agendada") nunca contemplado, por ser inferencia no confirmada, dejaba invisible una reserva real exitosa). Antes de dar por buena la integración con el sistema externo del próximo dominio, ejercitar el escenario real completo (con autorización explícita) y capturar el vocabulario real de sus campos de estado — no asumirlo de la documentación o de nombres "razonables".

## 4. Qué NO se hereda — se reconstruye para cada dominio nuevo

Explícito, para no perder tiempo intentando generalizar de más:

- El **adaptador de agenda/servicio real** (equivalente a `HrmmAppointmentService`) — específico del sistema externo de cada negocio, sin nada genérico que extraer más allá del `Protocol AppointmentService` que ya existe.
- El **catálogo de negocio específico** (`CatalogMirror`, servicios/médicos) — específico del dominio salud; un dominio de ventas no tiene "servicios y médicos", tendría su propio catálogo con su propia forma.
- El **Brain del dominio** (`HealthBrain`) — la máquina de etapas, las frases reconocidas, las reglas de negocio son propias de cada dominio. Lo que SÍ se anticipa (punto 3) son los PATRONES DE FALLO ya conocidos, no el Brain en sí.

## Alcance de este recado

Ninguno de los puntos de arriba se implementó — es un registro de plan para retomar cuando el usuario decida que corresponde. No se tocó ningún archivo de código en esta sesión como parte de este pedido.

---

## Actualización 2026-09-06 (recado 037) — guardrails pre-LLM: qué quedó resuelto antes de dar el salto a un Brain basado en LLM

Este recado (033) sigue siendo, en su origen, sobre un tema DISTINTO (extraer identidad al Core) — pero el usuario pidió explícitamente registrar aquí qué guardrails de seguridad ya quedan resueltos antes de considerar conectar un LLM real a la conversación, ya que ambos temas son precondiciones para el mismo destino ("el próximo salto" del proyecto). Ver recado 037 para el detalle completo.

**Resuelto (implementado y probado, 272/272 tests, cero regresiones)**:
1. Persistencia real de `EventLog`/`ConversationMemory` (R-11) — sin esto, ningún LLM podría auditarse tras un reinicio.
2. `DatoInventadoGuardrail` — mecanismo agnóstico de dominio listo, aunque `domains/health/` todavía no lo usa (Brain determinista no lo necesita hoy).
3. `ConfirmacionEstructuradaRequeridaParaWriteGuardrail` — ninguna tool WRITE se ejecuta sin una confirmación determinista declarada explícitamente por el Brain; corregido un hueco real en `FakeBrain` (Core) que ejecutaba sin ningún paso de confirmación.
4. `FueraDeAlcanceGuardrail` — resistencia a manipulación tipo "ignora tus instrucciones", listo aunque redundante con el Brain determinista de hoy.
5. Corrección de robustez real (no pedida explícitamente, encontrada al diseñar la Parte 4 del pedido): la detección de riesgo ahora se calcula ANTES de invocar al Brain, y un fallo del Brain (posible con un LLM real, nunca con el determinista de hoy) escala en vez de crashear.

**Sigue PENDIENTE, explícitamente fuera de alcance de cualquier sesión de código**:
- R-1: el criterio clínico/legal real de qué constituye una urgencia — ninguna arquitectura de software sustituye esa validación. Los guardrails de arriba preparan el mecanismo, nunca deciden el contenido.
- R-13: `AnthropicBrain` nunca se probó en vivo — sigue sin conectar ningún LLM real a ninguna conversación.
- El plan de este recado (033, extraer identidad al Core) — sigue sin retomarse, mismo criterio "no ahora" de la sección 1 de arriba.

**Conclusión**: la infraestructura de seguridad de Core (persistencia auditable + 3 guardrails nuevos + orden de riesgo robusto) ya no es un bloqueante para dar el salto a un LLM real — lo que sigue bloqueando ese salto es (a) la validación clínica/legal del criterio de riesgo (decisión humana, no de código) y (b) la decisión explícita del usuario de cuándo y con qué alcance conectar un Brain basado en LLM al dominio salud.

---

## Actualización 2026-09-06 (parte 2) — los guardrails del recado 037 como ADN heredable confirmado

Lo de arriba (Actualización recado 037) registraba el trabajo como precondición para un LLM en `domains/health/`. Esta sección lo reencuadra explícitamente en términos del ADN heredable de este recado (033): no es solo una intención de diseño — es trabajo real, ya construido y verificado, que el PRÓXIMO dominio (seguridad ciudadana / evolución de TuRed123) puede reutilizar directamente, sin reescribir nada del mecanismo.

### Guardrails del Core ya heredables (confirmado, recado 037)

- **Persistencia real de `EventLog`/`ConversationMemory`** (`ZANTIA_EVENTS_DB_PATH`/`ZANTIA_MEMORY_DB_PATH`) — 100% agnóstico de dominio, vive en `core/agent_contract.py:build_orchestrator`. Un dominio nuevo lo hereda automáticamente por el simple hecho de usar `build_orchestrator` (mismo patrón ya confirmado con `domains/health/`, que nunca tuvo que tocar un solo archivo para heredar la persistencia de `ConversationState` en el recado 021, ni la de `EventLog`/`ConversationMemory` en el 037). Para seguridad ciudadana, esto es la diferencia entre poder auditar después "qué dijo el sistema sobre un caso real" o perder esa traza en cualquier reinicio.
- **`DatoInventadoGuardrail`** — verifica texto libre contra los datos reales confirmados en el turno, sin que el Core sepa qué es una "cita" ni un "caso". Para seguridad ciudadana, el mismo mecanismo (patrón + lista de valores permitidos, declarado por el Brain de ese dominio) aplicaría a no inventar un número de caso, una unidad de despacho asignada, o cualquier dato que el sistema originador (ej. el CAD/despacho real) no haya confirmado — exactamente el mismo riesgo de alucinación que en salud, con un costo de error mucho más alto si el dominio es de emergencias.
- **`ConfirmacionEstructuradaRequeridaParaWriteGuardrail`** — el principio de fondo ("ninguna acción WRITE se ejecuta sin que el Brain declare una confirmación determinista verificable por código") no tiene nada de específico de salud. Aplica exactamente igual a **crear un caso de emergencia** o **escalar a una entidad real** (GAULA, Policía, Bomberos) que a reservar una cita médica — en ambos casos, la garantía que importa es la misma: nunca ejecutar una escritura real sobre la base de que "el LLM pareció entender que había que actuar".
- **`FueraDeAlcanceGuardrail`** — protección contra manipulación del LLM (mensajes tipo "ignora tus instrucciones anteriores"), independiente de dominio por diseño (revisa el mensaje entrante, nunca vocabulario de negocio). Se hereda sin cambios.
- **Reordenamiento de la detección de riesgo ANTES de invocar al Brain, con el Brain envuelto en try/except** — este es, de los 5, el hallazgo MÁS directamente relevante para seguridad ciudadana, y ya está resuelto en el Core, no como algo que ese dominio tendría que descubrir por su cuenta (como pasó, por analogía, con varios de los bugs reales de `domains/health/` que motivaron este mismo recado 033, sección 3). Garantiza que un Brain fallido (timeout de red, error de API — exactamente los modos de falla reales de cualquier LLM en producción) **nunca silencie una señal de riesgo real** — en un dominio de seguridad ciudadana, donde un mensaje de riesgo podría literalmente ser "me están secuestrando", esto no es una mejora de robustez opcional: es un requisito CRÍTICO, y ya está resuelto.

### Lo que NO se hereda automáticamente — específico de cada dominio

Mismo criterio de honestidad que la sección 4 original de este recado (arriba): el MECANISMO se hereda, el CONTENIDO específico de cada dominio, no.

- **El contenido del criterio de riesgo** — `RISK_KEYWORDS_DEMO` (`core/brain.py`) es deliberadamente genérico y NO clínico/legal (4 palabras de ejemplo: "urgente", "emergencia", "ayuda inmediata", "muy grave"), y sigue así — `domains/health/` nunca lo extendió (confirmado con grep en el recado 037, ver R-1 en `.ai/RISKS.md`). Un dominio de seguridad ciudadana necesitaría su PROPIA lista real de palabras/frases de riesgo — ya documentadas en el proyecto TuRed123 (ej. "me dispararon", "no puedo respirar", "me están siguiendo", "secuestro", "incendio", "arma") — aplicada sobre el MISMO mecanismo ya construido en el Core (`detect_risk_keywords`, o su evolución hacia un vocabulario configurable por dominio, ver la Parte 4 `[PROPUESTO]` del recado 037). Esa lista, igual que en salud, requeriría su propia validación por quien tenga la autoridad para decidirla (en este caso, probablemente más cercana a protocolos reales de líneas de emergencia que a un criterio "clínico" — de cualquier forma, una decisión humana, nunca de software).
- **El criterio de qué cuenta como "confirmación estructurada" para una acción WRITE de este dominio** — el MECANISMO (`ConfirmacionEstructuradaRequeridaParaWriteGuardrail`, el guardrail en sí) se hereda; qué EXACTAMENTE constituye una confirmación válida para "crear un caso" o "escalar a GAULA" (¿un ordinal elegido? ¿una palabra de confirmación? ¿algo más estricto, dado el dominio?) es una decisión de diseño propia de ese dominio, no heredada.
- **Las `VerificacionDeDatos` concretas** que un Brain de seguridad ciudadana declararía para `DatoInventadoGuardrail` (qué patrones, qué categorías) — el guardrail se hereda vacío por default (ALLOW sin declaración, ver recado 037); poblarlo con las categorías reales de ese dominio es trabajo nuevo.
- Todo lo que la sección 4 original de este recado ya identificaba como no heredable (el adaptador de agenda/servicio real, el catálogo de negocio específico, el Brain del dominio en sí) — sin cambios, sigue aplicando igual.

**Conclusión de esta actualización**: el ADN heredable de "guardrails pre-LLM" ya no es una intención — es un conjunto concreto de mecanismos, en el Core, probados con 272 tests, que un dominio de seguridad ciudadana podría empezar a usar el mismo día que se decida construirlo, sin reconstruir nada de lo ya resuelto. Lo que ese dominio SÍ tendría que aportar es exclusivamente CONTENIDO (vocabulario de riesgo real, categorías de datos verificables, criterio de confirmación) — nunca el mecanismo en sí.
