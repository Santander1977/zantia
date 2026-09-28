# RECADO PARA CHATGPT

Fecha: 2026-09-06
Proyecto: icaco (ZANTIA — motor conversacional multi-dominio; dominio activo probado: `domains/health`, integrado con hrmm-backend real)
Tema: El fix del recado 047 (interrupciones de contexto — `_PARA_OTRO`/beneficiario en cualquier etapa) no cubre el caso real reportado hoy: una conversación que ACABA de cerrarse (reserva confirmada, o declinada/"no puedo ahora") y el paciente escribe inmediatamente después, en el mismo hilo de chat, un mensaje relacionado ("necesito una cita para mi hija" / una queja sobre la reserva que se acaba de hacer).
Objetivo de la investigación: diagnosticar con evidencia de código real (sin corregir todavía) por qué el fix del recado 047 no evitó una SEGUNDA reserva a nombre del titular en vez del beneficiario, y por qué un reclamo inmediato posterior a una reserva confirmada reinicia el flujo en vez de reconocerse como relacionado con esa reserva. Además, confirmar el estado real de la cita involucrada contra hrmm-backend y dar una primera evaluación (sin implementar) de fuzzy matching de fecha/hora.

---

## Resumen ejecutivo

El fix del recado 047 SÍ funciona — pero solo dentro de una conversación que el `HealthGateway` ya considera "abierta" (`find_open_context` devuelve una `Activity` no cerrada). El caso real de hoy no cae ahí: la conversación anterior (una cita de Pediatría) ya había llegado a un desenlace definitivo (`management_status` en `APPOINTMENT_CONFIRMED`/`DECLINED`/etc.), lo que dispara `_cerrar_si_definitivo` — cierre INMEDIATO e IRREVOCABLE de la `Activity`, en el mismo turno. El siguiente mensaje del mismo paciente ("dale gracias, necesito una cita para mi hija") ya no encuentra conversación abierta, así que se enruta por `gateway.py:_enrutar_solicitud_nueva` — un camino de clasificación de intención MÁS SIMPLE (`classify_intent_or_none`) que NUNCA llama a `HealthBrain.interpret()` en el primer turno cuando hay más de un servicio en el catálogo (decisión de diseño explícita y documentada en el propio código, ver sección "Archivos importantes"). El recado 047 solo tocó `HealthBrain.interpret()` — nunca tocó `gateway.py:_enrutar_solicitud_nueva`/`_resolver_programar_cita`, que es un código completamente distinto y es el que se ejecuta en este caso real. Por eso "para mi hija" nunca se evalúa: el texto del paciente se usa SOLO para clasificar la intención gruesa (PROGRAMAR_CITA) y después se descarta.

El mismo mecanismo explica el hallazgo #3 (el reclamo post-reserva que reinicia el flujo): tras confirmarse la reserva de Odontología, `_cerrar_si_definitivo` cierra la Activity en el mismo turno. El mensaje siguiente del paciente ("pero es para mi hija y no me preguntaste su documento...") vuelve a encontrar `find_open_context() == None` y se re-enruta como solicitud 100% nueva — no existe, en ningún punto del código, un mecanismo de "ventana de gracia" o "mensaje de seguimiento sobre la conversación recién cerrada". Es la MISMA causa raíz para los dos hallazgos, no dos bugs distintos.

Se confirmó contra hrmm-backend real (`GET /api/agenda/citas?documento_paciente=72302972`) que la cita de Odontología (2026-09-08, 08:00, Consultorio 4 — `cita_id=CITA-680ca01ca2`) SÍ quedó real y activa (`estado: "agendada"`), reservada bajo `documento_paciente=72302972` — el documento del TITULAR, no de la beneficiaria (hija). Confirma exactamente lo que el usuario sospechaba.

## Hallazgos

### Hallazgo A — `_resolver_programar_cita` evita deliberadamente `HealthBrain.interpret()` en el primer turno de una solicitud nueva

HECHO (código real, `domains/health/gateway.py:731-744`): cuando `_determinar_servicio_inicial` encuentra más de un servicio en el catálogo (el caso real: HRMM tiene 5 — Medicina General, Pediatría, Odontología, Urgencias, Psicología), `_resolver_programar_cita` escribe `etapa: "esperando_servicio"` DIRECTAMENTE en el estado y devuelve la pregunta de servicio, sin pasar el texto del paciente por `HealthBrain.interpret()`. El propio comentario del código lo documenta como decisión intencional: *"todavía no hay ninguna respuesta del paciente que interpretar en este primer turno, así que no hace falta pasar por `HealthBrain.interpret()` para componerlo"*.

Consecuencia: `_detectar_interrupcion_de_contexto` (donde vive el chequeo de `_PARA_OTRO` desde el recado 047) NUNCA se ejecuta para el texto que disparó esta rama. El texto completo del paciente ("dale gracias, necesito una cita para mi hija") sí llega íntegro a `_enrutar_solicitud_nueva`, pero solo se usa para `classify_intent_or_none` (clasificación gruesa de intención: PROGRAMAR_CITA / CANCELAR_CITA / etc., sin ningún conocimiento de `_PARA_OTRO`) — después se descarta.

### Hallazgo B — `_cerrar_si_definitivo` cierra la Activity de forma inmediata e irrevocable, sin ventana de gracia

HECHO (código real, `domains/health/gateway.py:876-908`): apenas `context.activity.management_status` llega a `APPOINTMENT_CONFIRMED`, `RESCHEDULED` o `DECLINED`, se llama `finalize_and_report` (que deja el `Activity.status` en un estado de `_ACTIVITY_ESTADOS_CERRADOS = {COMPLETED, FAILED, CANCELLED, EXPIRED}`) y se elimina la entrada de `gateway._open_conversations` — en el MISMO turno que produjo la confirmación/declinación, no en un turno posterior.

`find_open_context` (línea ~393-409) verifica frescura consultando `context.activity.status in _ACTIVITY_ESTADOS_CERRADOS` en cada llamada — no hay ningún TTL, ventana de gracia, ni "¿el paciente sigue escribiendo sobre lo mismo?". El estado cerrado es terminal e inmediato.

### Hallazgo C — Es la MISMA causa raíz para los puntos 1 y 3 reportados por el usuario, no dos bugs distintos

INFERENCIA (a partir de A + B): cualquier mensaje que llegue DESPUÉS de que una Activity se cierre — sin importar cuán relacionado esté con lo que se acaba de conversar, ni cuán rápido llegue — se trata como una solicitud 100% nueva, evaluada solo por `classify_intent_or_none` (sin memoria de la conversación anterior, sin `HealthBrain` en el primer turno). Esto explica:
- Punto 1 del usuario: "necesito una cita para mi hija" tras cerrar la conversación de Pediatría → nunca pasa por `_PARA_OTRO`.
- Punto 3 del usuario: el reclamo post-reserva de Odontología → tampoco pasa por ningún chequeo relacionado con la reserva recién hecha; simplemente crea una Activity nueva de PROGRAMAR_CITA y vuelve a preguntar servicio.

### Hallazgo D — Confirmado contra hrmm-backend real: la cita de Odontología quedó a nombre del titular

HECHO (verificado ahora mismo, `GET /api/agenda/citas?documento_paciente=72302972` contra `hrmm-backend` producción, con el secreto de canal de confianza local en `backend/.env`):

```json
{
  "cita_id": "CITA-680ca01ca2",
  "slot_id": "SLOT-SEED20260906-00183",
  "medico_id": "MED-04",
  "servicio_id": "SERV-03",
  "fecha": "2026-09-08",
  "hora_inicio": "08:00",
  "documento_paciente": "72302972",
  "nombre_paciente": "",
  "telefono": "",
  "correo": null,
  "estado": "agendada",
  "confirmada_en": null,
  "created_at": "2026-09-07T01:46:22.749037",
  "updated_at": "2026-09-07T01:46:22.749037"
}
```

- Estado real: `"agendada"` (activa, no cancelada) — la cita SÍ existe de verdad en producción.
- `documento_paciente: "72302972"` — el documento del TITULAR (mismo documento que aparece con nombre explícito "Santander Olivero"/"santander olivero" en otras citas del mismo paciente en esta misma consulta), NO el de ninguna beneficiaria/hija. Confirma el bug reportado: la reserva quedó a nombre de quien escribe el chat, no de la persona para quien pidió la cita.
- Hallazgo lateral (INFERENCIA, no pedido explícitamente pero visible en la misma respuesta): varias citas recientes creadas desde este canal de chat (`CITA-680ca01ca2`, `CITA-9782ae7085`, `CITA-78ebe0b8cd`, entre otras con `created_at` de hoy) tienen `nombre_paciente: ""` y `telefono: ""` — vacíos — a diferencia de citas más antiguas que sí traen nombre/teléfono reales. Podría indicar que el flujo actual de `agendar_cita` (vía `HrmmAppointmentService`/tools) no está enviando `nombre_paciente`/`telefono` al crear la cita en hrmm-backend, independientemente del bug de beneficiario — vale la pena que alguien lo revise por separado, no se investigó a fondo en esta sesión (fuera del alcance pedido).

## Arquitectura / estructura encontrada

Dos caminos de entrada distintos y NO simétricos en `domains/health/gateway.py`, ambos alcanzables desde `handle_inbound_message`:

1. **Conversación ya abierta** (`find_open_context` devuelve algo): `handle_patient_message` → `HealthBrain.interpret()` → dispatch por etapa, CON el chequeo centralizado `_detectar_interrupcion_de_contexto` del recado 047 corriendo en cualquier etapa (excepto `esperando_documento_beneficiario`/`esperando_confirmacion_beneficiario`).
2. **Solicitud nueva** (`find_open_context` devuelve `None`): `_enrutar_solicitud_nueva` → `classify_intent_or_none` (clasificador de intención simple, sin `_PARA_OTRO`) → `_resolver_por_intent` → para `PROGRAMAR_CITA`, `_resolver_programar_cita`, que si el catálogo tiene >1 servicio, pregunta servicio DIRECTO sin pasar por `HealthBrain.interpret()` en ese turno.

El recado 047 (y su predecesor 046) documentaron y corrigieron el hueco DENTRO del camino 1. El camino 2 nunca fue tocado por ninguno de los dos recados — y es exactamente el camino que se ejecuta cada vez que una conversación anterior ya cerró (lo normal después de CUALQUIER desenlace: reserva confirmada, declinada, o "no puedo ahora").

## Archivos importantes

- `/Users/enzoalfonso/Orangutan/icaco/domains/health/gateway.py`:
  - `handle_inbound_message` (línea ~486): decide entre camino 1 y camino 2 vía `find_open_context`.
  - `find_open_context` (línea ~393): verifica frescura de la Activity contra `_ACTIVITY_ESTADOS_CERRADOS` en cada llamada.
  - `_enrutar_solicitud_nueva` (línea ~609): clasifica con `classify_intent_or_none`, sin conocimiento de `_PARA_OTRO`.
  - `_resolver_programar_cita` (línea ~713): el bypass explícito de `HealthBrain.interpret()` está documentado en el comentario de las líneas ~734-738.
  - `_cerrar_si_definitivo` (línea ~876): cierre inmediato de la Activity apenas `management_status` llega a un desenlace definitivo.
  - `_ACTIVITY_ESTADOS_CERRADOS` (línea ~52).
- `/Users/enzoalfonso/Orangutan/icaco/domains/health/brain.py`:
  - `interpret()` (línea ~334): el chequeo centralizado del recado 047 vive aquí — solo se alcanza desde el camino 1.
  - `_detectar_interrupcion_de_contexto` (línea ~432), `_PARA_OTRO` (línea ~118, tupla de frases exactas — confirmado que "para mi hija" SÍ está en la lista, el matching de substring habría funcionado si esta función se hubiera llegado a llamar).
  - `_ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO` (línea ~145).
- `/Users/enzoalfonso/recado/047-interrupciones-de-contexto-en-cualquier-etapa.md`: el fix anterior, confirmado que su alcance real es solo el camino 1.
- `/Users/enzoalfonso/recado/048-saludo-sin-intencion-no-dispara-flujo-por-defecto.md`: el commit más reciente (`f040c9f`) antes de esta sesión, toca el mismo archivo `gateway.py` pero un problema distinto (saludo puro sin intención) — no relacionado con este hallazgo, pero mismo vecindario de código.

## Decisiones o conclusiones

- El fix del recado 047 es correcto para lo que se propuso corregir (interrupciones DENTRO de una conversación ya abierta) — no está roto, está incompleto frente al caso real de hoy.
- El caso real de hoy no es "el mismo bug que el 047 dijo haber corregido" en sentido estricto — es un bug HERMANO, en una capa distinta (`gateway.py` vs `brain.py`), con la misma clase de síntoma (beneficiario ignorado) pero un mecanismo de origen diferente (bypass de `HealthBrain.interpret()` en el primer turno de una solicitud nueva, no un hueco de cobertura por etapa dentro del Brain).
- No se implementó ninguna corrección en esta sesión — se investigó y diagnosticó únicamente, por pedido explícito del usuario ("NO CORRIJAS TODAVÍA").

## Problemas encontrados

1. **`_PARA_OTRO` no se evalúa en el primer turno de una solicitud nueva cuando el catálogo tiene más de un servicio** (Hallazgo A) — reproducido con evidencia de código, no con un test automatizado nuevo en esta sesión (no se escribió ningún test, por pedido explícito de no corregir todavía).
2. **Ninguna "ventana de gracia" tras cerrar una Activity** (Hallazgo B) — cualquier mensaje de seguimiento inmediato sobre la conversación recién cerrada (una corrección, una queja, un dato olvidado) se trata como 100% desconectado de ella.
3. **Posible bug lateral, no confirmado a fondo**: `nombre_paciente`/`telefono` vacíos en varias citas recientes creadas desde este canal (Hallazgo D) — podría ser un problema de mapeo en `HrmmAppointmentService`/la tool `agendar_cita`, no investigado en profundidad.

## Riesgos

- Mientras no se corrija el Hallazgo A, **cualquier** solicitud de cita que combine "primer mensaje de una conversación nueva" + "es para un beneficiario" seguirá reservando a nombre del titular por error — no es un caso raro, es el patrón más natural en que un paciente escribiría ese pedido (mensaje de apertura, no como interrupción a mitad de conversación).
- El Hallazgo B es un riesgo de experiencia de usuario más amplio, no exclusivo del caso beneficiario: cualquier corrección/queja/aclaración dicha inmediatamente después de un cierre de conversación se perderá o generará una Activity nueva no relacionada — riesgo de confusión y de citas duplicadas/erróneas (como ya pasó hoy).
- La cita `CITA-680ca01ca2` sigue activa (`estado: agendada`) a nombre del titular en vez de la hija — riesgo operativo real mientras no se decida si cancelarla/corregirla.

## Recomendaciones

RECOMENDACIÓN (no implementada, para decidir con el usuario):
- Opción simple y de bajo riesgo: cuando `_resolver_programar_cita` vaya a preguntar servicio (bypass de `HealthBrain.interpret()`), pasar igualmente el texto original por `_detectar_interrupcion_de_contexto` (o una versión reducida que solo chequee `_PARA_OTRO`, ya que las otras 4 categorías tienen menos sentido en un primer mensaje que aún no eligió nada) ANTES de decidir la etapa inicial — mismo patrón de "chequeo centralizado antes de cualquier dispatch" que ya usa `HealthBrain.interpret()`, aplicado también al camino de solicitud nueva.
- Para el Hallazgo B, evaluar una ventana de gracia corta (ej. permitir que el PRIMER mensaje inmediatamente posterior al cierre de una Activity todavía se enrute hacia esa Activity recién cerrada — quizás re-abriéndola o marcándola como "en corrección" — en vez de crear una nueva de inmediato) — requiere diseño explícito con el usuario, no es un cambio trivial de una línea como el de arriba.
- Para el hallazgo lateral D, revisar por separado (otra sesión) por qué `nombre_paciente`/`telefono` llegan vacíos a hrmm-backend en las citas recientes creadas por este canal.

## Información que debe conocer ChatGPT

- El proyecto `icaco` es la base de un motor conversacional multi-dominio (`core/`, `domains/health` es el único dominio con integración real probada contra `hrmm-backend`, otro proyecto de Orangutan en `/Users/enzoalfonso/Orangutan/hrmm`).
- Existe una serie larga y numerada de recados previos sobre este mismo dominio (`002` al `048` aprox., no todos revisados en esta sesión) — antes de proponer un diseño para las recomendaciones de arriba, conviene revisar los recados 013 (beneficiario original), 016 (patrón `etapa_antes_de_X` para retomar flujos), 046 y 047 (los más relacionados directamente).
- El branch de trabajo real (`main`, según `git log` de esta sesión) tiene el fix del recado 048 ya commiteado (`f040c9f`) pero el push de los commits del 047/048 estaba bloqueado por un "clasificador de modo automático" según el propio recado 048 — no se verificó en esta sesión si ese bloqueo sigue vigente.
- El secreto de canal de confianza (`BACKEND_TRUSTED_SECRET`) usado para consultar `GET /api/agenda/citas` vive en `hrmm/backend/.env` (no reproducido aquí) — cualquier verificación futura contra hrmm-backend real necesita ese mismo secreto.

## Preguntas pendientes

1. ¿Se cancela la cita `CITA-680ca01ca2` (Odontología, 2026-09-08, 08:00, documento 72302972) o se corrige/reasigna a la beneficiaria real? El usuario pidió explícitamente NO corregir nada todavía — queda pendiente su decisión.
2. ¿Se implementa la recomendación simple del Hallazgo A (chequear `_PARA_OTRO` también en `_resolver_programar_cita` antes de preguntar servicio) como corrección inmediata, o se espera a diseñar junto con la ventana de gracia del Hallazgo B como una sola corrección más completa?
3. ¿Vale la pena, en una sesión aparte, investigar a fondo por qué `nombre_paciente`/`telefono` llegan vacíos en las citas recientes creadas por este canal (Hallazgo D, lateral)?
4. Punto 4 original del usuario (fuzzy matching de fecha/hora, análogo al del recado 036 para servicios) — evaluado solo superficialmente en esta sesión, sin investigación de código dedicada: el patrón ya existe y probablemente sea trasladable (`difflib.SequenceMatcher`, mismo umbral/calibración que servicio), pero decidir el vocabulario de expresiones a cubrir ("el 9", "miércoles 9", "8" solo, "8:30 am") requeriría su propio recado de diseño, no se investigó el código de `_interpretar_fecha`/`_interpretar_horario` en esta sesión.
