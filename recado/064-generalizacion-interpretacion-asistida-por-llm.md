# 064 — Generalización de la interpretación asistida por LLM a cualquier punto de espera (DISEÑO, para tu aprobación)

**Fecha**: 2026-09-10
**Estado**: Implementado y probado (incluidas 3 llamadas reales a la API de Anthropic). **Sin commitear — a la espera de tu aprobación explícita**, tal como pediste.

---

## 0. Resumen de una línea

`core/selection.py` (recado 052) **no cambió nada** — es genuinamente genérico y ya soportaba esto. Lo que faltaba era conectarlo a más puntos: `domains/health/config.py` ahora expone `build_selection_proposer()` (mismo gate `HEALTH_BRAIN_TYPE=llm`/`ANTHROPIC_API_KEY` de siempre, extraído para reutilizarse), y `domains/health/gateway.py` lo usa como ÚLTIMO recurso en 3 puntos nuevos (wizard de código, wizard de identidad, fallback de menú) — sumados a los 2 que ya lo usaban (fecha/horario, servicio — recados 051/052/036), da **5 puntos reales** cubiertos por el mismo mecanismo.

## 1. El patrón que se generaliza (`core/selection.py`, recado 052) — sin tocar

Ya lo revisé a fondo. `interpret_selection(free_text, options, proposer)`:
1. Recibe una lista de `SelectionOption(id, text)` — las opciones REALES de este turno.
2. Le pide al `proposer` (el LLM) que proponga un `id`.
3. **Verifica que ese `id` esté literalmente en la lista real** — si no está (alucinación), si hay ambigüedad, si no hay proposer, o si la llamada falla: `None`, nunca una excepción sin manejar, nunca una interpretación inventada.
4. Solo entonces el dominio usa el `id` devuelto — tan determinista como si el paciente hubiera tecleado el ordinal exacto.

Esto es EXACTAMENTE el patrón pedido para generalizar, y no necesita ningún cambio: una "opción" no tiene que ser una fecha o un slot — puede ser una **categoría de interrupción** (`"salir"`, `"reenviar"`, etc.) igual de bien. La verificación es idéntica en ambos casos.

## 2. Diseño — 3 piezas nuevas, cero piezas nuevas en `core/`

### Pieza 1 — `build_selection_proposer()` (`domains/health/config.py`)

Extraída del interior de `build_health_brain` (antes solo se construía ahí, inline). Mismo criterio exacto: `HEALTH_BRAIN_TYPE=llm` + `ANTHROPIC_API_KEY` configurada -> `AnthropicSelectionProposer` real; cualquier otro caso -> `None`, con `logger.warning` si `HEALTH_BRAIN_TYPE=llm` mal configurado. **Ningún env var nuevo.** `build_health_brain` ahora la llama internamente (mismo comportamiento, cero duplicación de la lógica de activación).

### Pieza 2 — Wizards (`_clasificar_interrupcion_wizard_o_llm`, `gateway.py`)

```python
def _clasificar_interrupcion_wizard_o_llm(gateway, texto):
    categoria = _clasificar_interrupcion_wizard(texto)   # determinista+fuzzy (062/063), gratis, sin red
    if categoria is not None:
        return categoria
    return _clasificar_interrupcion_wizard_via_llm(texto, gateway.selection_proposer)  # ÚLTIMO recurso
```

Las 6 "opciones" que ve el LLM: las 5 categorías reales ya existentes (`salir`/`reenviar`/`pregunta_correo`/`consulta_citas`/`emocional`) más una sexta explícita, **`"es_el_dato"`** — "el mensaje parece ser el código/documento que se le pidió, no ninguna interrupción". Incluirla mejora la precisión del LLM (le da una salida explícita de "ninguna de las anteriores" en vez de forzarlo a elegir entre 5 categorías de interrupción) y se trata exactamente igual que `None` en el código que llama: **el LLM NUNCA interpreta ni modifica el valor del código/documento en sí** — solo decide si el mensaje es una interrupción o no. Si dice "es_el_dato" (o no propone nada, o falla, o no hay proposer), el mensaje sigue cayendo, sin cambios, al matching determinista de código/documento de siempre — el que de verdad valida contra hrmm-backend.

Reemplaza `_clasificar_interrupcion_wizard(text)` por `_clasificar_interrupcion_wizard_o_llm(gateway, text)` en AMBOS wizards (`_procesar_intento_de_codigo`, `_gestionar_identificacion`) — una sola línea cada uno, cero duplicación de las 5 categorías ni de sus respuestas (siguen siendo las MISMAS funciones de los recados 062/063).

### Pieza 3 — Fallback de menú (`_clasificar_solicitud_nueva_via_llm`, `gateway.py`)

Mismo mecanismo, aplicado a `_enrutar_solicitud_nueva` (sin conversación abierta todavía). Las "opciones" acá son los **5 ids reales de `_MENU_OPCIONES`** (reutilizados tal cual, nunca un mapeo paralelo) más `"emocional"`:

```python
_CATEGORIAS_MENU_LLM = {
    "1": "quiere reservar o agendar una cita nueva",
    "2": "quiere reprogramar una cita que ya tiene",
    "3": "quiere cancelar una cita que ya tiene",
    "4": "quiere consultar o ver las citas que ya tiene",
    "5": "quiere salir o terminar, no necesita nada más por ahora",
    "emocional": "expresa una emoción, malestar o frustración, sin pedir ninguna acción concreta",
}
```

Si el LLM propone "1"-"5" (verificado, id real), se despacha por `_resolver_por_intent` — EXACTAMENTE el mismo camino que si el paciente hubiera tecleado el ordinal. Si propone "emocional", una respuesta breve de acompañamiento + el menú de nuevo. Se llama SOLO después de agotar TODO lo determinista existente (`_interpretar_opcion_menu`, `classify_intent_or_none` — incluido su propio fallback a PROGRAMAR_CITA cuando el texto "tiene señal de intención", recado 056 — y `_es_despedida`).

**Hallazgo al diseñar los tests** (documentado con honestidad, no oculto): `classify_intent_or_none` ya tiene un fallback amplio (`_tiene_senal_de_intencion`, recado 056) que captura la MAYORÍA de mensajes con alguna palabra de pedido ("quiero", "podrías", "por favor", "me gustaría", etc.) como PROGRAMAR_CITA — así que este nuevo mecanismo de menú, en la práctica, solo se ejerce para mensajes genuinamente ambiguos SIN ninguna de esas palabras (ej. quejas indirectas, preguntas formuladas sin verbos de pedido). Es un alcance más angosto de lo que asumí al empezar a diseñar los tests — lo señalo explícitamente porque preferí decírtelo a que pareciera que este punto cubre más de lo que realmente cubre en la práctica de hoy.

### Wiring completo — `service/app.py`

```python
_gateway = build_health_gateway(
    ...,
    selection_proposer=build_selection_proposer(),
)
```

Una línea. Mismo gate, mismo momento de arranque que `_appointment_service`.

## 3. Por qué es seguro — análisis explícito

- **Nunca cambia EJECUCIÓN, solo INTERPRETACIÓN** (requisito 4 central): en ningún punto el resultado de una clasificación LLM llama directamente a `book_appointment`/`cancel_appointment_verified`/`confirm_verification_code`/`marcar_verificado`. Lo más que hace es (a) decidir CUÁL categoría de interrupción mostrar (todas son respuestas de solo-lectura o de reenvío, nunca una escritura), o (b) en el menú, arrancar el MISMO flujo que ya arrancaba un ordinal tecleado a mano — nunca salta ningún paso de verificación real más adelante.
- **`interpret_selection` es la única puerta** — nunca se usa `proposer.propose(...)` directo en ningún punto nuevo; siempre pasa por la verificación de `core/selection.py`.
- **Por qué los wizards NO pasan por `SeleccionAsistidaPorLLMNoVerificadaGuardrail`** (la segunda capa de defensa que sí protege a `HealthBrain`): los wizards (`_pending_verifications`/`_pending_identity`) son, por diseño desde su creación (recado 009/012), independientes de `ConversationState`/`Orchestrator` — NUNCA producen un `BrainOutput` ni pasan por ningún guardrail de Core, con o sin este recado. Ese guardrail es "defensa en profundidad" explícitamente documentada como redundante si el dominio ya verifica bien (y `interpret_selection` YA verifica de forma completa e idéntica) — así que no hay ningún hueco de seguridad nuevo, pero lo señalo explícitamente para que quede auditable, no asumido en silencio.
- **Default de hoy: cero cambios de comportamiento.** Sin `HEALTH_BRAIN_TYPE=llm`/`ANTHROPIC_API_KEY` (el estado real de producción hoy, confirmado en recados anteriores), `selection_proposer` es `None` en todos los wizards y en el gateway — `interpret_selection` devuelve `SelectionResult(None, "none")` de inmediato, sin ninguna llamada de red. La suite completa (505 tests) lo confirma sin ningún cambio de comportamiento.

## 4. Ejemplos de texto REALES (llamadas reales a Claude, no simulados)

### Wizard de código de verificación
```
Sistema: [...] 5. Salir / terminar Listo, te enviamos un código a tu correo
         (a***@dominio.com) para confirmar. Escríbelo aquí para continuar
         cuando lo tengas.
Paciente: oye disculpa, se me hizo tarde y ya ni sé si quiero seguir con esto, mejor no
Sistema: De acuerdo, no seguimos con esto por ahora. ¿En qué más te ayudo?
         1. Reservar una cita
         2. Reprogramar una cita
         3. Cancelar una cita
         4. Consultar mis citas
         5. Salir / terminar
```
Ninguna regla de `_SALIR_WIZARD` contiene "mejor no" ni "ya ni sé si quiero seguir" — Claude real clasificó correctamente la intención de salir en lenguaje genuinamente libre.

### Wizard de identidad de canal
```
Paciente: perdón, ¿a qué dirección de correo me mandaron eso?
Sistema: Te enviamos el código a tu correo (a***@dominio.com). Cuando lo
         tengas, escríbelo aquí para continuar.
```

### Fallback de menú (sin conversación abierta)
```
Paciente: oye cuentame que tengo agendado por ahi
Sistema: Aquí tienes tu 1 cita activa:
         1. medicina general — Jueves 10 de septiembre, 09:00, Consultorio 3
```

Los 3 usan datos sintéticos de prueba (`FakeHttpClient`, nunca red real contra hrmm-backend, nunca un paciente real) — solo la llamada a la API de Anthropic es real.

## 5. Verificación

**Suite completa**: `505 passed, 12 skipped` (498 previas + 7 tests deterministas nuevos; 12 skipped = 9 de siempre + 3 reales, que solo se activan con `ZANTIA_RUN_REAL_LLM_TESTS=1`). Cero regresiones.

**`tests/domains/health/test_interpretacion_asistida_generalizada.py`** (archivo nuevo):
1. `test_menu_reconoce_lenguaje_libre_variado_via_llm` / `test_wizard_codigo_reconoce_lenguaje_libre_via_llm` / `test_wizard_identidad_reconoce_lenguaje_libre_via_llm` — punto 1 (5 puntos: menú, wizard código, wizard identidad — servicio y fecha/horario YA cubiertos por recados 036/051/052, no duplicados).
2. `test_menu_sin_selection_proposer_mantiene_comportamiento_de_siempre` / `test_menu_rechaza_propuesta_alucinada_del_llm` — punto 4 (sin cambios de comportamiento sin proposer, y rechazo de alucinaciones).
3. `test_llm_nunca_ejecuta_una_accion_real_sin_el_codigo_verificado` / `test_llm_nunca_confirma_identidad_sin_el_codigo_real` — punto 2 (anti-bypass): un proposer que SIEMPRE dice "es_el_dato" o que alucina, y aun así un código incorrecto se sigue rechazando contra el backend real, uno correcto se sigue aceptando — la clasificación nunca sustituye la verificación real.
4. `test_real_wizard_codigo_reconoce_lenguaje_libre` / `test_real_wizard_identidad_reconoce_lenguaje_libre` / `test_real_menu_reconoce_lenguaje_libre` — punto 3 (3 llamadas reales, ejecutadas en esta sesión, ver sección 4 arriba con las transcripciones reales).

## 6. Archivos tocados (sin commitear)

- `domains/health/config.py` — `build_selection_proposer()` extraída; `build_health_brain` refactorizado para reutilizarla.
- `domains/health/gateway.py` — campo `selection_proposer` en `HealthGateway`; `build_health_gateway` acepta el parámetro; `_clasificar_interrupcion_wizard_o_llm`/`_clasificar_interrupcion_wizard_via_llm`/`_CATEGORIAS_WIZARD_LLM` (wizards); `_clasificar_solicitud_nueva_via_llm`/`_CATEGORIAS_MENU_LLM`/`_respuesta_expresion_emocional_menu` (menú); conectado en los 3 puntos.
- `service/app.py` — `build_selection_proposer()` pasado a `build_health_gateway`.
- `tests/domains/health/test_interpretacion_asistida_generalizada.py` — nuevo, 10 tests (7 deterministas + 3 reales).
- Ningún cambio en `core/selection.py`, `.env.example` (ningún env var nuevo), ni en `_clasificar_interrupcion_wizard`/`_CONSULTA_CITAS_EXISTENTES`/etc. de los recados 062/063 (reutilizados tal cual).

## 7. Lo que este recado NO hace (alcance deliberadamente acotado)

- No conecta esto a `_detectar_interrupcion_de_contexto` (brain.py, recados 047/053) — esa función ya vive DENTRO de una conversación con `ConversationState`/guardrails reales, y ya tiene su propia cobertura (determinista, más `AnthropicResponseDrafter` para el tono). Mezclar ambos mecanismos en el mismo punto no se pidió explícitamente y merece su propio análisis — señalado, no implementado.
- No agrega un endpoint/mecanismo para que el LLM "redacte" una respuesta más humana MÁS ALLÁ de las plantillas ya existentes (recados 062/063) — la generalización de HOY es de CLASIFICACIÓN (qué categoría es este mensaje), no de REDACCIÓN. Las plantillas de respuesta para cada categoría ya son cálidas y ya vuelven al contexto (ver recados 062/063) — extender también la redacción con `AnthropicResponseDrafter` dentro de los wizards es una decisión aparte, porque esos wizards no pasan por ningún guardrail que verifique que el texto redactado preserva el contenido (ver sección 3) — lo señalo como posible trabajo futuro, no lo implementé sin que lo pidieras.

## 4bis. Texto EXACTO y completo de las 3 llamadas reales (verbatim, tal como las devolvió el sistema)

### 1. Wizard de código de verificación — "mejor no" reconocido como salir

```
Paciente: quiero cancelar mi cita
Sistema: Buenas noches. Soy Andrés, tu asistente virtual para la gestión de tus citas
médicas del Hospital Regional del Magdalena Medio. ¿Qué deseas hacer?
1. Reservar una cita
2. Reprogramar una cita
3. Cancelar una cita
4. Consultar mis citas
5. Salir / terminar Listo, te enviamos un código a tu correo (a***@dominio.com) para
confirmar. Escríbelo aquí para continuar cuando lo tengas.

Paciente: oye disculpa, se me hizo tarde y ya ni sé si quiero seguir con esto, mejor no
Sistema: De acuerdo, no seguimos con esto por ahora. ¿En qué más te ayudo?
1. Reservar una cita
2. Reprogramar una cita
3. Cancelar una cita
4. Consultar mis citas
5. Salir / terminar
```
(El primer mensaje del sistema concatena el saludo institucional + el inicio del wizard en una sola línea con un espacio, sin salto — es el comportamiento real de `handle_inbound_message`, no un artefacto de la captura.)

### 2. Wizard de identidad de canal — "¿a qué correo me mandaron eso?"

```
Paciente: perdón, ¿a qué dirección de correo me mandaron eso?
Sistema: Te enviamos el código a tu correo (a***@dominio.com). Cuando lo tengas,
escríbelo aquí para continuar.
```

### 3. Fallback de menú general — "qué tengo agendado"

```
Paciente: oye cuentame que tengo agendado por ahi
Sistema: Aquí tienes tu 1 cita activa:
1. medicina general — Jueves 10 de septiembre, 09:00, Consultorio 3
```

Los 3 casos usan `FakeHttpClient` (datos sintéticos de prueba, nunca red real contra hrmm-backend, nunca un paciente real) — solo la llamada a la API de Anthropic es real.

## 4ter. ¿Y el problema del correo de verificación (`send_verification_code`)?

**Es un mecanismo DISTINTO de R-21** (que sigue pendiente, dejado así por tu propia decisión explícita — ver recado 060) — vale la pena la distinción explícita:

- **R-21** = el correo de CONFIRMACIÓN tras reservar/cancelar/reprogramar (`enviar_confirmacion_email`, recado 054) — requiere que ZANTIA sepa el correo del paciente, y hoy nunca lo captura en la conversación. Sigue ABIERTO, sin tocar.
- **`send_verification_code`** = el mecanismo usado por AMBOS wizards (código de cancelar/reprogramar, recado 009; código de identidad de canal, recado 012/014) — envía un código al correo YA REGISTRADO del paciente en hrmm-backend (lo busca `buscar_paciente`, ZANTIA no necesita capturarlo). Es un endpoint DIFERENTE (`POST /api/agenda/verificacion/enviar`).

**Estado real de `send_verification_code`** `[CONFIRMADO leyendo recados 014/015]`: el endpoint existe y responde en producción real de hrmm-backend (`GET .../openapi.json` lo lista, verificado 2026-09-02). **Sigue PENDIENTE, sin resolver, desde el recado 015**: una prueba de extremo a extremo con un código REAL recibido en una bandeja de entrada real — nadie ha confirmado todavía que el correo efectivamente LLEGA (solo que el endpoint responde `200`/`{"enviado": true}`). Bloqueada por dos cosas: (a) esta máquina no tiene `HRMM_BACKEND_SECRET`/`HRMM_BACKEND_URL` reales en `.env` configurados para esa prueba específica, y (b) requiere que un humano revise una bandeja de correo real — ningún agente puede hacerlo. Hay un test gateado ya preparado desde el recado 015 (`test_identidad_canal_real_e2e`, `ZANTIA_RUN_REAL_HRMM_TESTS`) que nunca se ha ejecutado. **No lo investigué de nuevo en esta sesión** — no había ninguna señal de que estuviera roto, solo que nunca se verificó de punta a punta. Si tienes evidencia concreta de que un correo real no llegó, cuéntamela y lo investigo como hallazgo nuevo.

## 5bis. Nuevo caso real — dos preguntas fuera de contexto en la misma conversación, en medio de un flujo de selección

### Hallazgo antes de implementar

`[CONFIRMADO]` grep completo del repo: **no existe ninguna dirección real del hospital en ningún archivo** (código, config, docs) — solo su NOMBRE ("Hospital Regional del Magdalena Medio") en el saludo institucional. Confirma que la única respuesta correcta es la honestidad explícita (nunca inventar una dirección), tal como pediste verificar antes de implementar.

### Diseño

Dos categorías NUEVAS en `_detectar_interrupcion_de_contexto` (`domains/health/brain.py`, mismo mecanismo de los recados 047/053, misma prioridad que `_PIDE_INFO`): `_PREGUNTA_UBICACION_HOSPITAL` y `_PREGUNTA_CALIDAD_ATENCION`. Ninguna de las dos cambia `etapa`/`datos` — ambas reutilizan **tal cual** `_RECORDATORIO_BREVE_POR_ETAPA` (el MISMO diccionario que ya usa `_responder_expresion_emocional`, recado 053, nunca un texto de recordatorio nuevo) para volver naturalmente a la selección pendiente. El texto base determinista de cada una es 100% honesto por diseño — la llamada real a Anthropic (vía `HealthAnthropicBrain`/`AnthropicResponseDrafter`, recado 038, sin cambios) solo lo reformula con calidez, nunca le agrega hechos nuevos.

### Transcripción REAL completa (llamada real a Claude, `MockAppointmentService`, sin datos de un paciente real)

```
Turno 1
Paciente: sí
Sistema: Estas son las fechas que tenemos disponibles:
1. Sábado 5 de septiembre
2. Domingo 6 de septiembre
3. Lunes 7 de septiembre
¿Cuál te queda mejor?

Turno 2 — interrupción 1 (ubicación)
Paciente: oye, y ¿dónde queda el hospital exactamente?
Sistema: Buena pregunta, pero no tengo la dirección exacta registrada por este medio —
te recomiendo llamar directamente al hospital para confirmarla.
Retomando lo de antes, ¿cuál de las fechas que te compartí te queda mejor?

Turno 3 — interrupción 2, distinta, más adelante en la misma conversación (calidad de atención)
Paciente: otra cosa, ¿los médicos de ahí son buenos atendiendo?
Sistema: Es una pregunta válida, pero no tengo información objetiva para darte una
opinión sobre eso. Lo que sí puedo hacer con gusto es ayudarte a agendar tu atención
cuando quieras.
Volviendo a lo de antes, ¿cuál de las fechas que te compartí te queda mejor?

Turno 4 — el paciente retoma la selección EXACTAMENTE donde iba
Paciente: 1
Sistema: Para el sábado 5 de septiembre tengo estos horarios disponibles en Sede Norte:
1. 09:00
2. 10:00
¿Cuál prefieres?

Turno 5 — la reserva se completa normalmente
Paciente: 1
Sistema: ¡Genial, Paciente Ficticio! Dame un momento mientras te dejo la reserva lista.
¡Listo! Quedó confirmado: medicina general el 2026-09-05 a las 09:00 en Sede Norte.
```

**Confirmado con el estado real de `ConversationState`** (no solo por el texto): tras el turno 2 y tras el turno 3, `datos_recopilados["etapa"]` seguía siendo `"esperando_fecha"` y `fechas_ofrecidas` no cambió — el estado de la selección NUNCA se perdió, verificado programáticamente, no solo inferido del texto.

### Verificación de guardrails — punto 2 pedido explícitamente

`[CONFIRMADO]` con el `EventLog` real de esta conversación (auditoría real, no inferida): los 3 turnos (incluidos los 2 con pregunta fuera de contexto) evaluaron los 9 guardrails de Core, **los 9 en `ALLOW` los 3 turnos**, incluido explícitamente `tipo_de_pregunta_alterada -> "tipo de pregunta preservado"` (Claude reformuló pero conservó la pregunta de selección) y `opinion_personal -> "sin opinión personal detectada"` (correcto: nunca opinó). **Ningún guardrail intervino** — ninguno fue necesario.

**Límite honesto que quiero señalar, no ocultar**: `dato_inventado -> "sin datos inventados detectados"` en estos turnos es un ALLOW **trivial** — no declaré ninguna `VerificacionDeDatos` nueva para "la dirección del hospital" (a diferencia de fecha/hora, que sí tienen una lista real contra la cual verificar), porque no existe un patrón simple para detectar "una dirección inventada" en texto libre, a diferencia de una fecha/hora con formato conocido. Hoy la garantía de que nunca se invente una dirección descansa en (a) el texto base determinista SIEMPRE honesto, y (b) el contrato ya documentado de `AnthropicResponseDrafter` (reformula, nunca agrega hechos) — no en una verificación automática dedicada a esto. Lo señalo como límite real, no como algo ya resuelto — si quieres cerrarlo con un guardrail dedicado, es trabajo aparte.

### Archivos adicionales tocados (mismo diff sin commitear del recado 064)

- `domains/health/brain.py` — `_PREGUNTA_UBICACION_HOSPITAL`/`_PREGUNTA_CALIDAD_ATENCION` + sus 2 ramas en `_detectar_interrupcion_de_contexto`.
- `tests/domains/health/test_preguntas_sobre_hospital_en_flujo_activo.py` — nuevo, 1 test real (gateado).

**Suite completa tras esto**: `505 passed, 13 skipped` (12 previos + 1 real nuevo). Cero regresiones.

## 8. Pendiente de tu aprobación

Todo lo de arriba está implementado, probado (incluidas las 3 llamadas reales) y documentado. Sin commitear. Dime si apruebas para comitear y pushear, o si quieres ajustar algo del diseño antes (ej. el alcance del punto 7, o las categorías/textos exactos de las secciones 2-4).
