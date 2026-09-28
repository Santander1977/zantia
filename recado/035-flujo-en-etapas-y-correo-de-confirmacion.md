# 035 — Flujo de selección en 3 etapas + correo de confirmación (trabajo en curso, autónomo)

**Fecha**: 2026-09-06
**Continúa**: recados 026-034 (misma conversación real de Telegram)
**Modo de esta sesión**: el usuario se desconectó y pidió explícitamente seguir avanzando de forma autónoma, tomando las decisiones que normalmente se le habrían consultado, con 4 límites que se respetaron sin excepción (ver sección final). Todo lo de abajo está implementado, probado, y **sin commitear** — pendiente de su aprobación del tono al volver, mismo proceso que los recados 027/028/034.

## Redeploy de EasyPanel (antes de este trabajo)

El usuario pidió disparar el webhook de deploy real de EasyPanel (`http://82.25.86.200:3000/api/deploy/...`, copiado directo de su panel) para forzar que el commit `fdd94a9` (recado 032) quedara realmente corriendo en producción — la hipótesis del recado 034 era que el síntoma persistente ("Voy a reservarlo" nunca confirmaba) se debía a que el servicio desplegado no había recogido ese commit. Se hizo la petición (`curl`, respuesta `"Deploying..."`, HTTP 200) y el usuario confirmó después, desde el panel, que el despliegue quedó en verde. No se volvió a probar en Telegram todavía (el usuario se desconectó justo después) — **queda pendiente que él confirme si el síntoma del recado 034 quedó resuelto con el redeploy**, no se puede dar por cerrado sin esa prueba real.

## Nota aparte: mensaje descartado

A mitad de una sesión anterior llegó un mensaje sobre "orquestador_citas"/n8n que el usuario aclaró explícitamente que fue un error suyo, no dirigido a esta sesión — se descartó sin investigar, tal como pidió.

---

## PARTE 1 — Flujo de selección en 3 etapas separadas

### Diseño

Antes: un solo bloque combinaba fecha+hora+consultorio en una lista ("1) 2026-09-07 07:00 en Consultorio 2"). Ahora son 3 pasos secuenciales, cada uno una lista de un solo tipo de dato por línea — **todos consultando disponibilidad REAL de `AppointmentService.get_availability()`, nunca inventada**:

1. **PASO 1 — Servicio**: sin cambios de fondo (ya existía desde el recado 030, etapa `esperando_servicio` — se pregunta solo si el catálogo real tiene más de un servicio).
2. **PASO 2 — Fecha**: nueva etapa `esperando_fecha`. Se listan las fechas ÚNICAS con disponibilidad real para el servicio ya resuelto (máximo 3 — mismo tope que el resto del archivo, y `_elegir_opcion` solo reconoce ordinales 1ª/2ª/3ª), formateadas en español legible ("Lunes 7 de septiembre") con una tabla fija de días/meses — deliberadamente SIN `locale.setlocale` (no determinista entre entornos/contenedores).
3. **PASO 3 — Horario**: nueva etapa `esperando_horario`. Una vez confirmada la fecha, se listan los horarios reales de ESA fecha específica (filtrando `get_availability()` por `.date == fecha_elegida`) — nunca combinados con la fecha de nuevo.

### Implementación

`domains/health/brain.py`:
- `_ofrecer_disponibilidad` (recados 013/027) → renombrada y dividida en `_ofrecer_fechas` (PASO 2) + `_ofrecer_horarios` (PASO 3, nueva).
- `_interpretar_seleccion` (recados 013/027) → reemplazada por `_interpretar_fecha` (nueva, PASO 2 respuesta) + `_interpretar_horario` (PASO 3 respuesta, misma lógica de reserva/beneficiario/nombre/idempotencia que la vieja `_interpretar_seleccion`, solo que el `slot_id` ya viene acotado a servicio+fecha).
- Mismos llamadores de antes (rama `_es_afirmativo` del camino outbound, confirmación de beneficiario, `_interpretar_servicio`) ahora apuntan a `_ofrecer_fechas`.
- Nuevo helper `_formatear_fecha_humana` + 2 variantes de aclaración nuevas (`_VARIANTES_FECHA_NO_IDENTIFICADA`) siguiendo el mismo mecanismo de rotación del recado 034.
- `agent.py:_sincronizar_activity` — el mapeo de `management_status` para la vieja etapa `"esperando_seleccion"` (→ `ENGAGED`) se actualizó a las dos etapas nuevas (`"esperando_fecha"`, `"esperando_horario"`), mismo significado, sin cambios de comportamiento.

**Deliberadamente NO tocado** (mismo criterio de escritura de recados anteriores — alcance explícito del pedido, "al pedir una cita"): el flujo de **reprogramar** una cita ya existente (`_iniciar_reprogramacion`/`_interpretar_seleccion_reprogramacion`) sigue con la lista combinada de antes — el pedido fue específicamente sobre RESERVAR, no sobre reprogramar. Señalado aquí para que quede como decisión consciente, no como omisión.

### Migración de tests (50 tests en 17 archivos)

Cambiar el flujo de 1 paso a 3 rompió, como era de esperar, todos los tests que asumían la lista combinada de antes ("opciones disponibles" en un solo turno) — 50 tests en 17 archivos, confirmado corriendo la suite completa justo después de implementar el rediseño (176 pasando + 50 fallando + 2 deshabilitados = 228 recolectados). Se actualizaron metódicamente los 17 archivos, insertando el turno adicional de elegir fecha donde correspondía, sin cambiar ninguna otra aserción de fondo (guardrails, `management_status`, `appointment_id`, idempotencia, recordatorios, beneficiario, olvido de identidad — todo se revisó y sigue intacto). **Ninguna garantía de fondo se perdió, solo se ajustó el número de turnos que cada flujo necesita.**

---

## PARTE 2 — Correo de confirmación tras reservar/cancelar/reprogramar

### Confirmación previa del usuario (decisión de producto, no verificable desde este repo)

Antes de implementar, encontré evidencia real que contradecía la premisa: en las citas reales del documento 72302972, el campo `correo` venía `null` en las 2 citas creadas por ZANTIA pero con un valor real en las otras 2 (de otro canal) — indicando que `correo` es un dato POR SOLICITUD, no algo que hrmm-backend resuelva solo con el documento. Se lo planteé al usuario antes de escribir nada; **confirmó explícitamente que sabe, por fuera de este repo, que hrmm-backend envía el correo de confirmación igual** — se implementó el mensaje genérico tal como se pidió originalmente, sin condicionarlo.

### Implementación — las 3 acciones reales

Misma frase en los 3 lugares (duplicada a propósito entre `agent.py` y `gateway.py`, con comentario cruzado para mantenerlas en sync si se cambia la redacción):

1. **Reservar** (`agent.py`, el mismo punto donde ya se agrega "¡Listo! Quedó confirmado...", recado 032) — cubre tanto Mock como `HrmmAppointmentService` real, ya que reservar nunca pasa por el sub-flujo de verificación.
2. **Cancelar** (`gateway.py:_procesar_intento_de_codigo`, sub-flujo real de verificación por código) — además se agregó el nombre del paciente (recado 034) a este mensaje, que no lo tenía todavía.
3. **Reprogramar** (mismo lugar, rama `else`) — igual, con nombre.

Ejemplo real (reserva, con nombre):
> "¡Perfecto, Enzo! Dame un segundo, voy a dejarlo reservado. ¡Listo! Quedó confirmado: medicina general el 2026-09-05 a las 09:00 en Sede Norte. Te enviamos un correo de confirmación con todos los detalles."

Ejemplo real (cancelación, con nombre):
> "Listo, Enzo, tu cita quedó cancelada. Te enviamos un correo de confirmación con todos los detalles."

### Fuera de alcance, deliberadamente

El flujo de **cancelar/reprogramar vía `HealthBrain`/Mock** (`_cancelar` en `brain.py`, alcanzable solo con `MockAppointmentService` — nunca con Hrmm real, que siempre pasa por el sub-flujo de verificación) no recibió el mensaje de correo: ese camino nunca es el que usa un paciente real, y tocarlo habría sido alcance no pedido. Señalado explícitamente, no un descuido.

---

## Verificación

- **Test 1** (`test_flujo_en_3_etapas_filtra_correctamente_sobre_lo_ya_elegido` + `test_elegir_la_segunda_fecha_ofrece_horarios_de_esa_fecha_no_de_la_primera`): confirma con `FakeHttpClient` que elegir la fecha A muestra horarios reales de A (nunca los de B) y viceversa, y que el `slot_id` finalmente reservado corresponde exactamente a fecha+hora elegidas — no una coincidencia de índice.
- **Test 2/3** (`test_correo_de_confirmacion_tras_reserva_real`, `..._cancelacion_real`, `..._reprogramacion_real`): las 3 acciones reales, contra `HrmmAppointmentService`/`CatalogMirror` reales vía `FakeHttpClient`, terminan con la frase de correo — incluyendo el sub-flujo real de verificación por código para cancelar/reprogramar.
- Test adicional: fecha no identificada no asume ninguna y permite reintentar (mismo criterio de "nunca inventar" ya establecido en todo el archivo).
- Suite completa final: **234 tests pasando + 2 deshabilitados a propósito** (228 recolectados justo tras el rediseño, con 50 rotos por migrar + los 6 nuevos de este recado = 234). Cero regresiones de fondo — todo lo roto era exclusivamente por el cambio deliberado de número de turnos.
- Guardrails e identidad corridos explícitamente por separado: 27 pasando + 1 deshabilitado, sin cambios.
- Grep final de las frases de `_PROMESAS_PROHIBIDAS`: cero ocurrencias nuevas.

## Límites respetados sin excepción (pedido explícito del usuario)

1. **Ninguna escritura real contra producción de hrmm-backend** en esta sesión — todo el trabajo de este recado corrió contra `FakeHttpClient`/`MockAppointmentService`. La única interacción con la red real fue el propio webhook de redeploy, pedido explícitamente antes de empezar este trabajo.
2. **Ningún despliegue nuevo en EasyPanel** — el único disparado fue el que el usuario pidió explícitamente al principio.
3. **Nada commiteado ni pusheado** — todo el código y los tests quedan listos en el árbol de trabajo, a la espera de la aprobación de tono del usuario.
4. **Todo documentado aquí** para que el usuario pueda ponerse al día sin perder nada.

## Pendiente de tu vuelta

1. **Confirmar en Telegram** si el redeploy resolvió el síntoma del recado 034 (reserva sin confirmar) — no se pudo re-probar en esta sesión porque implica una interacción real con el bot de Telegram, no algo que se prueba con FakeHttpClient.
2. **Aprobar el tono** de los mensajes nuevos (fechas en español, horarios, correo de confirmación con/sin nombre) antes de commitear — ejemplos completos arriba.
3. Nada bloqueante encontrado que requiriera detenerse — todo lo pedido en Partes 1 y 2 quedó implementado y probado.
