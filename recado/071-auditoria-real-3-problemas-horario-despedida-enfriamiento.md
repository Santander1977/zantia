# 071 — Auditoría contra sistema real: 3 problemas (horario duplicado, despedida sin conversación no armaba el enfriamiento)

**Fecha**: 2026-09-10/11
**Rama**: `main` (base `73d3349`, recado 069 ya desplegado)
**Estado**: 3 causas raíz identificadas y corregidas, verificadas con datos REALES (hrmm-backend producción) y tiempo REAL (no simulado). **Nada comiteado todavía** — pendiente tu aprobación. Incluye el trabajo del recado 070 (selección de servicio por ordinal + aclaraciones con lista completa), que seguía sin comitear.

---

## 0. Sobre el método de prueba pedido — aclaración necesaria ANTES de todo lo demás

Pediste que probara "de forma autónoma" haciendo `POST` directo al webhook real de Telegram (`https://curson8n-zantia.byrp3l.easypanel.host/webhook/telegram`) con un payload sintético, y que leyera la respuesta real. Antes de intentarlo, leí `service/app.py:234-285` (el handler real de ese endpoint) para confirmar que el método funcionaría como se esperaba — y **no es así**, por una razón estructural, no por falta de esfuerzo de mi parte:

```python
mensaje = _canal_telegram.receive()
respuesta_texto = await _procesar_con_indicador_de_escritura(mensaje)
try:
    _canal_telegram.send(OutboundMessage(conversation_id=mensaje.conversation_id, text=respuesta_texto))
except TelegramChannelError as exc:
    ...
    return {"procesado": True, "respondido": False, "motivo": str(exc)}
return {"procesado": True, "respondido": True}
```

El `POST` al webhook **nunca devuelve el texto de la respuesta** en el HTTP response — el diseño (deliberado, recado 012, para que un fallo de ENTREGA nunca tumbe el procesamiento) es: procesar el mensaje, y **enviar la respuesta por separado** a través de la API real de Telegram (`sendMessage`) hacia el `chat_id` que venga en el payload. La única forma de VER el texto real sería leyendo ese chat de Telegram directamente — algo para lo que no tengo ninguna credencial ni herramienta (no tengo acceso a tu cuenta/chat de Telegram, y `getUpdates` no es una alternativa: es mutuamente excluyente con el modo webhook que el bot ya tiene configurado, y desactivarlo temporalmente para probar sería una acción sobre producción que no está autorizada sin pedirlo explícitamente).

Además, mandar un `POST` sintético con un `chat_id` inventado habría hecho que `_canal_telegram.send(...)` intentara de verdad entregarle un mensaje a un chat que no existe (fallando con un error de Telegram, sin decirme nada útil sobre el CONTENIDO); y usar un `chat_id` real que no es el tuyo sería enviar mensajes reales a un desconocido — no lo hice.

**Lo que sí hice en su lugar — la verificación más fuerte que de verdad tengo a mi alcance**: ejecuté el MISMO código de dominio (`HealthGateway`/`HealthBrain`, exactamente el mismo commit que ya está pusheado) pero conectado a:
- **hrmm-backend de PRODUCCIÓN real** (`HRMM_BACKEND_ENV=production`, con tu `HRMM_BACKEND_SECRET` real, mismo mecanismo ya usado y aprobado en el recado 068) — esto fue clave: **el Problema 1 solo se manifiesta con datos reales**, nunca con el catálogo ficticio de los tests (ver abajo).
- **la API real de Anthropic** (`HEALTH_BRAIN_TYPE=llm` + tu `ANTHROPIC_API_KEY` real, igual que tu `.env` de producción).
- **tiempo real** (`time.sleep()` de verdad, no timestamps simulados) para el enfriamiento de 2 minutos.

Esto ejerce el 100% de la lógica de negocio real (que es donde viven los 3 problemas reportados) contra sistemas reales — lo único que NO pude ejercer es la capa de transporte de Telegram en sí (parseo del JSON del webhook + el `sendMessage` final), que es un adaptador delgado, ya cubierto por su propia suite de tests (`test_telegram_channel.py`), y que ninguno de los 3 problemas reportados menciona.

**Lo único que de verdad no puedo confirmar yo mismo**: si el código EFECTIVAMENTE corriendo en EasyPanel ahora mismo es el commit `73d3349` (recado 069) o uno más viejo — no existe ningún endpoint de versión (confirmado en el recado 060) y no tengo credenciales de EasyPanel. Si quieres descartar esa posibilidad con certeza, lo único que necesito de ti (no es "probar", es leer un dato que ya tienes en pantalla) es el hash de commit que muestra el log de build exitoso que mencionaste — lo comparo directo contra `73d3349`.

---

## PROBLEMA 1 — Horario mostrando solo números, sin poder distinguir las opciones

### Reproducción con datos REALES (no simulados)

Corriendo el flujo real (servicio → fecha → horario) contra hrmm-backend de producción, para "Medicina General" el viernes 11 de septiembre de 2026:

```
=== Oferta de horarios reales ===
Para el Viernes 11 de septiembre, estos son los horarios disponibles:
1. 07:00 en Consultorio 2
2. 07:30 en Consultorio 2
3. 07:30 en Consultorio 1
¿Cuál prefieres?

=== ACLARACION de horario (respuesta ambigua) — ANTES DEL FIX ===
No logré identificar cuál prefieres:
1. 07:00
2. 07:30
3. 07:30
¿me confirmas si es la 1, la 2 o la 3?

=== Respuesta a '07:30' (AMBIGUO entre 2 reales) — ANTES DEL FIX ===
Creo que podrías referirte a más de uno de estos horarios:
1. 07:30
2. 07:30
¿Cuál de los dos prefieres?
```

La oferta ORIGINAL sí desambigua con el consultorio. Pero las 2 aclaraciones (incluida la que el recado 070 afirmó haber corregido) mostraban **líneas idénticas** ("07:30" dos veces) — exactamente lo que reportaste: números sin poder distinguir cuál era cuál.

### Causa raíz (con líneas exactas)

Dos médicos reales distintos, mismo servicio, misma fecha, **misma hora de inicio** (07:30) en consultorios distintos — un caso real perfectamente normal que **ningún catálogo ficticio de los tests tenía** (por eso nunca se reprodujo antes, ni con la suite completa en verde).

`domains/health/brain.py::_interpretar_horario` (antes del fix) reconstruía la lista de aclaración desde `datos["horas_ofrecidas"]` — **solo la hora, sin consultorio** (a diferencia de la oferta original, `_ofrecer_horarios`, que sí incluye el consultorio cuando hace falta). Con horas repetidas, la lista de aclaración quedaba con líneas duplicadas e indistinguibles.

**Hallazgo adicional de CORRECTITUD** (no solo de presentación): el camino de selección asistida por LLM (`_interpretar_seleccion_asistida_por_llm(texto, horas)`) usaba la hora bare como `id` de cada opción — con horas repetidas, un `id` duplicado rompe la garantía de `core/selection.py` de identificar una única opción real sin ambigüedad. Esto podía, en teoría, hacer que el mecanismo verificado "confirmara" una elección ambigua sin que el paciente hubiera sido realmente inequívoco.

### Corrección

- `_ofrecer_horarios` ahora guarda, junto a `horas_ofrecidas` (sin cambios): `horas_display_ofrecidas` (SIEMPRE con el consultorio, a diferencia de la lista bonita que lo omite cuando coincide) y `texto_horario_ofrecido` (el texto YA renderizado de la oferta original).
- `_emparejar_horario_por_texto` ahora acepta un parámetro `mostrar` opcional — los candidatos ambiguos se presentan con ese texto (desambiguado), nunca con la hora bare.
- La aclaración "no identificada" ahora reutiliza `texto_horario_ofrecido` directamente (la MISMA lista ya mostrada, garantizado idéntica) en vez de reconstruir una versión empobrecida.
- El camino LLM asistido ahora usa el `slot_id` real (siempre único) como `id` de selección, con el texto desambiguado como texto legible — cierra también el hallazgo de correctitud.

### Verificación

**Contra datos reales (después del fix)**:
```
=== ACLARACION de horario (respuesta ambigua) — DESPUES DEL FIX ===
No logré identificar cuál prefieres:
1. 07:00 en Consultorio 2
2. 07:30 en Consultorio 2
3. 07:30 en Consultorio 1
¿me confirmas si es la 1, la 2 o la 3?

=== Respuesta a '07:30' (AMBIGUO entre 2 reales) — DESPUES DEL FIX ===
Creo que podrías referirte a más de uno de estos horarios:
1. 07:30 en Consultorio 2
2. 07:30 en Consultorio 1
¿Cuál de los dos prefieres?

=== Elegir horario '1' por ordinal (confirmacion real) ===
¡Perfecto! Dame un segundo, voy a dejarlo reservado.
```

**Auditoría de los otros 2 (fecha y servicio), pedida explícitamente**: confirmado que NO tienen este problema — `fechas_ofrecidas` se construye con `sorted({o.date for o in opciones})` (un `set`, únicas por construcción); el catálogo de servicios (`CatalogMirror.listar_nombres()`) devuelve un nombre único por `servicio_id` real, sin duplicados posibles. Solo horario podía repetirse (misma hora, distinto consultorio).

**Tests automatizados**: `tests/domains/health/corpus_regresion/test_recado070_horario_duplicado_entre_consultorios.py` (4 tests, reproduce EXACTAMENTE el dato real de arriba con un catálogo ficticio que replica la duplicidad) + `test_seleccion_asistida_por_llm.py` actualizado (el `id_seleccionado_via_llm` ahora es el `slot_id`, no la hora bare — más correcto).

---

## PROBLEMAS 2 y 3 — Despedida/enfriamiento: UNA SOLA causa raíz para ambos

### Reproducción con TIEMPO REAL (no simulado)

Script con `time.sleep()` real, sin manipular ningún timestamp — **transcripción completa, ANTES del fix**:

```
[t=+0.0s] CIERRE: 'Fue un gusto atenderte. En 2 minutos estaremos disponibles
           nuevamente si necesitas algo más. ¡Hasta pronto!'
[t=+0.0s] INMEDIATO ("hola"): 'Buenas noches. Soy Andrés, tu asistente virtual
           para la gestión de tus citas médicas del Hospital Regional del
           Magdalena Medio. ¿Qué deseas hacer?
           1. Reservar una cita
           2. Reprogramar una cita
           3. Cancelar una cita
           4. Consultar mis citas
           5. Salir / terminar'
Esperando 60s reales...
[t=+60.0s] A LA MITAD ("sigues ahi?"): 'No logré identificar qué necesitas —
           puedes responder con el número o la palabra de una de estas
           opciones: [...]'
Esperando 50s reales mas (total ~110s)...
[t=+110.0s] CASI TERMINANDO ("hola de nuevo"): [mismo fallback genérico, sin bloqueo]
Esperando 15s reales mas (total ~125s)...
[t=+125.0s] PASADO EL ENFRIAMIENTO ("hola"): [mismo fallback genérico, sin bloqueo]
```

**Confirmado con evidencia real**: el enfriamiento de 2 minutos **nunca se activó, en ningún momento** — el "Hola" inmediato mostró el menú institucional COMPLETO, como si la despedida nunca hubiera ocurrido. Esto reproduce exactamente tu reporte ("el cierre sigue sin funcionar").

### Causa raíz exacta (con líneas de código)

**Ambos problemas (2 y 3) tienen la MISMA causa raíz** — no son dos bugs distintos.

El despliegue del recado 069 SÍ es correcto (confirmado: `git rev-parse HEAD` y `git ls-remote origin refs/heads/main` coinciden en `73d334953acd4974087b292b6f78731b5401ccd1`) — la lógica de despedida/formato/enfriamiento del 069 en sí misma funciona (ya lo había verificado con 12 mensajes variados en ese recado). El problema real es más sutil: **el mecanismo de enfriamiento nunca se ARMABA** para el camino de despedida MÁS COMÚN de todos.

`domains/health/gateway.py::_resolver_por_intent`, rama `RequestIntent.SALIR` (alcanzada cuando el paciente se despide **SIN haber abierto antes una conversación** — "gracias"/"chao"/"5"/"salir" como primer mensaje, o después de que una conversación anterior ya cerró — el escenario más natural y frecuente de todos). El código, tal cual estaba, traía este comentario explícito:

> *"Deliberadamente NO se toca `_cierre_reciente` acá (a diferencia de `_cerrar_si_definitivo`): esta despedida ya ES el saludo corto de cierre — el siguiente 'Hola' debe volver a ver el guion institucional completo, no la variante corta de regreso."*

Esa decisión es del **recado 060** — tomada ANTES de que el **recado 067** construyera el enfriamiento de 2 minutos encima de esa MISMA estructura (`gateway._cierre_reciente`). Nadie revisó esa decisión al agregar el enfriamiento: como esta rama nunca escribía en `_cierre_reciente`, el chequeo de enfriamiento en `handle_inbound_message` (que LEE esa misma estructura, `gateway.py:661-666`) nunca encontraba nada que bloquear. Resultado: cualquier mensaje inmediatamente después de ESTA despedida (la más común) se procesaba con toda normalidad, sin bloqueo, sin informar tiempo restante — exactamente el Problema 3, y la causa de que el Problema 2 ("sigue sin funcionar") pareciera cierto pese a que el texto de despedida en sí era correcto.

**Por qué ningún test lo atrapó antes**: los tests de los recados 067/069 (incluidos los 12 casos que verifiqué manualmente en el 069) SIEMPRE abrían una conversación primero ("necesito una cita") antes de despedirse — ese camino pasa por `_cerrar_si_definitivo` (Activity real cerrándose), que SÍ armó `_cierre_reciente` correctamente desde el recado 067. El hueco real estaba específicamente en la despedida SIN conversación previa — un camino que ningún test había ejercitado junto con el enfriamiento hasta esta prueba en tiempo real.

### Corrección

`_resolver_por_intent`, rama `RequestIntent.SALIR`, ahora también arma `gateway._cierre_reciente[patient_reference] = (datetime.now(timezone.utc), nombre, True)` — mismo patrón que `_cerrar_si_definitivo`. El comentario original del recado 060 ("el siguiente Hola debe ver el guion completo") queda **superado** por tu propio requisito explícito del recado 069 (punto 4: *"pasados los 2 minutos... saludo corto si aplica"*) — un saludo corto tras el enfriamiento es ahora el comportamiento CORRECTO, no una regresión de lo que pediste en el 069.

### Verificación — MISMO script, tiempo real, DESPUÉS del fix

```
[t=+0.0s] CIERRE: 'Fue un gusto atenderte. En 2 minutos estaremos disponibles
           nuevamente si necesitas algo más. ¡Hasta pronto!'
[t=+0.0s] INMEDIATO: 'Aún estamos en pausa — podremos atenderte de nuevo en
           2 minutos y 0 segundos.'
Esperando 60s reales...
[t=+60.0s] A LA MITAD: 'Aún estamos en pausa — podremos atenderte de nuevo en
           1 minuto y 0 segundos.'
Esperando 50s reales mas (total ~110s)...
[t=+110.0s] CASI TERMINANDO: 'Aún estamos en pausa — podremos atenderte de
           nuevo en 0 minutos y 10 segundos.'
Esperando 15s reales mas (total ~125s, pasado el enfriamiento)...
[t=+125.0s] PASADO EL ENFRIAMIENTO: '¡Buenas noches! ¿Puedo ayudarte en algo más?'
```

**Confirmado con tiempo real, sin ninguna simulación**: bloqueo inmediato, cuenta regresiva real y precisa en 2 momentos intermedios distintos (60s y 110s reales, exactamente como pediste), y transición correcta a contacto normal (saludo corto) pasados los 2 minutos exactos.

**Tests automatizados** (con manipulación determinista del timestamp, para que la suite siga siendo rápida — la prueba que encontró y confirmó el fix del bug SÍ fue en tiempo real, documentada arriba): `tests/domains/health/corpus_regresion/test_recado070_despedida_sin_conversacion_no_armaba_enfriamiento.py` (2 tests) + 2 tests preexistentes actualizados en `test_pregunta_correo_y_despedida.py` (`test_reproduce_bucle_real_de_despedida_sin_conversacion_abierta`, `test_hola_despues_de_opcion_salir_activa_el_enfriamiento_y_luego_saludo_corto`, renombrado — su premisa original quedó superada por este mismo fix).

---

## Hallazgo adicional, transparente, NO corregido (fuera del alcance de los 3 problemas reportados)

Durante la investigación con LLM real encontré que, **dentro de una conversación YA ABIERTA** en la etapa de elegir FECHA, si el paciente escribe el dígito suelto "5" y una de las fechas ofrecidas cae justo en el día-del-mes 5, el sistema selecciona esa fecha en vez de interpretar "5" como el atajo de menú "Salir" — porque el atajo numérico del menú (`_MENU_OPCIONES`) **solo aplica cuando no hay conversación abierta** (por diseño, desde el recado 059/067; dentro de una etapa activa, "5" naturalmente puede significar el día 5 del mes, la hora, etc.). Esto es una coincidencia narrow (requiere que el día-del-mes ofrecido sea literalmente 5) y es el comportamiento **de diseño ya documentado**, no algo que el fix de despedida debiera cubrir — lo señalo por transparencia, tal como pediste, no lo oculto. Si te parece que amerita corrección, dímelo explícitamente y lo evalúo aparte.

---

## Estado de la suite completa

**563 passed, 15 skipped, 0 failed** (`.venv/bin/pytest -q`) — incluye los tests nuevos de este recado y del recado 070 (que seguía sin comitear).

```
git status --short
 M .ai/CONVERSATION_COVERAGE.md
 M domains/health/brain.py
 M domains/health/gateway.py
 M tests/domains/health/test_auditoria_salida_y_cierre_formal.py
 M tests/domains/health/test_pregunta_correo_y_despedida.py
 M tests/domains/health/test_seleccion_asistida_por_llm.py
?? tests/domains/health/corpus_regresion/test_recado070_despedida_sin_conversacion_no_armaba_enfriamiento.py
?? tests/domains/health/corpus_regresion/test_recado070_horario_duplicado_entre_consultorios.py
?? tests/domains/health/corpus_regresion/test_recado070_seleccion_de_servicio_por_ordinal.py
?? tests/domains/health/test_aclaraciones_repiten_lista_completa.py
```

---

## Próximo paso

Nada se ha comiteado. Si apruebas el trabajo de este recado (071) junto con el del recado 070 (selección de servicio por ordinal + aclaraciones con lista completa, seguía pendiente):

1. Comiteo y pusheo todo junto, confirmando con `git ls-remote` + comparación de hashes.
2. La única acción manual que te queda a ti: dar clic en "Implementar"/"Redeploy" en EasyPanel — nada de escribir mensajes de prueba.
3. Si quieres, tras el redeploy, dime el hash de commit que muestra el log de build de EasyPanel (no una prueba, solo un dato que ya tienes en pantalla) y lo comparo contra el hash pusheado, para cerrar con certeza la pregunta de "¿el código desplegado es genuinamente el nuevo?" que ninguna llamada mía puede responder por sí sola.
