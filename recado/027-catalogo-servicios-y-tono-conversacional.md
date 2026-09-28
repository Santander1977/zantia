# 027 — Bug real del catálogo de servicios + pase de tono conversacional

**Fecha**: 2026-09-05
**Continúa**: recado 026 (misma conversación real de Telegram)

## PARTE 1 — Bug del catálogo de servicios

### Diagnóstico (respondiendo los 4 puntos pedidos)

**1. ¿Existía manejo de "consultar catálogo sin especialidad nombrada"?**
`[CONFIRMADO]` No existía en ninguna capa. `domains/health/intent.py:classify_intent` solo reconocía la frase de catálogo en tercera persona ("qué servicios **tienen**"), nunca en segunda persona real ("qué servicios **tienes**", "cuál tienes"). Y dentro de una conversación ya abierta, `HealthBrain` tampoco tenía NINGÚN patrón para esto — cualquier pregunta de catálogo caía al fallback genérico de sí/no o, peor, a la rama de reserva.

**2. ¿Se interpretó "cuál servicios tienes disponible" como el NOMBRE del servicio buscado?**
`[CONFIRMADO, pero la hipótesis original no era exacta]` — reproduje la conversación completa con un script (`domains/health/gateway.py` real, `MockAppointmentService`) y confirmé el mecanismo exacto:
- `classify_intent("Programar cuál servicios tienes disponible")` devolvía `PROGRAMAR_CITA` — no por interpretar el texto como nombre de servicio, sino porque la palabra suelta **"programar"** (en cualquier parte del mensaje) hacía match con `_PROGRAMAR`, sin que `_INFORMACION` (chequeada antes, pero con frases insuficientes) la interceptara primero.
- `domains/health/gateway.py:_nueva_activity_sintetica` asigna `service="medicina general"` **hardcodeado**, siempre, para CUALQUIER solicitud de "programar cita" nueva — independientemente de lo que el paciente haya escrito. El texto real del paciente nunca se usa para elegir el servicio.
- Con eso, `HealthBrain._ofrecer_disponibilidad` pedía disponibilidad para "medicina general" — si el catálogo real de `hrmm-backend` no tiene cupos para ese servicio en ese momento (o el nombre real no coincide), cae a "sin disponibilidad".

**3. Manejo agregado**: `intent.py` y `brain.py` ahora reconocen la pregunta de catálogo (frases en "tú": "qué servicios tienes", "cuál(es) servicio(s)", "cuál tienes", "servicios disponibles", etc.) y responden con `AppointmentService.list_services()` — el catálogo **real**, nunca inventado. Nuevo método `list_services()`:
- `CatalogMirror.listar_nombres()` — nombres reales ya sincronizados de `GET /api/agenda/servicios`.
- `HrmmAppointmentService.list_services()` — delega en el catálogo real.
- `MockAppointmentService.list_services()` — catálogo ficticio, separado de `_slots` (para no "perder" un servicio del catálogo solo porque se quedó sin cupos).
- Todo duck-typed (mismo criterio que `buscar_paciente`) — un `AppointmentService` que no lo implemente cae al mensaje genérico existente, nunca falla ni inventa nombres.

**4. Por qué mensajes distintos repetían el mismo mensaje fijo — corregido**
`[CONFIRMADO]` con logging manual turno a turno: NO era literalmente "una sola conversación atascada en un estado" — el Core reabre el ciclo automáticamente después de cada turno que termina en `RESPUESTA` (mecanismo YA EXISTENTE, `_normalizar_tras_turno`/`_reabrir_ciclo`, documentado desde antes). El problema real: **ninguna capa reconocía la pregunta de catálogo**, así que cualquier reformulación ("Cuál tienes") rebotaba entre el fallback genérico de sí/no y, si el paciente decía "sí", de vuelta al mismo "sin disponibilidad" para el servicio por defecto nunca confirmado. Con el fix del punto 3, una reformulación de catálogo ahora sí saca al paciente del bucle con una respuesta real y útil.

### Reproducción antes/después (script real, disponibilidad drenada a propósito)

```
ANTES:
>>> "Programar cuál servicios tienes disponible"
<<< "Por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde..."
>>> "Cuál tienes"
<<< "¿Te gustaría que te ayude a programar tu atención? Puedes responder sí o no."
>>> "Se más amable"
<<< "¿Te gustaría que te ayude a programar tu atención? Puedes responder sí o no."
>>> "Si"
<<< "Por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde..."

DESPUÉS:
>>> "Programar cuál servicios tienes disponible"
<<< "Estos son los servicios que tenemos disponibles: medicina general. ¿Te gustaría agendar una cita para alguno de ellos?"
>>> "Cuál tienes"
<<< "Estos son los servicios que tenemos disponibles: medicina general. ¿Te gustaría agendar una cita para alguno de ellos?"
```
("Se más amable"/"Si" sin disponibilidad real siguen mostrando el mensaje honesto de "sin cupos" — correcto y esperado, no es el bug reportado; ver nota de alcance abajo.)

### Hallazgo adicional encontrado al verificar (no reportado por el usuario, corregido igual)

Al revisar TODO el árbol del dominio buscando la frase prohibida "te contactamos" (para el pase de tono, parte 2), encontré una **tercera instancia** en `domains/health/gateway.py:_iniciar_verificacion_para_gestion` (sub-flujo de reprogramar-con-código-de-verificación, `HrmmAppointmentService` real) — "Por ahora no tengo otros horarios disponibles para reprogramar, te contactamos pronto." Esta rama es **más grave** que las dos ya corregidas en el recado 026: vive completamente fuera del Orchestrator/Core (documentado así a propósito, ver docstring del sub-flujo), así que `NoPrometerContactoGuardrail` **nunca la ve** — se le habría enviado esa frase a un paciente real TAL CUAL, sin ninguna red de seguridad. Corregida y con test nuevo (`test_reprogramar_sin_disponibilidad_no_promete_contacto`), ya que no tenía ninguna cobertura previa.

### Alcance explícitamente NO cubierto (decisión consciente, no descuido)

- El fallback de `classify_intent` para un mensaje que no matchea NADA sigue siendo `PROGRAMAR_CITA` por diseño ("el punto de entrada más seguro", documentado desde el origen). Un mensaje como "Se más amable" sigue cayendo ahí y, si no hay disponibilidad real, sigue mostrando "sin cupos". Rediseñar ese fallback es un cambio de alcance mayor, no pedido explícitamente — lo dejo señalado como observación para una futura decisión de producto, no lo implementé.
- No se implementó que el paciente pueda NOMBRAR un servicio real del catálogo por texto libre y que la reserva lo use (`_nueva_activity_sintetica` sigue asumiendo "medicina general" por defecto para toda solicitud de reserva nueva) — el pedido era listar el catálogo, no rediseñar la selección de servicio en la reserva. Señalado como mejora futura razonable, no implementada.

## PARTE 2 — Tono conversacional

### Regla seguida en cada cambio

Se preservó, verificado por grep antes y después de cada edición, que ninguna de las frases de `guardrails/rules.py:_PROMESAS_PROHIBIDAS` se reintrodujera, y se corrió la suite completa después de cada tanda de cambios (no solo al final) para detectar cualquier ruptura de inmediato en vez de acumular riesgo.

**Deliberadamente SIN tocar**: los mensajes de escalamiento (`_MENSAJE_ESCALAMIENTO_INBOUND`, `_MENSAJE_ESCALADO_ESTANDAR`/`_MENSAJE_ESCALADO_URGENTE` del Core, y el `modified_response` del guardrail) — son frases de seguridad, ancladas por varios tests con substrings exactos ("pasar tu caso al equipo"), y un mensaje de escalamiento prioriza claridad sobre calidez. También se dejó sin tocar el saludo outbound de `agent.py:contact_patient` (subsistema distinto, de demanda inducida, no el flujo reactivo que reportó el bug).

### Antes / Después (muestra de 8 mensajes clave, para tu revisión)

| # | Contexto | Antes | Después |
|---|---|---|---|
| 1 | Fallback de sí/no (se repetía literal turno tras turno) | "¿Te gustaría que te ayude a programar tu atención? Puedes responder sí o no." | "¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir." |
| 2 | Sin disponibilidad (recado 026 ya le había quitado la frase prohibida; ahora más empático) | "Por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde para revisar de nuevo." | "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde y lo revisamos de nuevo con gusto." |
| 3 | Ofrece disponibilidad real | "Perfecto, estas son las opciones disponibles: {...}. ¿Cuál prefieres?" | "¡Perfecto! Estas son las opciones disponibles: {...}. ¿Cuál te queda mejor?" |
| 4 | Identidad confirmada (gateway.py) | "Gracias, ya confirmé tu identidad. ¿En qué te puedo ayudar? Puedo programar, reprogramar, cancelar o consultar una cita." | "¡Gracias! Ya confirmé tu identidad. ¿En qué te puedo ayudar hoy? Puedo programar, reprogramar, cancelar o consultar una cita tuya." |
| 5 | Pedir documento (gateway.py, primer contacto por Chatwoot/Telegram) | "Antes de continuar, ¿me confirmas tu número de documento de identidad? Lo necesito para consultar tus datos de forma segura." | "¡Hola! Antes de seguir, ¿me confirmas tu número de documento de identidad? Lo necesito para consultar tus datos con seguridad." |
| 6 | Paciente declina | "Entiendo, gracias por tu tiempo. Si cambias de opinión, aquí estamos." | "Entiendo perfectamente, gracias por tu tiempo. Si más adelante cambias de opinión, aquí voy a estar." |
| 7 | Pide información no autorizada (diagnóstico, etc.) | "Eso no lo tengo disponible por este canal — no puedo darte información clínica que no esté autorizada aquí. Si quieres, puedo poner en contacto al equipo para resolver esa duda." | "Uy, esa parte no te la puedo compartir por este canal — no puedo darte información clínica que no esté autorizada aquí. Si quieres, con gusto pongo tu duda en manos del equipo para que te ayuden con eso." |
| 8 | "¿Por qué me contactan?" — **corregido también el hallazgo de la frase prohibida que se había quedado sin arreglar en el recado 026** | "Te contactamos por {motivo}. La idea es ayudarte a programar tu atención cuando te quede cómodo. ¿Te gustaría revisar opciones de horario?" | "Con gusto te cuento: esto es sobre {motivo}. La idea es ayudarte a programar tu atención cuando te quede cómodo. ¿Revisamos juntos las opciones de horario?" |

El resto de los mensajes tocados (confirmación de beneficiario, selección de turno, reprogramar/cancelar, wizard de "olvida mi información", catálogo de servicios) siguen el mismo criterio — ver diff completo en `domains/health/brain.py` y `domains/health/gateway.py`.

### Un test tuvo que actualizarse (esperado, no un descuido)

`tests/domains/health/test_beneficiario_gestion.py::test_mock_appointment_service_ignora_la_frase_de_beneficiario` verificaba el texto EXACTO del mensaje #1 de la tabla — precisamente el que pediste variar. Cambié la aserción para verificar la GARANTÍA real (sigue siendo la misma pregunta cerrada de sí/no) en vez del texto literal memorizado, que es justo lo que pediste dejar de hacer.

## Verificación

- **184 tests recolectados, 182 pasando + 2 deshabilitados a propósito** (sin cambios en los deshabilitados). Antes de esta sesión: 174.
- Tests nuevos: `tests/domains/health/test_catalogo_servicios.py` (5), `test_hrmm_appointment_service.py` (+2, `list_services`), `test_hrmm_gateway_verification.py` (+1, el hallazgo de la frase prohibida sin proteger).
- `tests/guardrails/test_guardrails.py::test_modifica_respuesta_con_promesa_prohibida` — **PASA sin cambios**: `NoPrometerContactoGuardrail` sigue interceptando una promesa prohibida si el Brain llegara a proponerla, ninguna lógica de guardrail se tocó.
- Grep final sobre `domains/`, `channels/`, `service/`, `core/`: cero ocurrencias de las frases de `_PROMESAS_PROHIBIDAS` fuera del propio `guardrails/rules.py` y los comentarios que las mencionan explícitamente.

## Pendiente de tu aprobación

Antes de dar esto por cerrado, por favor revisa la tabla de antes/después de la Parte 2 — si algún mensaje no te convence en tono o quieres ajustar alguno puntual, lo cambio sin tocar la lógica de nuevo.
