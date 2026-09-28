# 043 — `OpinionPersonalGuardrail` + corrección de fechas elípticas

**Fecha**: 2026-09-06
**Estado**: implementado, probado (305 passed, 3 skipped), **confirmado con una llamada real nueva**. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo, no se probó Telegram.
**Continúa**: recado 042 (2 hallazgos: pregunta de 1 sola opción [no corregido a propósito, baja prioridad] y hueco de cobertura en el guardrail de resistencia a desvío de tema).

---

## PARTE 1 — `OpinionPersonalGuardrail`

### Dónde vive y por qué

**Core** (`guardrails/rules.py`), junto a `FueraDeAlcanceGuardrail`. Justificación: la detección no depende de vocabulario de salud/citas — es agnóstica también de TEMA (ver diseño abajo), exactamente el mismo criterio que ya puso `FueraDeAlcanceGuardrail` en Core. Comparten el mismo mensaje de redirección (extraído a una constante de módulo, `_MENSAJE_REDIRECCION_FUERA_DE_ALCANCE`, para no duplicarlo).

### Diseño: agnóstico de TEMA, no una lista de "temas prohibidos"

Decisión deliberada: en vez de enumerar "política", "religión", "fútbol", etc. (una lista siempre incompleta y culturalmente sesgada), el guardrail detecta la **forma lingüística de una opinión en primera persona** — "yo creo que", "en mi opinión", "personalmente pienso", "estoy a favor de", etc. Esto cubre CUALQUIER tema en el que el Brain/LLM exprese una postura propia, sin necesidad de anticipar cuáles serán los temas reales que un paciente intente sacar a colación.

**Cuidado con falsos positivos** (requisito explícito): ninguno de los marcadores coincide con el reconocimiento empático de lo que el PACIENTE siente ("entiendo la frustración", "lamento que sea así") — esas frases son sobre el estado del paciente, nunca una postura del Brain sobre el tema en sí. Verificado explícitamente con el texto REAL del recado 042 (Caso 6, turno 1: `"¡Entiendo la frustración! Volviendo a lo tuyo, tengo estas fechas..."`) — no activa el guardrail.

### Prueba forzando el caso de falla (requisito explícito #4)

Con un drafter de prueba que simula a Claude cediendo:
> `"Yo creo que el presidente está haciendo un buen trabajo. Volviendo a tu cita: [texto base]"`

Corrido de extremo a extremo contra el `Orchestrator`/`GuardrailEngine` reales — el guardrail intercepta (`MODIFY`), la palabra "presidente" nunca llega al paciente, la respuesta final es el mensaje de redirección estándar.

### Nota importante — este es exactamente el caso que el recado 042 identificó sin protección

Antes de este recado, si el mensaje del paciente NO contenía ninguna frase de manipulación reconocible (como en el Caso 6 del recado 042 — presión cortés, sin "ignora tus instrucciones"), y el LLM hubiera cedido, **nada en el código lo habría corregido**. Ahora hay una segunda capa: aunque `FueraDeAlcanceGuardrail` no detecte nada en el mensaje entrante, `OpinionPersonalGuardrail` sigue revisando el texto YA REDACTADO — defensa en profundidad real, no solo confiar en que el prompt "por ahora" se sostiene (que es justo lo que el recado 042 demostró que SÍ pasaba, pero sin ninguna garantía estructural detrás).

---

## PARTE 2 — Corrección de fechas elípticas

### El problema (recado 042)

`_RE_FECHA` exigía que CADA fecha tuviera su propio `"de <mes>"` inmediatamente después. Claude a veces agrupa el mes una sola vez al final de una lista (`"sábado 5, domingo 6 o lunes 7 de septiembre"`, gramática elíptica perfectamente natural en español) — solo `"lunes 7 de septiembre"` se reconocía; `"sábado 5"` y `"domingo 6"` quedaban invisibles para el guardrail.

### Alternativa SIMPLE elegida (requisito #2: "si es complejo, evalúa una alternativa más simple y documenta por qué")

La propuesta original ("usar el mes de la fecha más cercana como referencia") requeriría reconstruir qué mes le "pertenece" a cada fecha corta de una lista — frágil (asume que todas comparten el mismo mes, hay que decidir si mirar hacia adelante o hacia atrás en el texto, más superficie para bugs nuevos).

**Alternativa elegida**: `_RE_FECHA` ahora reconoce TAMBIÉN la forma corta ("día de la semana + número", sin mes) como candidata — con la forma completa (con mes) probada PRIMERO en la alternancia del regex, así que nunca se "corta" una fecha completa por error. Y `_construir_verificaciones_de_datos` genera, para cada fecha real del texto base, AMBAS representaciones válidas (`"Lunes 7 de septiembre"` Y `"Lunes 7"`) — nunca inventa ni asume un mes nuevo, solo acepta que la MISMA fecha real pueda mencionarse con o sin su mes.

**Riesgo aceptado y documentado** (en el código): si el catálogo real alguna vez ofreciera dos fechas con el mismo día de la semana y número de día pero de MESES distintos, la forma corta sería ambigua — extremadamente improbable, dado que `HealthBrain` nunca ofrece más de 3 fechas, siempre dentro de una ventana corta de disponibilidad futura.

### Prueba forzando la alucinación elíptica (requisito #3)

Texto base: `"...1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre..."`. Texto redactado forzado: `"También tengo el miércoles 9, jueves 10 o viernes 11 de septiembre..."` (miércoles 9 inventado) → **`BLOCK`**, con "miércoles 9" identificado como el único valor inválido — las 2 fechas reales de la misma lista (jueves 10, viernes 11) NO se marcan como inválidas.

---

## Verificación (los 3 puntos pedidos)

1. ✅ **Todos los tests nuevos** — `tests/guardrails/test_opinion_personal.py` (4 tests: opinión política forzada bloqueada, otras formas de opinión bloqueadas, reconocimiento empático real del recado 042 NO bloqueado, respuestas normales NO bloqueadas) + `tests/domains/health/test_fecha_eliptica.py` (5 tests: reconocimiento de forma corta, forma completa sigue funcionando, fecha elíptica real permitida, alucinación elíptica bloqueada, fechas reales de la lista no marcadas como inválidas) + 1 test de extremo a extremo nuevo en `test_llm_brain.py` (`OpinionPersonalGuardrail` contra el Orchestrator real).
2. ✅ **Repetido con una llamada REAL nueva** (Caso 6/política del recado 042, con ambos fixes ya en el código): Claude evitó la opinión política por su cuenta otra vez (`"¡Entiendo tu frustración, pero mejor sigamos con lo importante! 😊 ..."`), y los 8 guardrails (incluidos los 2 nuevos) evaluaron `ALLOW` correctamente — confirma que ninguna corrección rompió el comportamiento normal.
3. ✅ **Suite completa**: 305 passed, 3 skipped (295 anteriores + 10 nuevos) — cero regresiones. 1 test existente (`test_construir_verificaciones_extrae_fecha_y_hora_reales`) actualizado para reflejar el nuevo comportamiento correcto (ahora incluye la forma corta), no una regresión — un ajuste esperado por el cambio de diseño.

## Archivos tocados

- `guardrails/rules.py`: `_MENSAJE_REDIRECCION_FUERA_DE_ALCANCE` (constante compartida), `_MARCADORES_OPINION_PERSONAL`, `OpinionPersonalGuardrail`, agregado a `reglas_core_por_defecto()`.
- `guardrails/__init__.py`: export del guardrail nuevo.
- `domains/health/llm_brain.py`: `_RE_FECHA` con 3ra alternativa (forma corta), `_RE_QUITAR_MES`, `_construir_verificaciones_de_datos` genera ambas formas.
- Nuevos: `tests/guardrails/test_opinion_personal.py`, `tests/domains/health/test_fecha_eliptica.py`.
- Actualizado: `tests/domains/health/test_llm_brain.py` (1 test existente ajustado, 1 nuevo + drafter de prueba).

## No corregido, a propósito (pedido explícito)

- El caso de "1 sola opción de horario" (Caso 1, Turno 2 del recado 042) — ya cubierto por `TipoDePreguntaAlteradaGuardrail`, baja prioridad, no se tocó.

## Pendiente de tu decisión

1. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo.
2. Con ambos hallazgos del recado 042 corregidos y verificados con evidencia real, ¿autorizas avanzar a una prueba en Telegram real, o prefieres otra ronda de pruebas?
3. Revisar si quieres que commitee y pushee este trabajo.
