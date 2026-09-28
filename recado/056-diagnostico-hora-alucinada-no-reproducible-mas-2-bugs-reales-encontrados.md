# 056 — "07:30 alucinado": no reproducible con el código actual + 2 bugs reales encontrados al investigar

**Fecha**: 2026-09-07
**Estado**: Investigación exhaustiva completa. **No se pudo reproducir el resultado exacto reportado con el código actual.** Se encontraron y corrigieron 2 bugs reales, distintos, durante la investigación. 452 passed, 8 skipped (439 previas + 13 nuevas). Cero regresiones. Incluye 2 llamadas reales verificadas contra la API de Anthropic. **Cancelación de la cita real pendiente de tu código de verificación** (ya enviado).

---

## Resultado de la investigación: honestidad ante todo

Reproduje el escenario EXACTO que describiste — horarios ofrecidos `["07:00", "08:00", "08:30"]`, respuesta del paciente `"8:30"` — de tres formas distintas:

1. **Unidad**: `_emparejar_horario_por_texto("8:30", ["07:00", "08:00", "08:30"])` → `("08:30", [])`. Correcto.
2. **Integración completa**: `HealthBrain._interpretar_horario("8:30", datos)` con el catálogo real de Odontología (mismo médico, mismo consultorio) → `tool_requerida["params"]["slot_id"]` apunta al slot de las 08:30. Correcto.
3. **Extremo a extremo con `HealthAnthropicBrain` + una llamada REAL a Claude** (redactando el mensaje de oferta, exactamente como en producción con `HEALTH_BRAIN_TYPE=llm`) → la oferta redactada por Claude real dice "07:00, 08:00 y 08:30" (coincide con tu transcripción), y la reserva resultante sigue apuntando correctamente a las 08:30.

**En los tres casos, el resultado es correcto — nunca reproduje una reserva a las 07:30.** No voy a presentarte una "corrección" para un mecanismo que no logré demostrar que esté roto en el código actual — eso sería inventar una causa raíz, exactamente lo que este proyecto evita en todo lo demás.

### Evidencia real que SÍ encontré (relevante, pero no concluyente sobre la causa)

`GET /api/agenda/citas` (documento 72302972) confirma que `CITA-9782ae7085` (Odontologia, 2026-09-09, **07:30**, Consultorio 4, CONFIRMED) es real. Investigando el estado real de `agenda.disponibilidad` para ese servicio/fecha en hrmm-backend, encontré que el slot de las 07:30 para ese médico **está marcado "Reservado" — exactamente por esta misma cita**, y es cronológicamente el turno inmediatamente posterior a las 07:00 y anterior a las 08:00. Esto significa que, en el momento real de la conversación, 07:30 SÍ era una opción "Libre" disponible — la pregunta sin responder es si de verdad no se mostró (como dice tu transcripción) o si en algún punto de la conversación real sí apareció y se perdió en la narrativa del reporte. No pude reconciliar esto con ningún mecanismo del código actual que explique "input 8:30 → slot 07:30".

### Hipótesis más probable (sin poder confirmarla desde aquí)

La producción desplegada en EasyPanel puede no reflejar el código más reciente de este repositorio — de hecho, confirmé al recibir tu siguiente mensaje que el **recado 055 (formato de listas) nunca llegó a commitearse/pushearse** pese a que ya lo habías aprobado (mi error: quedó pendiente cuando llegaron mensajes nuevos encima). Si esto pasó con 055, es objetivamente posible que otras correcciones de hoy (051, 052, 053) tampoco estuvieran desplegadas en el momento exacto de esta conversación real, y que el comportamiento reportado corresponda a una versión de código anterior a alguna de ellas — no puedo confirmar esto sin acceso a los logs/versión exacta del contenedor desplegado en ese momento.

## 2 bugs reales encontrados durante la investigación (corregidos)

### 1. `_ofrecer_horarios` no ordenaba cronológicamente antes de tomar los 3 primeros

`AppointmentService.get_availability()` no garantiza ningún orden — confirmado leyendo el JSON real de `GET /api/agenda/disponibilidad`: para un servicio con VARIOS médicos, los bloques llegan agrupados de forma que NO es estrictamente cronológica (ej. las 07:00 de 3 médicos distintos, consecutivas, antes que las 07:30 de cualquiera de ellos). `_ofrecer_horarios` tomaba `[:3]` de esa lista sin ordenar — a diferencia de `_ofrecer_fechas`, que sí ordena (`sorted(...)`). Corregido: ahora `_ofrecer_horarios` también ordena por hora antes de recortar a 3, garantizando SIEMPRE mostrar los 3 horarios cronológicamente más próximos, sin depender del orden que entregue el backend. No explica por sí solo el hallazgo reportado (Odontología solo tiene un médico, y en ese caso el orden natural sí era cronológico) — pero es un riesgo real para cualquier servicio con más de un médico, y directamente relacionado con la clase de bug investigada.

### 2. "8 de la mañana" (con "ñ", como se escribe correctamente en español) nunca matcheaba ninguna hora

Encontrado escribiendo las pruebas de robustez que pediste. `_sin_tildes` (usada para normalizar el texto del paciente antes de comparar) **deliberadamente nunca toca la "ñ"** — mismo criterio ya documentado en este archivo para no confundir "año"/"ano". Pero `_formas_hora_nivel1` genera la forma idiomática hardcodeada como `"de la manana"` (sin "ñ"). Un paciente que escribiera correctamente "8 de la **mañana**" nunca coincidía con ninguna forma, cayendo siempre al fallback de aclaración — no una alucinación, pero sí una UX rota para una forma de escribir perfectamente natural y correcta. Corregido con una normalización local ñ→n **solo dentro de esta comparación puntual** (`_horario_coincide_nivel1`) — `_sin_tildes` global no se tocó, sigue protegiendo "año" en cualquier otro lugar del archivo.

## Cancelación de la cita real

Código de verificación **ya enviado** al correo real en archivo para el documento 72302972 (`d***@barranquillasegura.com`). Pendiente de que me compartas el código de 6 dígitos para ejecutar `cancel_appointment_verified` sobre `CITA-9782ae7085` y confirmarte con una consulta posterior.

## Verificación (los 5 puntos pedidos)

Todo en `tests/domains/health/test_horario_sin_cero_inicial_nunca_alucina.py` (13 tests + 2 gateados):

1. ✅ Reproducción exacta del escenario: `["07:00","08:00","08:30"]` + `"8:30"` → selecciona 08:30, nunca otro valor (unidad + integración).
2. ✅ Variantes sin cero inicial (`"8:00"`, `"8 am"`, `"8am"`, `"8 de la mañana"` — este último solo pasa tras el fix del bug 2 de arriba, `"8:30 am"`, etc.) — todas matchean correctamente contra opciones con cero inicial.
3. ✅ Sin ninguna coincidencia real (`"9:15"`) → pide aclaración, nunca inventa ni avanza.
4. ✅ 2 llamadas REALES contra la API de Anthropic: el escenario exacto reportado (con redacción real de Claude) y un caso que SÍ obliga a consultar el mecanismo del recado 052 (referencia posicional "la última que mencionaste", sin ningún nivel determinista que la reconozca) — ninguno de los dos alucina.
5. ✅ Suite completa: **452 passed, 8 skipped** — cero regresiones.

## Archivos tocados

- `domains/health/brain.py`: `_ofrecer_horarios` (ordena cronológicamente), `_horario_coincide_nivel1` (normaliza "ñ" localmente).
- Nuevo: `tests/domains/health/test_horario_sin_cero_inicial_nunca_alucina.py` (13 tests + 2 gateados).

## Pendiente de tu decisión / acción

1. **Necesito el código de verificación** para completar la cancelación real de `CITA-9782ae7085`.
2. Si tienes la transcripción completa (no solo el resumen), y puedes confirmar la hora exacta de build/deploy del contenedor de EasyPanel en el momento de esa conversación, ayudaría a confirmar o descartar la hipótesis de versión desplegada desactualizada — sin esa evidencia, este hallazgo queda [DESCONOCIDO], no [CONFIRMADO].
3. Revisar si quieres que commitee y pushee este trabajo (junto con el recado 055, pendiente desde antes).
