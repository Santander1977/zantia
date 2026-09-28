# RECADO PARA CHATGPT

Fecha: 2026-09-06
Proyecto: icaco (ZANTIA — dominio salud, `domains/health`, integrado con hrmm-backend real)
Tema: Corrección del hallazgo del recado 049 — ventana de gracia de un turno tras cerrar una `Activity`, para que las 5 categorías de interrupción de contexto del recado 047 se revisen también en el mensaje inmediatamente posterior a un cierre (reserva confirmada/reprogramada/declinada), no solo dentro de una conversación ya abierta.
Objetivo de la investigación/trabajo: implementar el mecanismo pedido explícitamente por el usuario, decidir con cuidado (sin improvisar) cómo tratar una declaración de beneficiario sobre una reserva REAL ya ejecutada contra producción, verificar los 5 puntos pedidos con evidencia real (no supuesta), y documentar el resultado.

---

## Resumen ejecutivo

Se implementó una ventana de gracia de UN turno en `domains/health/gateway.py`: apenas `_cerrar_si_definitivo` cierra una `Activity` (reserva confirmada/reprogramada/declinada), queda registrada como "recién cerrada" (`HealthGateway._recien_cerrada`, nuevo). El mensaje siguiente del mismo paciente, si no encuentra conversación abierta, se reevalúa PRIMERO contra el detector centralizado de interrupciones de contexto del recado 047 (`HealthBrain._detectar_interrupcion_de_contexto`, reutilizado tal cual — nunca duplicado, expuesto ahora vía una nueva propiedad de solo lectura `Orchestrator.brain`) antes de tratarse como una solicitud 100% nueva. La ventana se consume en esa misma evaluación (coincida o no) — nunca dura más de un turno.

Para el caso más delicado (declarar un beneficiario DESPUÉS de que la Activity recién cerrada ya ejecutó una reserva real contra hrmm-backend), se tomó una decisión de diseño explícita: NUNCA se cancela ni se reasigna nada automáticamente. Se distingue, con una señal ya existente en el propio dominio (`intent.py:_PROGRAMAR`, las frases explícitas de "solicitud de cita nueva"), si el mensaje es sobre una cita NUEVA (arranca el wizard normal de beneficiario, sin cambios) o es una corrección/reclamo sobre la reserva que se acaba de hacer (se informa con claridad y se remite al mismo flujo de cancelación YA EXISTENTE y YA protegido por código de verificación — nunca se ejecuta ninguna escritura nueva en ese turno).

Se encontraron y corrigieron, en el camino, dos bugs reales de implementación (no supuestos — descubiertos corriendo los tests contra el código real):
1. Un mismatch de clave preexistente en `_cerrar_si_definitivo` (`context.activity.patient_reference`, el DOCUMENTO ya resuelto, en vez del identificador de CANAL con el que el resto del archivo indexa `_open_conversations`/`_saludo_mostrado`) — inofensivo hasta ahora porque `find_open_context` se autocorregía en la siguiente consulta, pero rompía la ventana de gracia nueva.
2. `core/orchestrator.py:_reabrir_ciclo` borra `datos_recopilados` a `{}` cada vez que `fase_actual == CIERRE` — sin corregir también `fase_actual` al reabrir el wizard de beneficiario, el turno siguiente perdía todo lo que la ventana de gracia acababa de guardar.

Los 5 puntos de verificación pedidos pasan con evidencia real (tests nuevos, corridos, no supuestos) y la suite completa queda en **354 passed, 4 skipped** (350 previas + 4 nuevas) — cero regresiones.

## Hallazgos

### Hallazgo A — el detector de interrupciones vive solo dentro de `HealthBrain.interpret()`, inalcanzable sin conversación abierta

Ya diagnosticado en el recado 049 — reconfirmado acá al implementar la corrección: `_evaluar_ventana_de_gracia` (nuevo, `gateway.py`) tuvo que reutilizar `_detectar_interrupcion_de_contexto` DIRECTO (vía la nueva propiedad `Orchestrator.brain`) porque no existía ningún otro punto de acceso — confirma que el recado 047 nunca tocó `gateway.py`, exactamente como se documentó.

### Hallazgo B (nuevo, encontrado en este trabajo) — mismatch de clave entre `context.activity.patient_reference` y el identificador de canal

`_cerrar_si_definitivo` (antes de esta corrección) hacía `gateway._open_conversations.pop(context.activity.patient_reference, None)` — pero `context.activity.patient_reference` es el DOCUMENTO ya resuelto (`_documento_resuelto`, gate de identidad 012/R-15), NO el identificador de CANAL con el que `_open_conversations`/`_saludo_mostrado`/`register_context` indexan en cualquier otro punto del archivo. Con canales/AppointmentService donde canal == documento (el caso común, cubierto por casi todos los tests existentes) esto no se nota. Con el gate de identidad activo (canal distinto del documento — reproducido a propósito en los tests nuevos de este recado, `identity_store.marcar_verificado(canal, documento, nombre)`), el `pop` original era un no-op silencioso — inofensivo porque `find_open_context` se autolimpia en la siguiente consulta de todos modos — pero mi ventana de gracia nueva (`_recien_cerrada`) SÍ necesitaba la clave correcta para poder encontrarse en el turno siguiente.

**Corregido**: `_cerrar_si_definitivo` ahora recibe `patient_reference` (el identificador de canal) como parámetro explícito — los 3 call sites (`handle_inbound_message`, `_resolver_programar_cita`, `_resolver_gestion_de_cita_existente`) ya lo tenían en alcance, se pasa explícito en vez de derivarlo de la Activity. Cambio mínimo, mismo comportamiento para cualquier caso donde canal == documento (la mayoría de los tests existentes), corrige el caso gated sin tocar nada más.

### Hallazgo C (nuevo, encontrado en este trabajo) — `_reabrir_ciclo` (Core) borra `datos_recopilados` al reabrir desde CIERRE

`core/orchestrator.py:Orchestrator.handle_message` — cuando `state.fase_actual == FaseActual.CIERRE`, llama a `_reabrir_ciclo(state)`, que **resetea `datos_recopilados` a `{}`** (además de `intencion`, `objetivo_de_conversacion`, etc.) antes de invocar al Brain. Sin corregir también `fase_actual` al reabrir el wizard de beneficiario desde la ventana de gracia, el turno SIGUIENTE (el documento del beneficiario, procesado por el camino normal `handle_patient_message`) encontraba `fase_actual == CIERRE`, `_reabrir_ciclo` borraba `datos_recopilados["etapa"] = "esperando_documento_beneficiario"` de vuelta a `{}`, y el mensaje caía en el fallback de `_interpretar_decision` ("No logré entender si es un sí o un no...") en vez de `_interpretar_documento_beneficiario`.

**Corregido**: cuando la ventana de gracia reabre el wizard de beneficiario (única de las 5 categorías que necesita continuar en turnos siguientes), `_evaluar_ventana_de_gracia` también fija `fase_actual = FaseActual.RECOPILACION_DE_DATOS` (la fase real en la que ya vive cualquier etapa "esperando_X" en curso — no una fase inventada) al guardar el estado, además de reabrir `Activity.status` (`COMPLETED` -> `IN_PROGRESS`, mismo estado que dispensa `accept_activity` para cualquier Activity nueva) y re-registrar la conversación como abierta (`register_context`, mecanismo de correlación de siempre, sin cambios).

## Arquitectura / estructura encontrada

Mecanismo completo, en `domains/health/gateway.py`:

1. `HealthGateway._recien_cerrada: Dict[str, str]` (nuevo campo del dataclass) — `patient_reference` (canal) -> `activity_id` de la Activity que se acaba de cerrar.
2. `_cerrar_si_definitivo` (firma cambiada: ahora recibe `patient_reference` explícito) registra ahí la Activity al cerrarla — sin hacer `_contexts.pop(...)` (a diferencia de `_open_conversations`), para que la ventana de gracia pueda recuperar el contexto completo.
3. `handle_inbound_message`: tras `find_open_context` devolver `None`, y ANTES del gate de identidad, llama a `_evaluar_ventana_de_gracia(gateway, patient_reference, message_id, text)` (nuevo). Si devuelve una respuesta, el turno termina ahí.
4. `_evaluar_ventana_de_gracia` (nuevo):
   - `pop` de `_recien_cerrada` (consumo de un solo uso, sin importar el resultado).
   - Recupera el `HealthAgentContext` cerrado desde `_contexts` y su `ConversationState` desde `orchestrator.store`.
   - Si la etapa guardada está en `HealthBrain._ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO`, no aplica (mismo criterio que dentro de una conversación abierta).
   - Llama a `contexto_cerrado.orchestrator.brain._detectar_interrupcion_de_contexto(texto, datos, etapa)` — el MISMO detector del recado 047, reutilizado vía la nueva propiedad de solo lectura `Orchestrator.brain` (`core/orchestrator.py`, mismo patrón que `tools`/`events`/`store`).
   - Si no coincide con ninguna de las 5 categorías: `None` — el llamador sigue con `_enrutar_solicitud_nueva` normal, sin ningún cambio de comportamiento.
   - Si coincide con `_PARA_OTRO` (beneficiario) Y la Activity cerrada tiene `appointment_id` real Y el texto NO contiene ninguna frase explícita de `intent.py:_PROGRAMAR` ("necesito una cita", "agendar", etc.): se DESCARTA la respuesta del Brain (que habría arrancado el wizard) y se sustituye por el mensaje de "informa y remite a cancelar" (ver Decisión de diseño abajo) — sin ninguna escritura nueva.
   - En cualquier otro caso de coincidencia: se persiste la actualización de estado propuesta por el Brain (y, si la nueva etapa es `esperando_documento_beneficiario`, además se reabre `Activity.status`, `fase_actual`, y se re-registra la conversación — Hallazgos B/C arriba) y se devuelve la respuesta.
5. `core/orchestrator.py`: nueva propiedad `Orchestrator.brain` (solo lectura, mismo patrón que `tools`/`events`/`store`).

## Archivos importantes

- `/Users/enzoalfonso/Orangutan/icaco/domains/health/gateway.py`:
  - `HealthGateway._recien_cerrada` (nuevo campo, ~línea 365).
  - `handle_inbound_message` (~línea 499): nueva llamada a `_evaluar_ventana_de_gracia` entre `find_open_context` y el gate de identidad.
  - `_cerrar_si_definitivo` (~línea 903, firma cambiada: `+patient_reference`).
  - `_evaluar_ventana_de_gracia` (nueva, ~línea 970).
  - Import nuevo: `from .intent import _PROGRAMAR as _PALABRAS_PROGRAMAR_CITA`.
- `/Users/enzoalfonso/Orangutan/icaco/core/orchestrator.py`: nueva propiedad `Orchestrator.brain` (~línea 103).
- `/Users/enzoalfonso/Orangutan/icaco/domains/health/brain.py`: SIN cambios funcionales (se agregó solo un comentario en `_detectar_interrupcion_de_contexto` explicando que la distinción "cita nueva vs. corrección" vive deliberadamente en `gateway.py`, no acá) — el comportamiento normal de `_PARA_OTRO` dentro de una conversación abierta (recado 047) queda intacto, verificado por la suite existente sin cambios.
- Nuevo: `/Users/enzoalfonso/Orangutan/icaco/tests/domains/health/test_ventana_de_gracia_tras_cierre.py` (4 tests, ver Verificación abajo).

## Decisiones o conclusiones

**Decisión de diseño explícita, pedida por el usuario — cómo tratar `_PARA_OTRO` sobre una reserva ya ejecutada**: se consideraron y descartaron dos alternativas antes de elegir la implementada.

- Descartada: reasignar `documento_paciente` de la cita ya creada en silencio. No existe ningún endpoint de hrmm-backend para eso (`crear_cita`/`cancelar_cita`/`reprogramar_cita` son las únicas escrituras posibles) — habría que inventar una mutación nueva contra producción sin ningún endpoint real que la soporte.
- Descartada: cancelar automáticamente la reserva anterior y arrancar el wizard de beneficiario para reservar una nueva. Con `HrmmAppointmentService` real, cancelar SIEMPRE exige el código de verificación por correo — `HealthBrain._cancelar` (sin tocar) ya documenta que ese camino determinista es INALCANZABLE con un servicio real; el paciente real cancela exclusivamente por el sub-flujo `gateway.py:_procesar_intento_de_codigo`. Ejecutar una cancelación real sin ese código saltaría la misma protección que ya existe para cualquier otra cancelación — inaceptable para una escritura contra producción.
- **Elegida**: informar con claridad (la cita quedó a nombre del titular, no del beneficiario) y remitir EXPLÍCITAMENTE al mismo flujo de cancelación ya existente y ya protegido (la frase exacta "cancelar la cita", reconocida tanto por `HealthBrain._CANCELAR` como por `intent.py:RequestIntent.CANCELAR_CITA`) — nunca se ejecuta ni se propone ninguna escritura nueva en ese turno. Verificado en los tests (ver abajo) que decir "cancelar la cita" a continuación SÍ dispara el envío real del código de verificación — el mensaje no remite a un callejón sin salida.

**Cómo se distingue "cita nueva" de "corrección sobre la reserva recién hecha"**: ambos mensajes de ejemplo del usuario mencionan un beneficiario; la única señal disponible con el criterio de este dominio (palabras clave, no NLU real — `.ai/RISKS.md` R-13) es si el texto TAMBIÉN contiene una frase explícita de `intent.py:_PROGRAMAR` ("necesito una cita", "agendar", etc.). Se intentó primero con `classify_intent_or_none(text) != RequestIntent.PROGRAMAR_CITA` — **INCORRECTO**, descubierto corriendo los tests: esa función solo devuelve `None` para un saludo PURO (recado 048); para CUALQUIER OTRO texto sin ninguna palabra clave específica, sigue defaulteando a `PROGRAMAR_CITA` igual (recado 030) — con ese criterio, AMBOS mensajes de ejemplo clasificaban igual, sin distinguir nada. Corregido usando el chequeo DIRECTO contra `intent.py:_PROGRAMAR` (import `_PALABRAS_PROGRAMAR_CITA`).

## Verificación (los 5 puntos pedidos)

Todo en `tests/domains/health/test_ventana_de_gracia_tras_cierre.py` (4 tests nuevos, contra `HrmmAppointmentService` real con `FakeHttpClient`, 4 servicios reales del catálogo HRMM):

1. ✅ `test_beneficiario_declarado_en_solicitud_nueva_tras_cierre_activa_wizard` — reproduce el caso EXACTO del recado 049 punto 1: reserva de Pediatría confirmada para el titular -> "dale gracias, necesito una cita para mi hija" -> activa el wizard de beneficiario (pide documento), NO la rama de "reserva ya ejecutada", NO crea una `PatientRequest`/Activity de programar cita normal. Además confirma que el wizard reabierto es funcional en el turno siguiente (documento de la hija -> "Hija de Prueba 050... correcto").
2. ✅ `test_reclamo_sobre_reserva_ya_ejecutada_informa_y_remite_a_cancelar_protegido` — reproduce el caso EXACTO del recado 049 punto 3: reserva confirmada -> "pero es para mi hija y no me pregustastes su documento de identidad" -> respuesta informa y remite a "cancelar la cita" + "código de verificación", NUNCA arranca el wizard normal, la cita original queda exactamente igual (`estado: reservada`, sin cambios), no se envía ningún código todavía. Bonus verificado: decir "cancelar la cita" a continuación SÍ dispara el envío real del código de verificación (mismo sub-flujo ya existente, sin tocar) — confirma que no es un callejón sin salida.
3. ✅ `test_solicitud_genuinamente_nueva_tras_cierre_no_se_ve_afectada` — reserva confirmada -> "necesito otra cita de urgencias" -> se comporta exactamente como una solicitud nueva cualquiera (pregunta servicio, crea una segunda `PatientRequest`/Activity real) — cero cambio de comportamiento.
4. ✅ `test_ventana_de_gracia_no_dura_mas_de_un_turno` — reserva confirmada -> "hola" (consume la ventana sin activar nada) -> "es para mi hija" (un segundo mensaje que SÍ hubiera calzado) -> ya NO activa el wizard, mismo comportamiento de siempre — confirma que la ventana nunca dura más de un turno.
5. ✅ Suite completa: **354 passed, 4 skipped** (350 previas + 4 nuevas) — cero regresiones, incluidos los cambios en `core/orchestrator.py` y la firma de `_cerrar_si_definitivo`.

## Problemas encontrados

Ver Hallazgos B y C arriba — ambos corregidos en este mismo trabajo, no quedan pendientes.

## Riesgos

- La ventana de gracia es de UN SOLO turno, por diseño explícito pedido por el usuario ("el mecanismo más simple"). Un paciente que tarde más de un mensaje en darse cuenta del error (ej. "hola" -> "en realidad..." -> "es para mi hija") NO quedará cubierto — mismo comportamiento que antes de este recado para ese caso más lejano. Documentado, no un descuido (ver `test_ventana_de_gracia_no_dura_mas_de_un_turno`).
- La distinción "cita nueva vs. corrección" (`_PROGRAMAR` explícito) es, como el resto del dominio, por palabras clave — un mensaje real que declare beneficiario para una cita NUEVA sin usar ninguna de las frases de `_PROGRAMAR` (ej. "también para mi hija, por favor") caería, incorrectamente, en la rama de "reserva ya ejecutada" en vez de arrancar el wizard normal. No se encontró ningún caso real de producción así todavía — vale la pena vigilarlo si aparece.
- El `appointment_service` de las 4 respuestas de interrupción reevaluadas en la ventana de gracia (`_HUMANO`/`_NO_PUEDE_AHORA`/`_INFO_NO_AUTORIZADA`/`_PIDE_INFO`) queda en un desenlace de un solo turno (escalada/finalizada/sin cambio) — no se reabren para continuación, por diseño (solo `_PARA_OTRO` genera un wizard de varios turnos). Si en el futuro alguna de esas 4 categorías necesitara continuación multi-turno, habría que extender el mismo mecanismo de reapertura (Hallazgo C) a esos casos también.

## Recomendaciones

RECOMENDACIÓN (no implementada, para decidir con el usuario):
- Corregido: revisar si el mismatch de clave del Hallazgo B (`context.activity.patient_reference` vs. identificador de canal) aparece en algún OTRO punto del código que no se haya tocado en este trabajo — solo se corrigieron los 3 call sites de `_cerrar_si_definitivo`; no se hizo una auditoría exhaustiva de todo `gateway.py` buscando el mismo patrón en otros lugares.
- Evaluar si el hallazgo del Core (`_reabrir_ciclo` borra `datos_recopilados` al reabrir desde CIERRE, Hallazgo C) tiene otras consecuencias no ejercitadas todavía en otros dominios que usen `core/orchestrator.py` (`domains/citizen`, `domains/emergency`, `domains/sales`) — este recado solo lo corrigió para el caso puntual de la ventana de gracia del dominio salud.

## Información que debe conocer ChatGPT

- Este recado continúa directamente el recado 049 (mismo hallazgo, ahora corregido) — leer ese primero para el diagnóstico original completo.
- El branch de trabajo (`main`) tenía, antes de este trabajo, el push de los commits del recado 047/048 bloqueado por un "clasificador de modo automático" (según el propio recado 048) — no se verificó en esta sesión si ese bloqueo sigue vigente ni se intentó commitear/pushear este trabajo.
- La cita real `CITA-680ca01ca2` (Odontología, 2026-09-08, documento 72302972 — la que originó el reporte del recado 049) fue cancelada exitosamente en este mismo hilo de trabajo, ANTES de este recado, contra hrmm-backend real, con el código de verificación real enviado al correo registrado — confirmado con una consulta posterior (`estado: cancelada`). No relacionado con el mecanismo de este recado (se hizo manualmente, no automatizado).

## Preguntas pendientes

1. ¿Se commitea y pushea este trabajo? (mismo patrón de pregunta que los recados 047/048).
2. ¿Vale la pena una auditoría más amplia del mismatch de clave del Hallazgo B en el resto de `gateway.py`?
3. ¿El comportamiento de "un solo turno" de la ventana de gracia es suficiente, o el usuario prefiere evaluar una ventana más larga (con TTL real) más adelante, ahora que existe un mecanismo base para extenderla?
