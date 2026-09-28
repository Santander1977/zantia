# RECADO PARA CHATGPT

Fecha: 2026-09-07
Proyecto: icaco (ZANTIA — dominio salud, `domains/health`)
Tema: Reconocimiento flexible de fecha/horario en `HealthBrain._interpretar_fecha`/`_interpretar_horario` — mismo principio de tolerancia ya aplicado al fuzzy matching de servicio (recado 036).
Objetivo de la investigación/trabajo: corregir un bug real confirmado en producción — el paciente solo podía elegir fecha/horario por el número de la opción ("1"/"2"/"3"), no repitiendo la fecha/hora tal cual se le mostró — implementar, verificar con evidencia real y documentar.

---

## Resumen ejecutivo

`domains/health/brain.py:_interpretar_fecha`/`_interpretar_horario` ahora reconocen, además del ordinal ya existente (`_elegir_opcion`, sin cambios), texto libre que repita la fecha/hora ofrecida: día de la semana solo, número de día del mes solo, fecha completa tal como se mostró (fecha), y hora completa/hora sola/con meridiano (horario). Mismo criterio de "palabras clave, no NLU real" que el resto del archivo (`.ai/RISKS.md` R-13) — nunca se inventa ninguna fecha/hora, solo se reconoce texto contra las opciones REALES ya ofrecidas.

Diseño en dos niveles de especificidad por criterio (más seguro primero, se detiene en el primer nivel que produzca algún candidato — 1 = match claro, 2+ = ambigüedad genuina, nunca se elige por el paciente). 36 tests nuevos, todos pasando. Suite completa: **390 passed, 4 skipped** (354 previas + 36 nuevas) — cero regresiones. Ningún guardrail tocado (confirmado con `git diff --stat -- guardrails/`, vacío).

## Hallazgos

Ninguno nuevo — el bug reportado (solo se reconocía el ordinal) se confirmó leyendo el código real de `_interpretar_fecha`/`_interpretar_horario` (ambas llamaban solo a `_elegir_opcion`, que únicamente matchea "1"/"primera"/"2"/"segunda"/"3"/"tercera" — ver `domains/health/brain.py:_elegir_opcion`, sin tocar) — consistente con lo reportado por el usuario, no hizo falta más diagnóstico.

## Arquitectura / estructura encontrada

Nuevas funciones en `domains/health/brain.py`, todas de nivel de módulo (no duplican nada existente, mismo criterio que `_emparejar_servicio_por_similitud` del recado 036):

- `_dia_semana_normalizado`/`_mes_normalizado`/`_dia_del_mes`: derivan las 3 piezas de texto reconocibles de una fecha ISO real, sin tildes, en minúsculas.
- `_fecha_coincide_nivel1(texto, fecha)`: día del mes + (mes O día de semana) presentes en el texto (con límites de palabra, `\b...\b`, para no confundir "7" con "17"/"70") — cubre "7 de septiembre", "lunes 7", "lunes 7 de septiembre", "día 7 de septiembre". Estructuralmente casi imposible de ambigüar (dos fechas reales nunca comparten día+mes).
- `_fecha_coincide_nivel2(texto, fecha)`: día de la semana solo, o día del mes solo — más laxo, sí puede colisionar.
- `_emparejar_fecha_por_texto(texto, fechas)`: prueba nivel 1, si no hay match prueba nivel 2; devuelve `(fecha, [])` si hay un único candidato, `(None, [candidatos])` si hay 2+ (ambiguo), `(None, [])` si no hay ninguno — mismo contrato que `_emparejar_servicio_por_similitud`.
- `_formas_hora_nivel1(hora_24)`: variantes de texto con precisión de minuto/meridiano de una hora real ("07:00" -> "07:00", "7:00", "7:00am", "7:00 am", "7 am", "7am", "7 de la mañana" cuando los minutos son :00).
- `_hora_solo_normalizada(hora_24)`: la hora sola, sin minutos ("07:00"/"07:30" -> "7") — nivel 2, más laxo.
- `_horario_coincide_nivel1`/`_horario_coincide_nivel2`/`_emparejar_horario_por_texto`: mismo patrón que fecha, sobre `datos["horas_ofrecidas"]` (nuevo, paralelo a `datos["opciones_horario"]` por índice — se agrega en `_ofrecer_horarios`, la hora REAL de cada slot ya ofrecido).

`_interpretar_fecha`/`_interpretar_horario`: primero `_elegir_opcion` (ordinal, sin tocar); si no matchea, el nuevo matcher de texto libre; si hay candidatos ambiguos, nuevas variantes rotativas `_VARIANTES_FECHA_AMBIGUA`/`_VARIANTES_HORARIO_AMBIGUO` (mismo patrón que `_VARIANTES_SERVICIO_AMBIGUO`, recado 036, placeholder `{opciones}`); si no hay ningún match, el fallback de siempre (`_VARIANTES_FECHA_NO_IDENTIFICADA`/`_VARIANTES_SELECCION_NO_IDENTIFICADA`, recado 034, sin cambios).

Para horario, `_interpretar_horario` mapea la hora textual reconocida de vuelta al `slot_id` real vía `horas.index(hora_elegida)` — seguro porque `_emparejar_horario_por_texto` solo devuelve una hora única cuando exactamente UNA entrada de `horas_ofrecidas` coincide (si hubiera dos entradas con el mismo valor de hora, el conteo de candidatos sería 2, tratado como ambigüedad genuina, nunca llega a `.index()`).

## Archivos importantes

- `/Users/enzoalfonso/Orangutan/icaco/domains/health/brain.py`:
  - Funciones nuevas insertadas justo después de `_formatear_fecha_humana` (día/mes/hora, matchers de 2 niveles).
  - `_VARIANTES_FECHA_AMBIGUA`/`_VARIANTES_HORARIO_AMBIGUO` (nuevas, junto a `_VARIANTES_SERVICIO_AMBIGUO`).
  - `_ofrecer_horarios`: agrega `datos["horas_ofrecidas"]`.
  - `_interpretar_fecha`/`_interpretar_horario`: lógica de 3 vías (ordinal -> texto libre -> ambiguo/fallback).
- Nuevo: `/Users/enzoalfonso/Orangutan/icaco/tests/domains/health/test_reconocimiento_flexible_fecha_horario.py` (36 tests).

## Decisiones o conclusiones

- El ordinal sigue siendo SIEMPRE la primera vía probada — cero riesgo de romper el comportamiento ya probado (confirmado: los tests preexistentes de fecha/horario, no tocados, siguen pasando exactos).
- Ambigüedad nunca se resuelve adivinando — mismo principio que servicio (recado 036) y que el resto del proyecto (el Brain propone, nunca asume). Verificado con un caso real construido a propósito (Lunes con 08:00 y 08:30, "8" ambiguo entre ambos).
- Caso ambiguo de FECHA no se pudo reproducir a través del catálogo real de 3 fechas consecutivas ofrecidas hoy (nunca hay dos fechas ofrecidas el mismo día de semana o mismo día del mes con esa ventana) — se verificó `_emparejar_fecha_por_texto` a nivel de unidad con dos fechas reales construidas a mano (dos lunes, en semanas distintas — escenario posible con la ventana de disponibilidad de 90 días del recado 050). Mismo criterio que otros tests de este archivo que llaman funciones internas directo cuando el escenario no es reproducible a través del flujo completo con datos reales de hoy.
- `_hora_solo_normalizada`/nivel 2 de horario es, a propósito, el ÚNICO punto de este cambio con riesgo real de ambigüedad en producción hoy (dos horarios ofrecidos pueden compartir la misma hora con minutos distintos, ej. 07:00/07:30 — visto en la disponibilidad real de HRMM) — por eso se cubrió con un test dedicado, no solo teórico.

## Verificación (los 5 puntos pedidos)

Todo en `tests/domains/health/test_reconocimiento_flexible_fecha_horario.py`, contra `HrmmAppointmentService` real con `FakeHttpClient` (catálogo/disponibilidad reales, no inventados):

1. ✅ `test_fecha_reconocida_en_las_4_formas` (parametrizado ×20): las 3 fechas reales del catálogo (Lunes/Martes/Miércoles), cada una con ordinal, día de semana solo (con/sin "el"), día del mes solo (con/sin "el"/"día"), y fecha completa tal cual se mostró (con y sin tilde en "miércoles").
2. ✅ `test_horario_reconocido_en_multiples_formas` (parametrizado ×12): texto completo ("09:00", "8:00 am"), hora sola inequívoca ("9", "10"), y con meridiano/idiomático ("9 am", "9:00 am", "9 de la mañana") — verificado con la reserva REAL completada (`slot_id` correcto en la cita creada contra `FakeHttpClient`, mensaje "confirmado").
3. ✅ `test_horario_ambiguo_pide_aclaracion_en_vez_de_adivinar`: "8" entre 08:00/08:30 -> pide aclaración mostrando ambas horas reales, NO reserva nada; aclarando con "08:30" completo SÍ avanza y reserva el slot correcto. `test_fecha_ambigua_a_nivel_de_unidad_pide_aclaracion`: dos fechas reales el mismo día de semana -> ambiguo con "lunes" solo; deja de serlo con más contexto ("7 de septiembre"/"14 de septiembre").
4. ✅ `test_fecha_no_reconocida_usa_fallback_normal`/`test_horario_no_reconocido_usa_fallback_normal`: texto sin ninguna forma reconocible -> mismo mensaje de aclaración rotativo de siempre (recado 034), etapa sin avanzar, nada elegido.
5. ✅ Suite completa: **390 passed, 4 skipped** (354 previas + 36 nuevas) — cero regresiones.

## Problemas encontrados

Ninguno nuevo (fuera del propio bug reportado, ya corregido).

## Riesgos

- Igual que el resto del dominio: matching por palabras clave/substring, no NLU real (`.ai/RISKS.md` R-13) — un paciente que use una expresión de fecha/hora genuinamente distinta a las cubiertas ("pasado mañana", "en la tarde" sin especificar hora) sigue cayendo al fallback de siempre, sin degradar nada (comportamiento idéntico a antes de este recado para esos casos).
- El nivel 2 de fecha (día de semana solo, o día del mes solo) puede colisionar con ventanas de disponibilidad más largas (recado 050 extendió la prueba a 90 días) — cubierto por la detección de ambigüedad, no por prevención; el paciente real vería una pregunta de aclaración extra en ese caso, nunca una elección equivocada.

## Recomendaciones

Ninguna pendiente — alcance cerrado, cubre exactamente lo pedido.

## Información que debe conocer ChatGPT

- Continúa la serie de recados sobre `domains/health/brain.py` — recados 030 (fuzzy servicio, precedente directo de este mismo patrón), 034 (variantes rotativas de fallback, reutilizadas sin cambios), 035 (asistente de reserva en etapas, donde viven `_interpretar_fecha`/`_interpretar_horario`), 050 (ventana de gracia — sin relación directa con este recado, mismo archivo).
- `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración real del repo (confirmado, no tocado por este trabajo) — el hallazgo del recado 050 sobre el `.env` LOCAL de esta máquina con `HEALTH_BRAIN_TYPE=llm` sigue vigente y sin resolver, ese archivo no se tocó en esta sesión tampoco.

## Preguntas pendientes

1. ¿Se commitea y pushea este trabajo?
