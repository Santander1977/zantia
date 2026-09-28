# 084 — Fix: variante de "consultar mis citas" sin respuesta, y "enviame un email" tras reservar caía al saludo genérico

**Fecha**: 2026-09-15
**Tipo**: corrección real, probada (código + tests unitarios + E2E local), **NO desplegada** — a la espera de confirmación explícita para commitear/pushear/redesplegar.
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Origen**: reportado por el usuario como "dos hallazgos reales de una conversación completa en producción, transcripción completa adjunta". **Aviso importante**: el mensaje del usuario incluía el placeholder literal `[pega aquí la transcripción completa que ya tienes]` sin reemplazar — la transcripción completa **nunca llegó a esta investigación**. Se le avisó al usuario al inicio de la sesión. Todo lo que sigue está basado en las **dos frases exactas** que sí llegó a dar, más evidencia de código real — nunca en una transcripción inventada.

## 0. Clasificación de afirmaciones (regla `discovery-antes-de-modificar.md`)

- `[CONFIRMADO]` las causas raíz de ambos hallazgos, leyendo el código y reproduciendo antes/después del fix con `pytest`/scripts puntuales (ver secciones 1 y 2).
- `[DESCONOCIDO]` el resto exacto de la conversación real (qué pasó antes/después de estas dos frases, si el paciente venía de un cierre reciente por otra vía, etc.) — nunca se rellenó ese hueco con una suposición.

## 1. Hallazgo 1 — "consultame las citas del ultimo mes"

### Pregunta del usuario
"Investiga por qué esta variante cae en un camino distinto al de 'consultar mis citas' exacto."

### Causa raíz `[CONFIRMADO]`
Dos capas de clasificación determinista, ambas ciegas a esta variante:

1. `gateway.py:_interpretar_opcion_menu` — reconoce la palabra suelta "consultar" con límite de palabra completa (`\bconsultar\b`). "**consultame**" es una palabra distinta (pronombre enclítico), nunca calza con ese regex — confirmado con `_interpretar_opcion_menu("consultame las citas del ultimo mes") -> None`.
2. `intent.py:_CONSULTAR` / `brain.py:_CONSULTA_CITAS_EXISTENTES` — ambas listas solo tenían formas **posesivas** ("consultar mi cita", "mis citas"). "las citas" (artículo definido, sin posesivo) nunca coincidía.

Con las dos capas deterministas en `None`, el enrutamiento depende POR COMPLETO del último recurso asistido por LLM (`_clasificar_solicitud_nueva_via_llm`) — eso es literalmente "un camino distinto": la forma exacta se resuelve gratis y con garantía en el primer chequeo; esta variante depende de si hay un `selection_proposer` configurado y de si el LLM la reconoce bien.

**Reproducido antes del fix** (sin proposer configurado, `MockAppointmentService`): `handle_inbound_message(..., "consultame las citas del ultimo mes")` devolvía **solo el saludo/menú institucional**, sin ninguna respuesta sobre las citas — la pregunta real del paciente quedaba sin contestar, en silencio.

No se confirmó (por falta de la transcripción real) si en producción, con `HEALTH_BRAIN_TYPE=llm` activo (confirmado configurado ahí por el recado 068), el LLM sí la clasificó y produjo el patrón "saludo + respuesta pegados en el mismo mensaje" que describe el usuario — el separador `\n\n` (recado 080) se aplica en un ÚNICO punto de inyección para CUALQUIER intent de primer contacto, así que ese patrón, si ocurrió, habría llevado el separador correcto igual: no se encontró ningún camino de código donde el saludo se pegue SIN el `\n\n`.

### Corrección
`intent.py:_CONSULTAR` y `brain.py:_CONSULTA_CITAS_EXISTENTES` (mismo criterio de duplicación ya documentado en ambos archivos) — se agregaron las 3 formas reales: `"consultame las citas"`, `"consultame mis citas"`, `"consultar las citas"`.

### Verificación
```
classify_intent_or_none_estricto("consultame las citas del ultimo mes") == RequestIntent.CONSULTAR_CITA  # antes: None
```
End-to-end (`MockAppointmentService`, sin conversación abierta): ahora responde con las citas reales (o "no tienes ninguna cita activa"), separadas del saludo por `\n\n`, EXACTAMENTE igual que "consultar mis citas".

## 2. Hallazgo 2 — "ok enviame un email" tras confirmar una reserva

### Pregunta del usuario
"Confirma si esa categoría sigue existiendo en el código, y si el patrón de reconocimiento es demasiado estricto para esta frase."

### Confirmación `[CONFIRMADO]`
La categoría (recado 058, `brain.py:_PREGUNTA_SOBRE_CORREO_ENVIADO`) **sigue existiendo y sigue conectada** — vive dentro de `_detectar_interrupcion_de_contexto`, reutilizada tanto por `HealthBrain.interpret()` (conversación abierta) como por `gateway.py:_evaluar_ventana_de_gracia` (el turno inmediato siguiente a un cierre, recado 050). El patrón de reconocimiento SÍ era demasiado estricto: las 12 frases originales estaban TODAS fraseadas como pregunta sobre algo ya hecho ("¿me enviaste...?", "¿llegó...?"), nunca como pedido/orden ("enviame", imperativo con pronombre enclítico). "enviame un email" no calzaba con ninguna.

### Cadena real reproducida `[CONFIRMADO]`
1. Reservar y confirmar una cita → `_cerrar_si_definitivo` cierra la Activity de inmediato (`ManagementStatus.APPOINTMENT_CONFIRMED`).
2. El mensaje siguiente ("ok enviame un email") ya no encuentra conversación abierta (`find_open_context -> None`).
3. Pasa por la ventana de gracia de un turno (`_evaluar_ventana_de_gracia`) — que reevalúa `_detectar_interrupcion_de_contexto`, pero (antes del fix) la frase no coincidía con nada ahí tampoco → devuelve `None`.
4. Cae a `_enrutar_solicitud_nueva` — tampoco reconoce nada (mismo motivo) → intent `None`.
5. Sin intent resuelto, y como la Activity se acaba de cerrar (arma `_cierre_reciente` con `_VENTANA_SALUDO_CORTO`), el turno devuelve el saludo CORTO genérico: **"¡Buenos días! ¿Puedo ayudarte en algo más?"** — exactamente el síntoma reportado.

### Corrección
`brain.py:_PREGUNTA_SOBRE_CORREO_ENVIADO` — se agregaron las formas de pedido: `"enviame"/"mandame"/"reenviame"` + `"el/un correo"/"email"`, y `"puedes enviarme"/"puedes mandarme"` + `"el correo"/"el email"`. El sistema no puede "reenviar" un correo bajo demanda (el único envío real ocurre dentro de `book_appointment`, recado 054) — la respuesta correcta a un PEDIDO de envío es la MISMA respuesta honesta ya existente sobre el estado real (`respuesta_pregunta_sobre_correo`), reutilizada tal cual, sin lógica nueva.

### Verificación
Reproducción de la secuencia real de 4 turnos (`necesito una cita` → `1` → `la primera` → `ok enviame un email`) con `MockAppointmentService`: antes del fix, `r4` era el saludo corto genérico; después del fix, `r4` es `"Buena pregunta — hoy no tenemos un correo tuyo registrado en este canal, así que no se envió ninguna confirmación por ese medio."` (estado real honesto, MockAppointmentService nunca recibe un correo).

## 3. Archivos tocados

- `domains/health/intent.py` — `_CONSULTAR` ampliado (3 frases nuevas) + comentario.
- `domains/health/brain.py` — `_CONSULTA_CITAS_EXISTENTES` (3 frases nuevas) y `_PREGUNTA_SOBRE_CORREO_ENVIADO` (11 frases nuevas) + comentarios.
- `tests/domains/health/test_saludo_institucional.py` — 1 test nuevo (`_interpretar_opcion_menu` NO reconoce "consultame..." — documenta por qué cae a la capa siguiente).
- `tests/domains/health/test_pregunta_correo_y_despedida.py` — 3 casos nuevos parametrizados ("ok enviame un email", "enviame el correo", "mandame el correo por favor") en el test de honestidad existente.
- `tests/domains/health/corpus_regresion/test_recado084_variantes_consulta_citas_y_pedido_correo.py` (nuevo, 4 tests) — reproduce ambos hallazgos de punta a punta vía `handle_inbound_message`, con las frases EXACTAS reportadas por el usuario.

## 4. Verificación de la suite completa

`.venv/bin/pytest -q`: **616 passed + 15 skipped**, cero regresiones. Confirmado que los tests nuevos son una prueba de regresión real (no un test que pasaría con cualquier código): corriendo el mismo archivo de corpus nuevo contra el código SIN el fix (`git stash` de `brain.py`/`intent.py`), **2 de los 4 tests fallan** exactamente como se esperaba (609 passed + 3 failed + 15 skipped) — los otros 2 (clasificación de unidad de `_interpretar_opcion_menu`) ya pasaban porque solo documentan un `None` que no cambió.

## 5. Siguiente paso

Reportar al usuario: ambos hallazgos confirmados con causa raíz real (nunca "el mismo bug de siempre reapareciendo" en el sentido literal de separador roto — el separador `\n\n` del recado 080 sigue intacto y se aplica de forma incondicional; la causa real en ambos casos fue una lista de frases determinista demasiado angosta para la forma gramatical real que usó el paciente). Aclarar explícitamente que la transcripción completa nunca llegó (placeholder sin reemplazar) y pedir que la reenvíe si hay más variantes reales para cubrir. Suite completa verde (616/616 + 15 skipped). Pendiente de autorización explícita para commitear.
