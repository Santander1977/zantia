# 070 — Selección de servicio por ordinal + mensajes de aclaración que ahora repiten la lista completa

**Fecha**: 2026-09-10
**Rama**: `main` (base `73d3349`, recado 069 ya desplegado)
**Estado**: Implementado y probado automáticamente. **Pendiente la prueba en vivo en Telegram con el usuario antes de comitear.**

Este recado cubre DOS hallazgos relacionados, pedidos juntos por el usuario: (Parte 1) selección de servicio por ordinal numérico, y (Parte 2) mensajes de aclaración/re-pregunta que no repetían la lista completa de opciones.

---

## 1. El reporte del usuario

Transcripción real:

```
Sistema ofrece: "1. Medicina General 2. Odontologia 3. Pediatria 4. Psicologia 5. Urgencias"
Paciente responde: "3" (debía ser Pediatria) -> NO reconocido, repite el menú.
Paciente responde: "2" (debía ser Odontologia) -> NO reconocido otra vez.
```

El usuario pidió confirmar, con evidencia de `git log`/`git blame`, si esto era una **regresión** (algo que funcionaba y se rompió, posiblemente en el trabajo de los recados 068/069) o una **funcionalidad que nunca existió**.

---

## 2. Causa raíz — confirmada con `git log -p`, no supuesta

**Nunca fue una regresión. Fue una decisión de diseño original del recado 030, nunca extendida.**

`domains/health/brain.py::HealthBrain._interpretar_servicio` es la función que interpreta la respuesta del paciente a la lista numerada de servicios. Desde su creación (recado 030) y en todo su historial (`git log -p --follow -- domains/health/brain.py`), esta función **solo hizo match por nombre real** (exacto/substring, y desde el recado 036 también fuzzy matching por tolerancia a typos) — **nunca tuvo ninguna rama que interpretara un ordinal numérico**.

Evidencia directa, el propio mensaje de commit `d7d4835` (recado 036, "tolerancia a errores de tipeo al elegir servicio"):

> "Confirmado con test que fecha/horario no necesitan el mismo tratamiento (**selección por ordinal, no por nombre libre**)."

Esto documenta explícitamente, en el momento en que se construyó el mecanismo, que fecha/horario usan un camino DISTINTO (ordinal) del de servicio (nombre/fuzzy) — una distinción consciente, no un descuido. El recado 067 corroboró lo mismo en un test dedicado (`test_seleccion_de_fecha_es_por_ordinal_no_por_nombre_libre_no_aplica_fuzzy`, `test_tolerancia_a_errores_de_tipeo_en_servicio.py:258`).

Los recados 068/069 (los más recientes antes de este) tocaron `gateway.py`/`intent.py`/partes de `brain.py` relacionadas con el fallback de menú institucional y la despedida — **ninguno de los dos modificó `_interpretar_servicio` ni `_indice_ordinal_seguro`**. No hay ningún commit que haya "quitado" soporte de ordinal para servicio, porque nunca existió.

**Conclusión**: es una funcionalidad faltante (punto 2 de la investigación pedida), no una regresión (punto 3, descartado con evidencia).

---

## 3. Por qué es un hallazgo real y no solo un "nice to have"

El paciente ve una lista numerada (recado 054/055) idéntica en formato a la de fecha, horario, reprogramación y el menú principal — las 4 de esas SÍ aceptan el ordinal. Es completamente natural, y esperable, que el paciente responda de la misma forma en las 5 listas. La matriz de cobertura (`.ai/CONVERSATION_COVERAGE.md`, fila #2) ya había marcado este hueco como "pendiente, no urgente — nadie reportó un caso real fallido"; este es exactamente ese caso real.

---

## 4. Fix implementado

### 4.1 `_indice_ordinal_seguro` ampliado de 3 a 10 posiciones (`brain.py:~615-651`)

Antes solo reconocía índices 0-2 ("1"/"primera", "2"/"segunda", "3"/"tercera") porque el único uso real (fecha/horario/reprogramación) nunca ofrecía más de 3 opciones. Ampliado a 0-9 (hasta "10"/"décima") para cubrir el catálogo real de 5 servicios, con margen. Comparación ahora sin tildes (`_sin_tildes`), para que "séptima"/"décima" funcionen con o sin acento. Los llamadores existentes (fecha/horario/reprogramación) siguen validando `indice < len(opciones)` — ampliar el rango no les afecta, un "4"/"5" que no aplica simplemente no cruza esa validación.

### 4.2 `_interpretar_servicio` revisa el ordinal primero (`brain.py:~1487-1520`)

```python
listar = getattr(self._appointment_service, "list_services", None)
servicios = listar() if listar else []
elegido = None
if servicios:
    indice = _indice_ordinal_seguro(texto)
    if indice is not None and indice < len(servicios):
        elegido = servicios[indice]
if elegido is None:
    normalizado = _sin_tildes(texto)
    elegido = next((s for s in servicios if _sin_tildes(s.lower()) in normalizado), None)
# ... (resto sin cambios: fuzzy matching, fallback)
```

Contra el catálogo **exacto en el mismo orden** que `list_services()` ya devuelve (mismo orden mostrado al paciente vía `_lista_numerada`, sin reordenar). Si no hay ordinal reconocido, cae al match por nombre/fuzzy de siempre — sin cambios en ese camino.

---

## 5. Verificación

### 5.1 Automatizada
- Suite completa: **552 passed, 15 skipped, 0 failed** (antes de este cambio: 546 passed — los 6 nuevos son los tests de este recado, cero regresiones).
- Nuevo archivo `tests/domains/health/corpus_regresion/test_recado070_seleccion_de_servicio_por_ordinal.py` (siguiendo la convención del corpus, recado 068):
  - Reproduce la transcripción real exacta: "3" → Pediatria, "2" → Odontologia (verificado contra la FECHA real ofrecida de cada servicio, no solo el texto genérico "fechas disponibles" — confirma sin ambigüedad qué servicio quedó seleccionado).
  - Los 5 ordinales numéricos ("1".."5") contra el catálogo real de 5, cada uno al servicio correcto.
  - Los 5 ordinales por palabra ("la primera".."quinta"), incluidas frases con palabras alrededor ("la tercera por favor").
  - Control: el fuzzy matching por nombre (recado 036, "pedeatria") sigue intacto.
  - Control: un ordinal fuera de rango ("9") no crashea, cae al fallback normal.
- Suite existente `test_tolerancia_a_errores_de_tipeo_en_servicio.py` (recado 036, fuzzy matching) sigue en 100% verde, sin ninguna modificación — confirma que el fix no tocó ese camino.

### 5.2 Verificación manual adicional (antes de escribir cualquier test, y de nuevo después)
Reproduje directamente en un REPL de Python, contra un catálogo real de 5 servicios con una fecha real distinta por servicio: "3"→Pediatria (fecha real ofrecida correcta), "2"→Odontologia (fecha real ofrecida correcta), "la tercera"→Pediatria, "pedeatria" (fuzzy)→Pediatria — los 4 casos correctos, sin ambigüedad.

---

# PARTE 2 — Mensajes de aclaración que no repetían la lista completa

## P2.1 El reporte del usuario

Confirmado en varias conversaciones reales de hoy: cuando el sistema no reconocía la respuesta del paciente a una lista numerada YA mostrada (fecha, horario, reprogramación, selección de slot dentro del wizard de verificación de código), el mensaje de aclaración solo preguntaba **"¿me confirmas si es la 1, la 2 o la 3?"** — sin volver a mostrar qué era cada opción. El paciente tenía que recordarlo de memoria, lo cual es una mala experiencia y una causa plausible de varias de las confusiones vistas hoy.

## P2.2 Auditoría completa — qué mensajes SÍ y cuáles NO mostraban la lista

Revisé cada mensaje de aclaración/fallback de `brain.py` y `gateway.py` (grep de "no logré identificar"/"¿me confirmas"/"la 1, la 2"):

| Mensaje | Etapa | ¿Repetía la lista ANTES? |
|---|---|---|
| `_VARIANTES_SERVICIO_NO_IDENTIFICADO` | Selección de servicio | ✅ Sí (recado 034) — sin cambios |
| `_VARIANTES_SERVICIO_AMBIGUO` | Ambigüedad de servicio | ✅ Sí (recado 036) — sin cambios |
| `_VARIANTES_FECHA_AMBIGUA` | Ambigüedad de fecha | ✅ Sí (recado 051) — sin cambios |
| `_VARIANTES_HORARIO_AMBIGUO` | Ambigüedad de horario | ✅ Sí (recado 051) — sin cambios |
| `_VARIANTES_FECHA_NO_IDENTIFICADA` | Selección de fecha, sin match | ❌ **No** — corregido |
| `_VARIANTES_SELECCION_NO_IDENTIFICADA` | Selección de horario, sin match | ❌ **No** — corregido |
| `_interpretar_seleccion_reprogramacion` (mensaje fijo) | Reprogramación (Brain) | ❌ **No** — corregido |
| `gateway.py:_procesar_intento_de_codigo`, stage `esperando_seleccion` (mensaje fijo) | Selección de slot en wizard de código (2FA) | ❌ **No** — corregido |
| `_VARIANTES_ACLARACION_SI_NO` | Decisión sí/no inicial | No aplica — es binario, no una lista |

**3 lugares reales corregidos** (los 4 marcados ❌, dos de ellos comparten la misma causa: ambos usan un mensaje fijo sin `{opciones}`).

## P2.3 Antes / después (texto exacto)

**Aclaración de fecha:**
- Antes: *"No logré identificar cuál fecha prefieres — ¿me confirmas si es la 1, la 2 o la 3?"*
- Después: *"No logré identificar cuál fecha prefieres:\n1. Lunes 14 de septiembre\n2. Martes 15 de septiembre\n3. Miércoles 16 de septiembre\n¿me confirmas si es la 1, la 2 o la 3?"*

**Aclaración de horario:**
- Antes: *"No logré identificar cuál prefieres — ¿me confirmas si es la 1, la 2 o la 3?"*
- Después: *"No logré identificar cuál prefieres:\n1. 09:00\n2. 10:00\n3. 11:00\n¿me confirmas si es la 1, la 2 o la 3?"*

**Aclaración de reprogramación (Brain):**
- Antes: *"¿Me confirmas cuál opción prefieres — la 1, la 2 o la 3?"*
- Después: *"No identifiqué cuál opción prefieres:\n1. Lunes 14 de septiembre, 09:00, Sede Norte\n2. ...\n¿me confirmas si es la 1, la 2 o la 3?"*

**Aclaración de selección en el wizard de código (2FA):**
- Antes: *"No identifiqué cuál opción prefieres — ¿me confirmas 1, 2 o 3?"*
- Después: mismo formato que reprogramación arriba.

## P2.4 Fix implementado

- `_VARIANTES_FECHA_NO_IDENTIFICADA`/`_VARIANTES_SELECCION_NO_IDENTIFICADA` (`brain.py:~481-493`): se les agregó `{opciones}`, mismo criterio que las otras 4 variantes del mismo bloque que ya lo tenían.
- `_interpretar_fecha`/`_interpretar_horario` (`brain.py`): en la rama de fallback genérico, ahora reconstruyen la lista (`_lista_numerada` sobre `fechas`/`horas`, ya disponibles en `datos`) y la pasan como `opciones=...`.
- `_iniciar_reprogramacion` (`brain.py`): ahora guarda el texto YA formateado de la lista en `datos["texto_opciones_reprogramacion"]` al ofrecerla (los `slot_id` guardados no traen fecha/hora/consultorio legibles) — `_interpretar_seleccion_reprogramacion` lo reutiliza en su fallback.
- `_resolver_programar_cita`/reprogramación con 2FA (`gateway.py`): mismo patrón — `pendiente["texto_opciones_slot"]` se guarda al ofrecer las opciones, y `_procesar_intento_de_codigo` lo reutiliza en su fallback.
- **LLM (`HealthAnthropicBrain`)**: el prompt de sistema (`llm_brain.py`, regla 7) YA exigía, desde el recado 038, preservar cualquier lista numerada EXACTAMENTE igual al reformular — con ejemplos explícitos de qué NUNCA hacer. Verificado con una llamada REAL a la API de Anthropic (ver P2.5) que esto sigue cumpliéndose también para los 2 mensajes recién corregidos — no fue necesario reforzar el prompt más.

## P2.5 Verificación

### Automatizada
- Nuevo archivo `tests/domains/health/test_aclaraciones_repiten_lista_completa.py` — 5 tests: aclaración de fecha, de horario, de reprogramación (Brain), de selección en el wizard de código (2FA), y un control de que la aclaración de servicio (que ya funcionaba) sigue intacta. Cada uno reproduce el escenario real (mensaje ambiguo real) y confirma que la respuesta contiene al menos una línea de lista numerada real (`N. dato`), no solo la pregunta.
- Suite completa: **557 passed, 15 skipped, 0 failed** (antes: 552 — los 5 nuevos son de este hallazgo).
- Un test preexistente (`test_feedback_con_digito_suelto_no_se_confunde_con_seleccion_de_fecha`, recado 067) afirmaba que el fallback NUNCA mencionaba nombres de días — eso era incidental (en ese momento el fallback nunca mostraba nada). Actualizado para verificar lo que realmente importaba ese test: que el feedback largo del paciente no se cuele tal cual en la respuesta — nunca se relajó la protección real, solo se corrigió una aserción que había quedado obsoleta por este mismo fix.

### Real, con LLM activo
Con `HEALTH_BRAIN_TYPE=llm` + `ANTHROPIC_API_KEY` real (llamada real a la API de Anthropic): una aclaración de servicio con la lista de 3 servicios se redactó como *"No hay problema, tómate tu tiempo. Estas son las opciones disponibles:\n\n1. Medicina General\n2. Odontologia\n3. Pediatria\n\n¿Me confirmas el nombre tal como aparece en la lista?"* — lista preservada exactamente, tono ajustado. Una aclaración de fecha (mismo escenario) preservó igual su única fecha listada.

**Hallazgo incidental, fuera de alcance**: en una de las llamadas reales apareció un aviso interno ya existente ("`AnthropicResponseDrafter falló ('ThinkingBlock' object has no attribute 'text') — usando el texto determinista sin redactar`") — el mecanismo de seguridad ya existente (recado 038) hizo su trabajo: ante el fallo, usó el texto determinista tal cual (que ya incluye la lista correcta) en vez de fallar o inventar algo. No es parte de este hallazgo ni se tocó — lo documento por transparencia, no lo corregí sin que se pida.

---

## 6. Nota — este recado quedó superado por el recado 071

Tras este recado, reportaste 3 problemas nuevos encontrados en producción (horario mostrando solo números, despedida sin funcionar, enfriamiento sin informar tiempo restante) y pediste dejar de solicitar pruebas manuales en Telegram, usando en su lugar verificación autónoma contra sistemas reales (hrmm-backend producción, API real de Anthropic, tiempo real). Esa investigación — que incluyó una causa raíz REAL encontrada en la propia selección de horario de este mismo recado (070) — está documentada completa en **`/Users/enzoalfonso/recado/071-auditoria-real-3-problemas-horario-despedida-enfriamiento.md`**, junto con el fix correspondiente. El trabajo de este recado (070) y el del 071 se comitean juntos — ver la sección "Próximo paso" del recado 071.
