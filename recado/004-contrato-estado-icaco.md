# RECADO PARA CHATGPT

Fecha: 2026-08-31
Proyecto: icaco (agente conversacional de Orangutan, dominio inicial: salud)
Tema: Especificación técnica preliminar del "Contrato de Estado Conversacional ICACO v1" — Fase 3 de diseño, a partir de la sección 6 de `003-arquitectura-cerebro-icaco.md`.
Objetivo: Pasar de arquitectura conceptual a especificación técnica preliminar del objeto `ConversationState` (modelo formal, máquina de estados, autoridad de escritura, contratos entre componentes) — sin implementar, sin elegir stack, sin crear tablas reales.

Este documento es autocontenido. Se apoya en dos documentos previos, ya publicados en esta misma carpeta:
- `/Users/enzoalfonso/recado/002-autopsia-cerebro-dani.md` — autopsia técnica de Dani (fuente de patrones y de las lecciones que este contrato corrige).
- `/Users/enzoalfonso/recado/003-arquitectura-cerebro-icaco.md` — arquitectura conceptual de ICACO (fuente directa de esta fase, especialmente su sección 6 "Estado conversacional").

Convenciones de esta fase: **HECHO** = verificado leyendo los documentos anteriores. **INFERENCIA** = conclusión razonada a partir de ese contenido, no literal. **RECOMENDACIÓN** = decisión de diseño propuesta en este documento. **PENDIENTE** = requiere una decisión humana (de producto, legal, clínica o de stack) que este documento no toma.

---

# CONTRATO DE ESTADO CONVERSACIONAL ICACO v1

## 1. Objetivo

RECOMENDACIÓN de encuadre: esta fase formaliza el componente ESTADO descrito conceptualmente en `003-arquitectura-cerebro-icaco.md` (sección 6) como un contrato técnico preliminar: qué campos tiene, quién puede tocarlos, cómo transiciona, cómo se protege contra duplicación/concurrencia, y qué frontera exacta existe entre el Cerebro (LLM), el Orquestador, los Guardrails y las Tools. Sigue siendo diseño puro — ningún campo de este documento se traduce a una tabla real, ninguna tecnología se elige.

---

## 2. Modelo formal del estado

### 2.1 Evaluación campo por campo de lo propuesto en 003

HECHO: `003-arquitectura-cerebro-icaco.md` (sección 6) propuso 17 campos. Este documento no los da por definitivos — se evaluó cada uno, con estos resultados:

| Campo original (003) | Evaluación | Decisión |
|---|---|---|
| `fase_actual` | Correcto, esencial | Se conserva |
| `intención` | Correcto, esencial | Se conserva |
| `objetivo_de_conversación` | Correcto — distinto de `intención` (uno es por turno, el otro persiste durante toda la conversación aunque haya desvíos) | Se conserva |
| `modo` | Correcto, esencial | Se conserva |
| `contexto` | **Problemático**: tal como estaba definido en 003, es texto narrativo libre — duplica lo que la sección 3 de este documento define como capa "RESUMEN" | **Se reemplaza** por `resumen_ref`: un puntero a la versión vigente del resumen (que vive en la capa RESUMEN, no en el estado), nunca el texto en sí |
| `datos_recopilados` | Correcto, esencial | Se conserva |
| `datos_faltantes` | **Problemático**: si se almacena como campo independiente, puede desincronizarse de `datos_recopilados` | **Se redefine como derivado**: se calcula en cada turno comparando `objetivo_de_conversación` (y su esquema de datos requeridos, PENDIENTE de definir por caso de uso) contra `datos_recopilados`. No se persiste como fuente primaria |
| `herramientas_utilizadas` | Correcto, esencial para idempotencia y auditoría | Se conserva |
| `resultado_de_herramientas` | **Ajustado**: se acota a "último resultado relevante por tool", no un historial completo (el historial vive en auditoría, sección 13) | Se conserva, acotado |
| `próxima_acción` | Correcto, pero es un campo **transitorio** (vigente solo durante el turno en curso, se sobreescribe cada vez, no se acumula) | Se conserva, con esa aclaración |
| `nivel_de_confianza` | Correcto, pero se aclara que es el **último valor conocido** de la interpretación más reciente, no una métrica acumulada | Se conserva, acotado |
| `necesidad_de_escalar` | Correcto, esencial | Se conserva, ahora explícitamente con motivo estructurado |
| `nivel_de_riesgo` | **Ambiguo en 003**: aparecía casi fusionado con `señal_de_urgencia` | **Se separa**: `nivel_de_riesgo` es una evaluación continua/gradual (ej. bajo/medio/alto); ver 2.3 |
| `señal_de_urgencia` | Igual que arriba | **Se separa**: `señal_de_urgencia` es un booleano que dispara `ESCALADO_URGENTE` de inmediato — es un disparador, no un nivel |
| `consentimiento_datos` | Correcto, esencial | Se conserva |
| `canal` | Correcto, esencial (aunque el canal exacto sigue PENDIENTE, el campo debe existir independientemente de cuál sea) | Se conserva |
| `última_actualización` | Correcto | Se conserva, y se agregan campos hermanos en 2.4 (versión, origen del cambio) que 003 no contemplaba |

RECOMENDACIÓN: además de estos, se agregan 4 campos que 003 no incluía, necesarios para las secciones 9-12 de este documento (idempotencia, concurrencia, versionado):
- `conversation_id` — identificador único de la conversación. Sorprendentemente ausente como campo explícito en 003 (estaba implícito en el `sessionKey` de la capa de memoria, pero el ESTADO necesita su propia clave primaria conceptual).
- `version` — número de revisión del estado, para concurrencia optimista.
- `origen_del_último_cambio` — qué actor escribió la última actualización (LLM-propuesta-aprobada / orquestador-regla / guardrail-corrección / tool-resultado).
- `último_mensaje_id_procesado` — para deduplicación de mensajes entrantes.

### 2.2 Modelo formal — grupos de campos

Para legibilidad, el objeto conceptual `ConversationState` se organiza en 4 grupos. Ningún grupo implica una tabla física distinta — es solo organización conceptual.

**Grupo A — Identidad y control técnico**

| Campo | Propósito | Tipo conceptual | Oblig. | Valor inicial | Escribe | Lee | Modifica | Validación | Sensibilidad | Persistir | Auditar |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `conversation_id` | Clave de la conversación | identificador | Sí | generado al INICIO | Orquestador | Todos | Nunca (inmutable) | Único | Operacional | Sí | Sí (creación) |
| `canal` | Por dónde llegó | enumeración | Sí | valor del canal entrante | Orquestador | Todos | Nunca tras creación | Valor de canal soportado (PENDIENTE definir lista, sec. 22) | Operacional | Sí | No |
| `version` | Revisión del estado | entero incremental | Sí | 0 | Orquestador (auto al escribir) | Orquestador | Orquestador | Debe incrementar en cada escritura | Operacional | Sí | No (implícito en historial) |
| `origen_del_último_cambio` | Trazabilidad de la última escritura | enumeración | Sí | "creación" | Orquestador | Orquestador/auditoría | Orquestador | Debe ser uno de los actores definidos en sec. 8 | Operacional/auditoría | Sí | Sí |
| `última_actualización` | Timestamp de la última escritura | fecha-hora | Sí | timestamp de creación | Orquestador (auto) | Todos | Orquestador | — | Operacional | Sí | No |
| `último_mensaje_id_procesado` | Deduplicación de entrada | identificador | No (hasta que llegue el primer mensaje) | vacío | Orquestador | Orquestador | Orquestador | Debe ser monótono/único por canal | Operacional | Sí | No |

**Grupo B — Núcleo conversacional**

| Campo | Propósito | Tipo conceptual | Oblig. | Valor inicial | Escribe | Lee | Modifica | Validación | Sensibilidad | Persistir | Auditar |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `fase_actual` | Punto de la máquina de estados (sec. 6) | enumeración cerrada | Sí | `INICIO` | Orquestador (según propuesta del Cerebro) | Todos | Orquestador | Solo transiciones válidas (sec. 9) | Operacional | Sí | Sí (todo cambio) |
| `intención` | Qué quiere el usuario en el turno actual | texto clasificado | No hasta IDENTIFICACIÓN | vacío | Orquestador (propuesta del Cerebro) | Cerebro, Orquestador | Orquestador | Debe pertenecer a un catálogo de intenciones soportadas (PENDIENTE por caso de uso) | Personal (puede reflejar motivo de consulta) | Sí | No (salvo cambios relevantes a riesgo) |
| `objetivo_de_conversación` | Meta general de la interacción | texto clasificado | No hasta que se fija | vacío | Orquestador | Cerebro, Orquestador | Orquestador (rara vez, solo si el usuario cambia de objetivo explícitamente) | Igual que intención | Personal | Sí | No |
| `modo` | Régimen de comportamiento activo | enumeración | Sí | `atención_general` | Orquestador (regla determinista) | Cerebro, Orquestador | Orquestador | Transición determinista, no libre | Operacional | Sí | Sí (todo cambio) |
| `resumen_ref` | Puntero a la versión vigente del resumen (capa RESUMEN, sec. 3) | referencia | No | vacío | Orquestador | Cerebro, Orquestador | Orquestador | Debe apuntar a un resumen existente | Personal (indirectamente) | Sí | No |
| `próxima_acción` | Qué se planea hacer en el siguiente ciclo (transitorio) | texto clasificado | No | vacío | Orquestador (propuesta del Cerebro, validada) | Orquestador, Guardrails | Orquestador | Debe ser una acción del catálogo permitido en `fase_actual` | Operacional | Sí (se sobreescribe cada turno) | No |
| `nivel_de_confianza` | Confianza de la última interpretación | escala (ej. bajo/medio/alto) | No | vacío | Orquestador (reportado por el Cerebro) | Orquestador, Guardrails | Orquestador | — | Operacional | Sí (último valor) | No |

**Grupo C — Datos del objetivo**

| Campo | Propósito | Tipo conceptual | Oblig. | Valor inicial | Escribe | Lee | Modifica | Validación | Sensibilidad | Persistir | Auditar |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `datos_recopilados` | Información obtenida del usuario relevante al objetivo | estructura clave-valor | No | vacío | Orquestador (extracción del Cerebro, validada) | Cerebro, Orquestador, Tools (lectura) | Orquestador | Cada clave según su propio esquema (PENDIENTE por caso de uso) | **Personal / potencialmente sensible** (puede incluir datos de salud) | Sí | Sí (toda escritura, por ser dato personal) |
| `datos_faltantes` | Qué falta para completar el objetivo | **derivado**, no almacenado como fuente primaria | — | — | Calculado por el Orquestador en cada turno | Cerebro, Orquestador | — (no se escribe directo) | — | Deriva la sensibilidad de `datos_recopilados` | No (se recalcula) | No |
| `herramientas_utilizadas` | Qué tools se invocaron y con qué resultado resumido | lista estructurada | No | vacío | Orquestador | Cerebro, Orquestador | Orquestador (solo agrega, no edita entradas pasadas) | — | Operacional (salvo que el resumen incluya dato personal) | Sí | Sí |
| `resultado_de_herramientas` | Último resultado relevante, por tool | estructura clave-valor (clave = tool) | No | vacío | Orquestador | Cerebro, Orquestador | Orquestador (sobreescribe por tool) | — | Depende de la tool | Sí (solo el último) | No (el histórico vive en auditoría) |

**Grupo D — Riesgo y cumplimiento**

| Campo | Propósito | Tipo conceptual | Oblig. | Valor inicial | Escribe | Lee | Modifica | Validación | Sensibilidad | Persistir | Auditar |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `nivel_de_riesgo` | Evaluación gradual de riesgo | escala (ej. bajo/medio/alto) | Sí (desde el inicio, valor por defecto) | `bajo` | **Guardrails/reglas deterministas** (el Cerebro solo aporta señal) | Todos | Guardrails | Solo puede subir por regla determinista; bajar requiere regla explícita, nunca "olvido" | **Sensible** | Sí | **Sí, siempre** |
| `señal_de_urgencia` | Disparador booleano de interrupción global | booleano | Sí | `false` | **Guardrails/reglas deterministas** (nunca el Cerebro directo) | Todos | Guardrails | Una vez `true`, solo un actor humano/regla explícita puede volverla a `false` — nunca automáticamente por salir de la ventana de contexto (lección directa de Dani) | **Sensible** | Sí | **Sí, siempre, máxima prioridad** |
| `necesidad_de_escalar` | Bandera + motivo | booleano + texto estructurado | Sí | `false` / vacío | Orquestador (propuesta del Cerebro o regla determinista) | Todos | Orquestador, Guardrails | El motivo es obligatorio si el valor es `true` | Personal/operacional | Sí | Sí |
| `consentimiento_datos` | Si el usuario fue informado/aceptó el tratamiento de sus datos | booleano + timestamp | Sí | `false` | Orquestador, tras confirmación explícita del usuario | Todos | Orquestador (solo hacia `true`, nunca se revoca "por defecto" — una revocación explícita es su propio evento auditado) | — | **Sensible por definición** (es en sí mismo un dato de cumplimiento) | Sí | **Sí, siempre** |

**Regla transversal de esta sección**: los campos del Grupo D nunca los escribe el Cerebro directamente — siempre pasan por Guardrails o por una regla determinista del Orquestador (ver sección 8, matriz de autoridad).

### 2.3 Aclaración `nivel_de_riesgo` vs. `señal_de_urgencia`

RECOMENDACIÓN (corrección respecto a 003, donde ambos aparecían casi fusionados): `nivel_de_riesgo` es una evaluación continua que puede subir sin necesariamente disparar una interrupción (ej. "medio" podría ajustar el tono o la prioridad de una pregunta, sin escalar todavía). `señal_de_urgencia` es un booleano que, al activarse, dispara sin condiciones la transición a `ESCALADO_URGENTE` (sección 6-7). El contenido exacto de qué patrones elevan uno u otro sigue **PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL** (heredado de `003`, sección 19) — aquí solo se define el lugar arquitectónico y la relación entre ambos campos, no el criterio médico.

---

## 3. Estado vs. memoria

RECOMENDACIÓN central de esta sección, respondiendo directamente a la instrucción de evitar que la misma información viva en cinco lugares:

| Capa | Qué vive ahí | Alcance temporal | Es fuente de decisión de flujo? |
|---|---|---|---|
| **A. ESTADO** (`ConversationState`, sección 2) | Datos operativos estructurados: fase, intención, objetivo, modo, datos recopilados, riesgo, consentimiento | Por conversación (`conversation_id`) | **Sí — es la única fuente de verdad para decisiones de flujo** |
| **B. MEMORIA DE CONVERSACIÓN** | Turnos crudos recientes (texto), ventana corta — mismo patrón que Dani (Postgres/`sessionKey`) | Por conversación, ventana acotada | No — es insumo de redacción para que el Cerebro hable con continuidad natural, nunca se consulta para decidir una transición de estado |
| **C. MEMORIA DEL USUARIO/CIUDADANO** | Perfil persistente: datos de contacto, interacciones previas relevantes, preferencias | Entre conversaciones distintas del mismo usuario | No decide el flujo de la conversación actual, pero puede informar al Cerebro (ej. "ya atendido antes por X motivo") |
| **D. RESUMEN** | Texto narrativo curado de la conversación actual, regenerado periódicamente por el Cerebro | Por conversación, se referencia desde `estado.resumen_ref` | No — es insumo de redacción, igual que B, nunca fuente de una transición |
| **E. CONOCIMIENTO** | Estático / dinámico / RAG / externo (sección 9 de `003`) | No cambia por la conversación — se consulta, no se escribe desde ella | No decide el flujo; informa el contenido de la respuesta |

**Regla que evita la duplicación en 5 lugares**: ningún dato que ya vive en el ESTADO (grupo A/B/C/D de la sección 2) debe reescribirse dentro del texto del RESUMEN como si fuera la fuente — el resumen puede *mencionar* en prosa lo que el estado ya tiene estructurado (para que el Cerebro redacte con naturalidad), pero el estado nunca se reconstruye leyendo el resumen. Es la inversión exacta de cómo funcionaba Dani, donde el LLM releía el historial crudo (equivalente a B) para inferir todo lo que en ICACO ahora vive en A.

---

## 4. Estado mínimo

RECOMENDACIÓN — campos necesarios para operar una conversación básica de un solo objetivo (ej. agendar una cita), sin las capas de madurez completas:

- `conversation_id`, `canal` (identidad mínima)
- `fase_actual`, `intención`, `objetivo_de_conversación`, `modo` (núcleo conversacional mínimo)
- `datos_recopilados` (sin necesidad de `resumen_ref` todavía — con volumen bajo, la memoria de conversación cruda alcanza)
- `necesidad_de_escalar` (+ motivo)
- `señal_de_urgencia` — **no se puede omitir ni en el estado mínimo**; ver justificación abajo
- `consentimiento_datos`
- `version`, `última_actualización` (housekeeping barato de incluir desde el día uno, evita reabrir el contrato pronto)

**Por qué `señal_de_urgencia` no es negociable ni en el MVP** (RECOMENDACIÓN explícita, no una conveniencia): omitirla del estado mínimo violaría el principio 11 de `003-arquitectura-cerebro-icaco.md` ("la señal de riesgo/urgencia se evalúa con reglas deterministas... nunca depende solo de que el LLM la reconozca"). No es una funcionalidad que se pueda posponer a una "fase 2" de madurez — es, junto con `consentimiento_datos`, la única distinción de dominio que separa a ICACO de un clon de Dani.

**Campos que sí pueden diferirse a estado completo**: `resumen_ref` (el MVP puede operar solo con memoria de conversación cruda si el volumen de turnos es bajo), `nivel_de_confianza` persistido formalmente, `nivel_de_riesgo` como escala gradual (el MVP puede operar solo con el booleano `señal_de_urgencia`, sin gradiente), `próxima_acción` explícito como campo separado (el MVP puede dejar que el Orquestador decida directo, sin modelar tan formalmente "propuesta vs. decisión"), `datos_faltantes` (siempre derivado, nunca se persiste, aplica igual en MVP y en completo), `herramientas_utilizadas`/`resultado_de_herramientas` detallados (el MVP puede llevar solo "última tool invocada", no un registro completo por tool), `origen_del_último_cambio` y el mecanismo formal de concurrencia optimista por versión (el MVP puede operar con un modelo de concurrencia más simple, sección 11).

---

## 5. Estado completo

RECOMENDACIÓN — arquitectura madura: todos los campos de la sección 2 (grupos A-D completos), incluyendo `resumen_ref` activo con regeneración periódica, `nivel_de_riesgo` como escala gradual (no solo el booleano), `nivel_de_confianza` persistido y disponible para reglas de negocio (ej. pedir confirmación explícita si la confianza es baja antes de ejecutar una acción), `herramientas_utilizadas`/`resultado_de_herramientas` completos por tool, mecanismo formal de `version`/concurrencia optimista, y enlace explícito hacia la capa C (memoria del usuario/ciudadano) para dar continuidad entre conversaciones distintas del mismo usuario.

---

## 6. Máquina de estados

RECOMENDACIÓN, formalizando la máquina conceptual de `003` (sección 12), sin darla por definitiva — se evaluó cada estado propuesto:

**Estados no terminales** (pueden tener duración de varios turnos):
- `INICIO` — existe solo hasta el primer mensaje procesado.
- `IDENTIFICACIÓN_DE_INTENCIÓN`
- `RECOPILACIÓN_DE_DATOS`
- `RAZONAMIENTO_DECISIÓN` — **evaluación**: a diferencia de los demás, este estado normalmente es transitorio dentro de un mismo turno (entra y sale sin esperar respuesta del usuario). Se conserva como estado explícito por valor de auditoría ("el sistema razonó y decidió X"), no porque típicamente persista entre turnos.
- `ACCIÓN`
- `RESPUESTA`
- `MANEJO_DE_DUDA`
- `PAUSA_POR_DATOS_FALTANTES`
- `SEGUIMIENTO` — semi-terminal: el objetivo ya se cumplió, pero la conversación puede continuar con un objetivo nuevo.

**Estados terminales** (para el flujo automatizado):
- `CIERRE`
- `ESCALADO_URGENTE`
- `ESCALADO_ESTÁNDAR`
- `ABANDONADA` — **propuesta nueva, no estaba en `003`**. Justificación: `003` no contemplaba qué pasa si el usuario simplemente deja de responder. Es un desenlace real y frecuente que necesita su propio estado terminal para efectos de limpieza/observabilidad — sin él, una conversación inconclusa quedaría indefinidamente en un estado no terminal, distorsionando cualquier métrica de tasa de cierre/escalamiento.

**Interrupciones globales** (desde cualquier estado no terminal, sin excepción):
- `señal_de_urgencia = true` → `ESCALADO_URGENTE`
- Solicitud explícita de humano, o incapacidad del agente tras agotar reintentos → `ESCALADO_ESTÁNDAR`
- Inactividad del usuario por encima de un umbral (umbral exacto **PENDIENTE DE DECISIÓN DE STACK/PRODUCTO**) → `ABANDONADA`

---

## 7. Prioridades

RECOMENDACIÓN de jerarquía, derivada del principio 11 de `003` (protección antes que fluidez) — no se adopta automáticamente el orden de ejemplo del encargo, se justifica cada nivel:

```
1. señal_de_urgencia (riesgo activo)        ← máxima prioridad, determinista, sin excepción
2. Solicitud explícita de escalamiento humano (ESCALADO_ESTÁNDAR)
3. Dato crítico faltante que bloquea cualquier acción (PAUSA_POR_DATOS_FALTANTES)
4. Ejecutar la acción/tool disponible hacia el objetivo en curso
5. Continuar la conversación normal hacia el objetivo
```

**Por qué este orden y no otro**:
- (1) sobre (2): una urgencia se atiende aunque el usuario NO la haya pedido explícitamente — pedir ayuda a un humano es una preferencia, una urgencia es un hecho que no depende de que el usuario sepa nombrarlo.
- (2) sobre (3) y (4): si el usuario ya pidió hablar con una persona, seguir intentando resolver automáticamente (aunque haya un dato faltante fácil de pedir, o una tool lista para usarse) iría en contra de lo que el usuario pidió.
- (3) sobre (4): ejecutar una tool sin el dato que necesita produciría un resultado inválido o una acción incorrecta (ej. agendar sin saber el motivo) — no tiene sentido intentarlo.

**Resolución del escenario planteado** (simultáneamente: pide cita + señal de riesgo + tool disponible + dato faltante + pide hablar con persona): **gana la señal de riesgo**. El sistema interrumpe todo lo demás de inmediato — no agenda, no pregunta el dato faltante, no resuelve la solicitud de hablar con alguien por el canal estándar — y dispara `ESCALADO_URGENTE`. Las demás intenciones (agendar, dato faltante, pedido de humano) quedan registradas en `estado.datos_recopilados`/auditoría para retomarse **solo si un humano lo autoriza después** — nunca se reanudan automáticamente (transición inválida explícita, sección 9).

---

## 8. Autoridad sobre el estado

RECOMENDACIÓN — matriz de quién puede hacer qué:

| Actor | Propone | Valida | Escribe el estado | Modifica campos críticos (Grupo D) | Ejecuta | Bloquea |
|---|---|---|---|---|---|---|
| **LLM (Cerebro)** | ✅ (intención, próxima_acción, propuesta de actualización) | ❌ | ❌ nunca directo | ❌ nunca | ❌ | ❌ |
| **Orquestador** | — | ✅ (valida propuesta contra reglas) | ✅ **único escritor real** | ✅ (solo tras aprobación de Guardrails) | ✅ (coordina el flujo) | Puede rechazar una propuesta, pero el bloqueo "duro" es de Guardrails |
| **Guardrails** | — | ✅ (verifica cumplimiento de reglas críticas) | ❌ | ❌ (no escribe, solo aprueba/rechaza) | ❌ | ✅ (puede bloquear antes de que el Orquestador aplique el cambio) |
| **Tools** | — | — | ❌ nunca escriben el estado directo | ❌ | ✅ (ejecutan su función, devuelven resultado) | ❌ |
| **Base de datos** | — | — | ✅ (persiste lo que el Orquestador le entrega) | — | — | ❌ |

**Principio central**: el LLM **siempre propone, nunca escribe**. El Orquestador es el único punto de escritura real. Para los campos del Grupo D (riesgo, urgencia, escalamiento, consentimiento) y para cualquier resultado de una tool de categoría WRITE (sección 17), la escritura del Orquestador requiere aprobación previa de Guardrails — no es opcional ni configurable caso por caso.

---

## 9. Transiciones

RECOMENDACIÓN — matriz de transiciones principales (no exhaustiva, cubre los casos estructurales):

| Estado actual | Evento | Condición | Estado siguiente | Quién decide |
|---|---|---|---|---|
| `INICIO` | Primer mensaje recibido | Siempre | `IDENTIFICACIÓN_DE_INTENCIÓN` | Orquestador |
| `IDENTIFICACIÓN_DE_INTENCIÓN` | Intención clasificada | Confianza suficiente | `RECOPILACIÓN_DE_DATOS` | Orquestador (según propuesta del Cerebro) |
| `IDENTIFICACIÓN_DE_INTENCIÓN` | Intención ambigua | Confianza baja | `IDENTIFICACIÓN_DE_INTENCIÓN` (reintento, pregunta aclaratoria) | Orquestador |
| `RECOPILACIÓN_DE_DATOS` | Dato recopilado, faltan más | `datos_faltantes` ≠ vacío | `RECOPILACIÓN_DE_DATOS` (ciclo válido, con contador) | Orquestador |
| `RECOPILACIÓN_DE_DATOS` | Todos los datos requeridos presentes | `datos_faltantes` = vacío | `RAZONAMIENTO_DECISIÓN` | Orquestador |
| `RECOPILACIÓN_DE_DATOS` | Dato crítico no obtenible | Límite de reintentos alcanzado | `PAUSA_POR_DATOS_FALTANTES` | Orquestador (regla de límite, no "el LLM se rinde") |
| `RAZONAMIENTO_DECISIÓN` | Cerebro propone tool | Guardrail aprueba | `ACCIÓN` | Orquestador |
| `RAZONAMIENTO_DECISIÓN` | Cerebro propone tool | Guardrail rechaza | `RAZONAMIENTO_DECISIÓN` (replantea) → `ESCALADO_ESTÁNDAR` si se agotan reintentos | Orquestador/Guardrails |
| `ACCIÓN` | Tool devuelve resultado | Éxito | `RESPUESTA` | Orquestador |
| `ACCIÓN` | Tool devuelve error/timeout | — | `RAZONAMIENTO_DECISIÓN` (reintento con límite) → `ESCALADO_ESTÁNDAR` si se agotan reintentos | Orquestador |
| `RESPUESTA` | Objetivo cumplido | — | `CIERRE` | Orquestador |
| `RESPUESTA` | Objetivo cumplido, conversación continúa | — | `SEGUIMIENTO` | Orquestador |
| `RESPUESTA` | Usuario expresa duda | — | `MANEJO_DE_DUDA` | Orquestador |
| `MANEJO_DE_DUDA` | Duda resuelta | — | `RESPUESTA` (retoma la fase previa registrada) | Orquestador |
| `SEGUIMIENTO` | Nuevo mensaje, nueva intención | — | `IDENTIFICACIÓN_DE_INTENCIÓN` (nuevo ciclo, mismo `conversation_id`) | Orquestador |
| Cualquier estado no terminal | `señal_de_urgencia = true` | Regla determinista | `ESCALADO_URGENTE` | Guardrails/reglas deterministas — **nunca el LLM** |
| Cualquier estado no terminal | Usuario pide humano | — | `ESCALADO_ESTÁNDAR` | Orquestador (propuesto por Cerebro, validado) |
| Cualquier estado no terminal | Inactividad > umbral | Umbral PENDIENTE | `ABANDONADA` | Orquestador (proceso determinista de limpieza) |

**Transiciones explícitamente inválidas**:
- `CIERRE` → cualquier estado, sin un nuevo mensaje entrante que dispare un nuevo ciclo.
- `ESCALADO_URGENTE` → reanudación automática del flujo normal, sin que un humano lo autorice.
- Cualquier transición que el LLM aplique directo, sin pasar por Orquestador/Guardrails — inválida por diseño, no por regla de negocio.
- `ACCIÓN` → `ACCIÓN` directo (no se encadenan dos tools sin pasar por `RAZONAMIENTO_DECISIÓN` entre medio — evita ejecuciones no auditadas en cadena).

**Ciclos válidos** (todos con límite de reintentos obligatorio): `RECOPILACIÓN_DE_DATOS` ↔ sí misma; `RAZONAMIENTO_DECISIÓN` ↔ `ACCIÓN`; `MANEJO_DE_DUDA` ↔ `RESPUESTA`.

**Situaciones que requieren intervención humana**: `señal_de_urgencia`, guardrail que rechaza repetidamente sin resolverse, reintentos de tool agotados, usuario que lo pide explícitamente, dato crítico no obtenible.

---

## 10. Idempotencia

RECOMENDACIÓN, campo por campo de los escenarios planteados:

- **Mensaje duplicado**: `último_mensaje_id_procesado` (sección 2.1) permite al Orquestador descartar un mensaje ya procesado sin re-ejecutar el ciclo completo (sin volver a llamar tools, sin generar una segunda respuesta).
- **Tool ejecutada dos veces**: toda tool de categoría WRITE (sección 17) se trata como potencialmente no-idempotente por defecto — antes de reintentar, el Orquestador verifica en `herramientas_utilizadas` si ya existe una ejecución exitosa reciente para el mismo objetivo.
- **Respuesta perdida**: el estado debe distinguir "acción ejecutada" (registrada en `resultado_de_herramientas`) de "respuesta entregada al usuario" — son dos hechos distintos. Si la acción ya se ejecutó pero no se confirmó la entrega, el reintento reenvía la respuesta ya generada, **nunca** vuelve a ejecutar la tool.
- **Usuario repite la solicitud**: si `datos_recopilados` ya cubre lo pedido y `herramientas_utilizadas` ya registra éxito reciente para el mismo `objetivo_de_conversación`, el Orquestador lo reconoce como repetición, no como solicitud nueva.
- **Canal reenvía un evento**: mismo mecanismo que "mensaje duplicado".

**Principio general**: el estado debe distinguir siempre "intención expresada" de "acción efectivamente ejecutada" — confundir ambas es la causa raíz de la mayoría de los errores de duplicación en agentes conversacionales con acciones transaccionales (un riesgo que **Dani nunca enfrentó**, porque ninguna de sus tools escribía en un sistema externo).

---

## 11. Concurrencia

RECOMENDACIÓN aplicada al escenario dado (Mensaje A: "Quiero agendar" / Mensaje B: "Mejor mañana", casi simultáneos):

- Principio 1 — **serialización por conversación**: todo mensaje que pertenece al mismo `conversation_id` se procesa en secuencia, nunca en paralelo sobre el mismo estado. Mientras el Mensaje A se está procesando (leyendo/actualizando el estado), el Mensaje B espera su turno.
- Principio 2 — **concurrencia optimista como red de seguridad**: si a pesar de la serialización ocurre una carrera real, toda escritura verifica que la `version` que está actualizando sigue vigente; si no, la escritura se rechaza y se reintenta sobre el estado más reciente, en vez de sobrescribir ciegamente.
- Aplicado al ejemplo: si "Quiero agendar" ya avanzó a `RECOPILACIÓN_DE_DATOS` con `objetivo_de_conversación = agendar_cita` cuando llega "mejor mañana", este segundo mensaje se procesa **después**, como continuación del mismo ciclo — se interpreta como una corrección de un dato en curso (fecha preferida), no como una intención nueva independiente.

No se elige tecnología (colas, locks distribuidos, etc.) — **PENDIENTE DE DECISIÓN DE STACK**. El principio conceptual (serialización por conversación + concurrencia optimista por versión) es independiente de esa elección.

---

## 12. Versionado

RECOMENDACIÓN, respondiendo directamente a lo solicitado:

- **¿Versión/revisión?** Sí — necesaria para la concurrencia optimista (sección 11) y para detectar escrituras basadas en datos obsoletos.
- **¿Timestamp?** Sí — se mantiene `última_actualización`, y se agrega `creado_en` (no estaba en 003) para calcular duración de la conversación y aplicar políticas de retención.
- **¿Historial de cambios completo dentro del estado?** **No** — embeber el historial completo en el objeto de estado vivo lo infla y mezcla "estado operativo actual" con "bitácora histórica" (justo el tipo de mezcla que la sección 19 pide evitar). El estado vivo solo lleva `version` + `origen_del_último_cambio`; el historial completo append-only vive en el registro de auditoría (sección 13), separado.
- **¿Origen del cambio?** Sí — cada actualización registra qué actor la originó.

**Por qué importa**: sin versión, dos escrituras concurrentes pueden pisarse silenciosamente (ej. el resultado de una tool sobreescribiendo una corrección de riesgo detectada un instante después). Sin origen del cambio, es imposible auditar después "por qué el estado dice esto" — algo que Dani no podía ofrecer en absoluto, porque no tenía estado persistido del cual llevar historial.

---

## 13. Auditoría

RECOMENDACIÓN — cambios que **deben** generar un evento auditable:

- Todo cambio en `nivel_de_riesgo` o `señal_de_urgencia` — máxima prioridad de auditoría.
- Todo cambio en `necesidad_de_escalar` (con motivo).
- Todo cambio en `consentimiento_datos`.
- Toda escritura/lectura/exportación/eliminación de un dato personal — coherente con la regla de protección de datos personales y la de documentación/memoria ya vigentes en icaco (ambas exigen un mecanismo de auditoría propio del dominio, no solo logs de aplicación).
- Toda acción externa ejecutada por una tool WRITE — qué se pidió, con qué parámetros, qué resultado.
- Todo cambio de `fase_actual` — traza completa del recorrido de la conversación.
- Toda invocación de tool (categoría; el payload completo solo si no contiene dato sensible innecesario).
- Todo bloqueo de Guardrail — qué se intentó, por qué se bloqueó. Esta señal, ausente por completo en Dani, es de altísimo valor: mide la calidad del propio sistema.

**Diseño del registro**: append-only, separado del estado operativo vivo. El estado vivo puede expirar/purgarse según política de retención; la auditoría tiene su propia política, probablemente más extensa — plazos exactos **PENDIENTE** (a definir en `.ai/DATA_MODEL.md` de icaco).

---

## 14. Privacidad

RECOMENDACIÓN — clasificación de los campos definidos en la sección 2:

- **Información operacional** (no personal): `conversation_id`, `canal`, `fase_actual`, `modo`, `version`, `última_actualización`, `creado_en`, `origen_del_último_cambio`, `herramientas_utilizadas` (nombres de tool), `próxima_acción`, `nivel_de_confianza`.
- **Información personal**: `datos_recopilados` (puede incluir nombre, contacto, motivo de consulta), `resumen_ref` (si narra contenido personal), `resultado_de_herramientas` (si una tool devuelve datos del usuario).
- **Información potencialmente sensible** (categoría reforzada por ser salud): cualquier campo de `datos_recopilados` que describa síntomas o condiciones de salud; `nivel_de_riesgo` y `señal_de_urgencia` (revelan información de salud/seguridad de la persona).
- **Información de auditoría**: el registro completo de la sección 13 — hereda el nivel de protección del dato que audita, porque puede referenciarlo.

**PENDIENTE DE VALIDACIÓN LEGAL** (no se inventa aquí, igual que ya lo marca la propia regla de protección de datos personales de icaco):
- Si los campos "potencialmente sensibles" caen bajo un régimen legal de dato sensible/especial en la jurisdicción aplicable (no confirmada todavía — ver `003` sección 19).
- Plazos de retención exactos por categoría.
- Si se requiere consentimiento diferenciado (no solo general) para la categoría "potencialmente sensible".

---

## 15. Contrato Cerebro ↔ Orquestador

RECOMENDACIÓN — frontera exacta:

**Qué entrega el Cerebro al Orquestador** (salida estructurada, nunca aplicada directo al estado):
- `intención_detectada`
- `nivel_de_confianza`
- `próxima_acción_propuesta`
- `propuesta_de_actualización_de_estado` (un *delta* — solo los campos que sugiere cambiar, nunca el estado completo)
- `tool_requerida` (si aplica, con parámetros propuestos)
- `respuesta_propuesta` (texto candidato, antes de Guardrails)
- `señales_detectadas` (ej. posible urgencia, posible duda) — como **señal de entrada** para las reglas deterministas, nunca como decisión final

**Qué entrega el Orquestador al Cerebro**:
- El mensaje del turno actual
- El `ConversationState` vigente, **de solo lectura**
- El resumen/memoria relevante (capa D/B de la sección 3)
- El conocimiento ya consultado, o las tools disponibles para solicitarlo
- Las restricciones activas del turno (ej. "ya se detectó una urgencia — tu única salida válida es reconocerla y no proponer nada más")

**Frontera clave**: el Cerebro nunca ve ni escribe el `ConversationState` directo — recibe una vista de solo lectura y devuelve una propuesta. Es la corrección directa del diseño de Dani, donde el LLM tenía, en la práctica, control total sobre lo que ocurría a continuación.

---

## 16. Contrato Orquestador ↔ Guardrails

RECOMENDACIÓN:

- **Entrada**: la propuesta completa del Cerebro (respuesta candidata + propuesta de actualización de estado + tool solicitada).
- **Validación**: Guardrails revisa (a) formato/contenido de la respuesta candidata, (b) si la actualización propuesta toca un campo del Grupo D y si cumple las reglas deterministas asociadas (ej. no se puede proponer bajar `necesidad_de_escalar` si `señal_de_urgencia` sigue en `true`), (c) si la tool solicitada está permitida en la `fase_actual`/`modo` vigentes.
- **Salida** (una de cuatro):
  - **Permitir** — se aplica tal cual.
  - **Modificar** — ej. recortar/reformatear la respuesta, o forzar un campo del estado a su valor determinista correcto.
  - **Bloquear** — se descarta la propuesta completa; se re-invoca al Cerebro con el motivo del bloqueo, o se usa una respuesta de reserva predefinida.
  - **Escalar** — el bloqueo es tan severo (ej. contradice una señal de riesgo activa) que en vez de reintentar con el Cerebro, se dispara directo `ESCALADO_URGENTE`.

**Qué tipo de decisiones deben poder bloquearse**: cualquier intento de bajar/ignorar `nivel_de_riesgo` o `señal_de_urgencia` sin una regla determinista que lo respalde; cualquier promesa prohibida en la respuesta candidata (ej. comprometer un tiempo de contacto humano — lección directa de Dani); cualquier propuesta de ejecutar una tool WRITE sin `consentimiento_datos` o sin confirmación explícita ya capturada; cualquier dato en la respuesta que no provenga de una fuente verificada (Conocimiento/Tools) — es decir, que el Cerebro se lo haya "inventado".

---

## 17. Contrato Orquestador ↔ Tools

RECOMENDACIÓN:

- **Request**: generado por el Orquestador (nunca directo del Cerebro), a partir de la tool solicitada + parámetros ya validados por Guardrails si la tool es crítica.
- **Autorización**: el Orquestador verifica permisos — ¿la tool está permitida en la `fase_actual`/`modo` actuales? ¿requiere confirmación explícita ya capturada en `datos_recopilados`?
- **Parámetros**: siempre provienen de `datos_recopilados` ya validado, nunca de texto libre sin validar generado directo por el Cerebro.
- **Respuesta**: se recibe, se resume, y el resumen (no necesariamente el payload completo) se guarda en `resultado_de_herramientas`.
- **Error**: se distingue recuperable (reintento con backoff y límite) de no recuperable (`PAUSA_POR_DATOS_FALTANTES` o `ESCALADO_ESTÁNDAR`).
- **Timeout**: tratado como error recuperable con el mismo mecanismo de límite.
- **Auditoría**: toda invocación queda registrada (sección 13), en especial las de categoría WRITE.

**Categorías y nivel de control necesario**:

| Categoría | Ejemplo en Dani | Nivel de control necesario |
|---|---|---|
| **READ** | `get_course_data`, `get_detailed_info` | Bajo — el Cerebro puede solicitarla con relativa libertad; el Orquestador solo verifica disponibilidad |
| **WRITE** | (nueva en ICACO — ej. agendar/reagendar/cancelar) | **Alto** — requiere autorización explícita + confirmación del usuario ya capturada en el estado + verificación de idempotencia (sección 10) + auditoría obligatoria |
| **NOTIFY** | `escalate_to_human`, `report_knowledge_gap` | Medio — no modifica datos del dominio, pero debe auditarse y no puede "prometer" nada en nombre del sistema (lección directa de Dani) |

---

## 18. Ejemplos

### Ejemplo 1 — Flujo normal

**Turno 1** — Usuario: *"Quiero pedir una cita"*

Estado antes del turno: `conversation_id` nuevo, `fase_actual = INICIO`, resto vacío/default.

- Cerebro interpreta `intención = agendar_cita`, `nivel_de_confianza = alto`.
- Orquestador transiciona: `INICIO` → `IDENTIFICACIÓN_DE_INTENCIÓN` → (confianza alta) → `RECOPILACIÓN_DE_DATOS`.
- Estado tras el turno: `intención = agendar_cita`; `objetivo_de_conversación = agendar_cita`; `fase_actual = RECOPILACIÓN_DE_DATOS`; `datos_faltantes` (derivado) = [motivo, fecha preferida, ...] (esquema exacto por objetivo: **PENDIENTE**, sección 22).
- Respuesta: pregunta por el dato faltante de mayor prioridad.

**Turno 2** — Usuario: *"Para revisión general, la próxima semana si se puede"*

- Cerebro extrae `motivo = revisión_general`, `fecha_preferida = próxima_semana`.
- Orquestador actualiza `datos_recopilados`; recalcula `datos_faltantes` (ya cubierto, o falta solo confirmar horario exacto).
- Transición: `RECOPILACIÓN_DE_DATOS` → `RAZONAMIENTO_DECISIÓN` → Cerebro propone tool WRITE "agendar" → Guardrails verifica `consentimiento_datos`: si falta, bloquea y fuerza el flujo de consentimiento primero; si está, aprueba → `ACCIÓN`.
- Tool ejecuta, devuelve horario confirmado.
- `herramientas_utilizadas += [agendar_cita: éxito]`; `resultado_de_herramientas = {horario: ...}`.
- Transición: `ACCIÓN` → `RESPUESTA` → objetivo cumplido → `CIERRE` (o `SEGUIMIENTO` si se pregunta si necesita algo más).

### Ejemplo 2 — Interrupción de seguridad

**Turno 1** — Usuario: *"Quiero pedir una cita, pero llevo dos días con un dolor en el pecho muy fuerte"*

- Cerebro interpreta `intención = agendar_cita` **y además** reporta `señales_detectadas: posible_urgencia`.
- Una regla determinista (no el Cerebro) evalúa esa señal contra criterios de riesgo (protocolo exacto **PENDIENTE DE VALIDACIÓN CLÍNICA**, heredado de `003` sección 19) → si coincide con un patrón definido, `señal_de_urgencia = true`.
- Guardrails: al ver `señal_de_urgencia = true`, **bloquea** cualquier propuesta del Cerebro que no sea reconocer la urgencia — aunque el Cerebro "quisiera" seguir con el flujo de agendar.
- Transición: **cualquier estado** (aquí, recién saliendo de `INICIO`) → `ESCALADO_URGENTE` (interrupción global, sección 7).
- Estado: `necesidad_de_escalar = true`, motivo = "posible urgencia médica reportada por el usuario"; `fase_actual = ESCALADO_URGENTE` (terminal para el flujo automatizado).
- Respuesta: mensaje breve derivando a atención inmediata (contenido exacto **PENDIENTE** de validación clínica/de producto — no se redacta un guion médico en este documento).
- La intención original "agendar cita" queda registrada en `datos_recopilados`/auditoría para retomarse después **si un humano lo autoriza** — nunca se reanuda automáticamente.

**Diferencia visual**: en el flujo normal, el estado avanza linealmente turno a turno hacia el objetivo. En la interrupción de seguridad, el estado salta directo a un estado terminal de máxima prioridad sin pasar por ninguna fase intermedia, sin importar en qué punto de la conversación se detectó la señal.

---

## 19. Errores a evitar

RECOMENDACIÓN — auto-revisión activa de este mismo contrato contra los riesgos de diseño solicitados:

| Riesgo | Cómo lo corrige este contrato |
|---|---|
| Duplicación de información | Separación ESTADO/MEMORIA/RESUMEN/CONOCIMIENTO (sección 3); `contexto` narrativo sacado del estado; `datos_faltantes` tratado como derivado, nunca duplicado |
| Campos ambiguos | `nivel_de_riesgo` separado de `señal_de_urgencia` (en 003 estaban casi fusionados) |
| Estado demasiado grande | Historial completo NO se embebe en el estado vivo (vive en auditoría aparte); `resultado_de_herramientas` guarda solo el último resultado por tool |
| Estado demasiado pequeño | El estado mínimo (sección 4) igual incluye `señal_de_urgencia` y `consentimiento_datos` — no se sacrifican por simplicidad |
| Dependencia excesiva del LLM | Frontera de autoridad (sección 8): el Cerebro solo propone |
| Ciclos infinitos | Todo ciclo válido exige límite de reintentos (sección 9) |
| Pérdida de contexto | Ninguna decisión de flujo depende solo de una ventana fija de memoria — a diferencia de Dani |
| Inconsistencias | `version` + concurrencia optimista (secciones 11-12) |
| Modificaciones no autorizadas | Matriz de autoridad (sección 8) |
| Falta de auditoría | Lista explícita de eventos auditables (sección 13) |
| Mezcla de memoria y estado | Resuelto explícitamente en la sección 3, a pedido directo de esta fase |

**Riesgo residual, declarado con honestidad** (no resuelto por este documento): `próxima_acción` y `nivel_de_confianza` dependen de que el Cerebro los reporte con honestidad en cada turno — no existe forma de verificar por código que una "confianza alta" reportada por el LLM sea realmente alta. Esto no se resuelve con un contrato de estado; requiere, en una fase posterior, calibración/evaluación del propio modelo — fuera del alcance de este documento.

---

## 20. Dani → ICACO

HECHO (columna izquierda, sustentada en `002-autopsia-cerebro-dani.md`) / RECOMENDACIÓN (columna derecha, sustentada en `003` y en este documento):

| DANI → problema | ICACO → solución |
|---|---|
| Sin estado persistido; todo inferido del historial cada turno | `ConversationState` explícito, persistido, con autoridad de escritura restringida al Orquestador (secciones 2, 8) |
| Contadores de repetición "mentales" | Campos estructurados en `datos_recopilados`/`herramientas_utilizadas`, no inferidos |
| Ventana de memoria fija (8 turnos) como única fuente de continuidad | Separación en capas ESTADO/MEMORIA/RESUMEN/PERFIL (sección 3) — ninguna decisión de flujo depende solo de la ventana cruda |
| Ningún guardrail de código sobre la salida del LLM | Contrato Orquestador↔Guardrails explícito, con poder de bloquear/modificar/escalar (sección 16) |
| Reglas de negocio en texto libre del prompt | Separación instrucciones/reglas/guardrails/políticas, aplicada aquí a nivel de contrato (sección 16-17) |
| Ninguna auditoría ni observabilidad | Lista explícita de eventos auditables, registro append-only separado del estado vivo (sección 13) |
| Toda escalación tratada igual, sin distinguir urgencia | `ESCALADO_URGENTE` vs. `ESCALADO_ESTÁNDAR`, con prioridad determinista (secciones 6-7) |
| El LLM invocaba tools directo, sin capa intermedia de control | Contrato Orquestador↔Tools con autorización y categorías READ/WRITE/NOTIFY con nivel de control diferenciado (sección 17) |
| Ninguna protección observada contra duplicación/reintento | Mecanismo conceptual de idempotencia explícito (sección 10) |
| Ninguna noción explícita de concurrencia en el extracto disponible | Procesamiento serializado por conversación + concurrencia optimista por versión (sección 11) |

---

## 21. Decisión de madurez

**SÍ, CON CONDICIONES.**

El contrato conceptual es suficientemente maduro para empezar a diseñar el prototipo mínimo (sección 4), pero antes de codificar faltan, explícitamente:

1. El esquema exacto de "datos requeridos por tipo de objetivo" (qué campos exige `agendar_cita` u otro objetivo) — necesario para que `datos_recopilados`/`datos_faltantes` dejen de ser un concepto y se vuelvan un esquema real. **PENDIENTE**, depende del caso de uso exacto de salud (ver `003`, sección 19).
2. El protocolo de riesgo/urgencia exacto — sin él, `señal_de_urgencia` es un campo bien diseñado pero vacío de contenido real. **PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL**, no es una decisión de software.
3. A quién exactamente se escala y con qué disponibilidad real. **PENDIENTE**.
4. Ninguna decisión de stack se ha tomado (deliberadamente, por instrucción de esta fase) — el contrato es implementable en cualquier stack razonable, pero la implementación real requiere esa elección primero.
5. Se recomienda una validación cruzada de este contrato, específicamente de los campos de riesgo/urgencia, con alguien con criterio clínico, antes de construir el prototipo.

Resueltas esas condiciones, el contrato sí es apto para pasar al diseño del prototipo mínimo.

---

## 22. Pendientes

Consolidado de todo lo marcado **PENDIENTE** a lo largo del documento:

- Esquema exacto de datos requeridos por tipo de objetivo (depende del caso de uso exacto de salud, aún no definido).
- Protocolo clínico de riesgo/urgencia — validación humana/legal, no de software.
- A quién se escala exactamente y con qué disponibilidad real.
- Jurisdicción/marco legal de datos de salud (si aplica una categoría de dato sensible, plazos de retención exactos, si se requiere consentimiento diferenciado).
- Umbral de tiempo para la transición a `ABANDONADA`.
- Catálogo cerrado de canales soportados.
- Catálogo cerrado de intenciones/objetivos soportados.

**PENDIENTE DE DECISIÓN DE STACK** (no se elige aquí, por instrucción explícita de esta fase):
- Motor de base de datos para persistir el estado.
- Mecanismo real de concurrencia/locking (más allá del principio conceptual de la sección 11).
- Mecanismo de colas/deduplicación de mensajes entrantes.
- Tecnología de orquestación (n8n como Dani, agente nativo, u otro).
- Modelo de LLM.
- Canal de mensajería exacto.
