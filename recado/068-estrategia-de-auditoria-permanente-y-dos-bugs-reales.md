# 068 — Estrategia de auditoría permanente + reserva con horario incorrecto + fallback de menú sin LLM

**Fecha**: 2026-09-11
**Estado**: Implementado, probado, y **verificado contra la base de datos real de producción** (sección 2.3 — confirmado: una sola cita, sin duplicados, nada que limpiar). **Sin commitear — a la espera de tu aprobación final.**

---

## 0. Estrategia estructural — el patrón que pediste resolver de raíz

### 0.1 Corpus de regresión de conversaciones reales

**Decisión**: directorio `tests/domains/health/corpus_regresion/` — cada archivo reproduce UNA transcripción real de punta a punta (`handle_inbound_message`, nunca una función aislada), con un README que define la convención (cuándo agregar, cómo nombrar, qué estructura). Se ejecuta automáticamente con `pytest` — es "obligatorio" simplemente por ser parte de la suite normal del proyecto, sin necesitar ningún comando especial.

Ya contiene los 2 hallazgos de hoy (secciones 1 y 2 más abajo) — el corpus creció desde el primer commit de este recado, tal como pediste.

### 0.2 Matriz de cobertura conversacional

**`.ai/CONVERSATION_COVERAGE.md`** (nuevo) — tabla de 12 puntos (los 11 del recado 067 + el fallback de menú principal, que faltaba en esa lista). Para cada uno: ¿determinista? ¿LLM asistido? ¿"salir"? — con evidencia y recado de origen. Auditar un punto nuevo, de ahora en adelante, es abrir esta tabla — no reconstruir la investigación.

**Hallazgos honestos que salieron de construir la tabla** (no ocultados):
- **Selección de servicio y selección al reprogramar NUNCA tuvieron LLM asistido** — nadie lo había notado porque nunca falló con un caso real. Documentado como `[CONFIRMADO — pendiente, no urgente]`, **no corregido** (sin evidencia real de que falle, siguiendo la regla de discovery del proyecto — no se arregla lo que no se ha visto roto).
- Confirmación de "olvida mis datos" (`confirmando_olvido`) — verifiqué que NO es un callejón sin salida (cualquier respuesta no afirmativa cancela y restaura, nunca se queda atascado).

### 0.3 Checklist de pre-deploy

**`scripts/verificar-antes-de-desplegar.sh`** (nuevo, de solo lectura, nunca toca EasyPanel) — corre la suite completa (incluido el corpus), confirma working tree limpio, compara `HEAD` local contra `origin/main`. Documentado en `.ai/DEPLOYMENT.md`, nueva sección "Checklist mínimo antes de CADA redeploy".

```
$ scripts/verificar-antes-de-desplegar.sh
== 1/3: Suite completa (incluye el corpus de regresión) ==
546 passed, 15 skipped in 1.21s
== 2/3: Working tree limpio ==
[...]
== 3/3: Hash real que se desplegaría ==
HEAD local:      4f6f6e2...
origin/main:     4f6f6e2...
OK — coinciden.
```

---

## 1. Hallazgo lateral GRAVE, encontrado auditando (no reportado por ti): `.env` real tiene `HEALTH_BRAIN_TYPE=llm`

Al construir la matriz de cobertura confirmé que el `.env` real de esta máquina **ya tiene `HEALTH_BRAIN_TYPE=llm` configurado** — es decir, toda esta sesión (y probablemente producción, si EasyPanel comparte esa configuración) corre con `HealthAnthropicBrain` activo, no con el `HealthBrain` determinista puro que buena parte de la documentación asume como default.

Esto expuso un bug real, nunca antes detectado: **`_evaluar_ventana_de_gracia` (la ventana de gracia de un turno, recado 050) crasheaba con `AttributeError`** en cualquier mensaje que necesitara reevaluarse tras un cierre, porque llamaba `orchestrator.brain._detectar_interrupcion_de_contexto(...)` directamente — un método que solo existe en `HealthBrain`, NUNCA en `HealthAnthropicBrain` (el envoltorio de redacción). Confirmado reproduciéndolo con un test real (`test_llm_brain.py::test_ventana_de_gracia_no_crashea_con_health_brain_type_llm_activo`) antes de corregir.

**Corregido**: se extrae siempre el `HealthBrain` determinista subyacente (`getattr(..., "_brain_determinista", ...)`), funcione con o sin el envoltorio de redacción activo.

Esto es exactamente el tipo de hallazgo que la matriz de cobertura (sección 0.2) existe para prevenir hacia adelante.

---

## 2. Parte 1 — reserva con horario incorrecto

### 2.1 Causa raíz — confirmada leyendo el código, reproducida con un escenario realista

`HrmmAppointmentService.book_appointment` tiene un mecanismo de "idempotencia adicional" (pensado para el camino OUTBOUND: un reintento del sistema IPS con una `idempotency_key` distinta) que, ANTES de corregir, comparaba solo `mismo_servicio` + `misma_fecha` — **nunca la hora/slot exacto**. Cualquier cita activa existente para ese servicio+fecha se devolvía tal cual como si fuera el resultado de la NUEVA selección, sin llamar siquiera a `POST /api/agenda/citas` la segunda vez.

Esto explica EXACTAMENTE la transcripción real: conversación 1 reserva Urgencias/14-sep a las 07:30; conversación 2 (nueva, minutos después) el paciente elige genuinamente la opción "1" de una oferta DISTINTA (07:00) — el sistema, en silencio, devolvió la cita VIEJA (07:30) en vez de intentar reservar la nueva.

**Corregido**: se agregó `misma_hora` a la comparación. El mecanismo sigue funcionando para su propósito original (mismo slot exacto, dos `idempotency_key` distintas → no duplica), pero ya no intercepta una selección de horario genuinamente distinta el mismo día.

### 2.2 Respuesta directa a tus 4 preguntas

1. **¿Cuántas citas reales existen, una o dos?** — **`[CONFIRMADO]` contra producción real (sección 2.3): UNA sola**, `CITA-29aa0de3e7`, Urgencias, 2026-09-14, **07:30**, CONFIRMED.
2. **¿Problema de idempotencia?** — Sí, exactamente: el mecanismo de idempotencia era DEMASIADO amplio (servicio+fecha en vez de servicio+fecha+hora).
3. **¿Bug de reporte, no de reserva real?** — Ambos a la vez, en el sentido que importa: no hubo una reserva duplicada, pero tampoco un simple error de texto — el sistema **nunca intentó reservar lo que el paciente pidió**, y el mensaje de confirmación reportó, como si fuera nuevo, el resultado de una acción vieja.
4. **Limpiar duplicados reales** — **Nada que limpiar, confirmado** — no hay duplicado real en la base de producción.

### 2.3 CONFIRMADO contra la base real de producción — `[CONFIRMADO]`

Ejecutado ahora mismo: `GET /api/agenda/citas?documento_paciente=<documento real proporcionado por el usuario>` contra hrmm-backend real (`HRMM_BACKEND_ENV=production`, `X-Backend-Secret` real) — lectura pura, sin ninguna escritura.

Resultado, filtrando por Urgencias/2026-09-14 (de 20 citas totales del paciente, ninguna otra relevante a este hallazgo — el resto es historial no relacionado, no reproducido aquí por no ser necesario):

| appointment_id | servicio | fecha | hora | consultorio | estado |
|---|---|---|---|---|---|
| `CITA-29aa0de3e7` | Urgencias | 2026-09-14 | **07:30** | Consultorio 5 | **CONFIRMED** |

**Una sola cita, exactamente como predijo el análisis del código** (sección 2.1) — la conversación 2 nunca llegó a crear una reserva real distinta; el mecanismo de idempotencia (antes del fix) devolvió en silencio esta misma cita en vez de intentar reservar 07:00. **Nada que limpiar** — tal como anticipaste en tu propio mensaje si el resultado era este. El fix de la sección 2.1 asegura que la PRÓXIMA vez que esto ocurra, la segunda selección se reserve de verdad (o falle explícitamente si el slot ya no está disponible), en vez de reportar un resultado que no ocurrió.

### 2.4 Verificación (sin necesitar el dato bloqueado)

- `tests/domains/health/test_hrmm_appointment_service.py::test_book_appointment_en_conversacion_nueva_con_otro_horario_no_reutiliza_la_vieja` — aislado, a nivel de servicio.
- `tests/domains/health/test_hrmm_appointment_service.py::test_book_appointment_en_conversacion_nueva_con_el_mismo_horario_si_se_deduplica` — control: el propósito original del mecanismo sigue intacto.
- `tests/domains/health/corpus_regresion/test_recado068_horario_incorrecto_en_conversacion_nueva.py` — de punta a punta, 2 conversaciones completas vía `handle_inbound_message`, reproduce la transcripción real (07:00/07:30/08:00 → elige "2" → confirma 07:30; luego 07:00/08:00/08:30 → elige "1" → confirma 07:00).

---

## 3. Parte 2 — fallback de menú sin interpretación asistida

### 3.1 Confirmado: quedó fuera de la generalización del recado 064

La categoría "información institucional" (recado 066) se conectó al detector centralizado DENTRO de una conversación abierta, pero **nunca** al fallback de menú principal (`gateway.py:_enrutar_solicitud_nueva`, sin conversación abierta) — el mismo hueco estructural que ya motivó los recados 062/063, esta vez sin que nadie lo hubiera generalizado a este punto específico.

**Corregido**: coincidencia EXACTA primero (gratis, reutiliza las mismas listas de brain.py); si no matchea (typo), la clasificación asistida por LLM del recado 064 ahora incluye `"informacion_institucional"` como categoría real.

### 3.2 Hallazgo adicional encontrado probando el fix — el mismo patrón del recado 067, otra vez

Al probar con la API real, "Kiero saber donde keda el ospital, porfa" seguía sin reconocerse — **no por el typo**, sino porque "porfa" está en `_VERBOS_DE_PEDIDO` y `classify_intent_or_none` (su propio último recurso amplio, `_tiene_senal_de_intencion`) la interceptaba ANTES de que la clasificación asistida por LLM (más precisa) tuviera oportunidad de correr — exactamente el mismo tipo de bug de prioridad que ya corregiste conmigo para la despedida en el recado 067, ahora en el mismo lugar pero para información institucional.

**Corregido**: nueva función `classify_intent_or_none_estricto` (`intent.py`) — todas las frases específicas y seguras, SIN el último recurso amplio. `gateway.py` prueba: menú exacto → despedida/salir → institucional exacto → **`classify_intent_or_none_estricto`** → LLM asistido (institucional/emocional/menú) → **recién ahí** `classify_intent_or_none` completo (con su último recurso amplio) como el ÚLTIMO nivel antes de rendirse.

### 3.3 Verificación — incluida llamada real a Claude

```
Paciente: Kiero saber donde keda el ospital, porfa
Sistema: [información institucional real — dirección, teléfono, correo]
```
Confirmado real, 1/1 en la prueba gateada tras el fix (antes fallaba 3/3 veces con la misma frase, de forma consistente — no era aleatoriedad del LLM, era el bug de prioridad).

`tests/domains/health/corpus_regresion/test_recado068_pregunta_institucional_con_typo_sin_conversacion.py` — 4 tests (exacto sin LLM, typo con LLM simulado, typo sin LLM configurado sigue sin reconocer — comportamiento sin cambios, y la prueba real).

---

## 4. Verificación completa

**Suite estándar** (default, sin `HEALTH_BRAIN_TYPE` forzado — la misma que se ha usado toda la sesión): `546 passed, 15 skipped`. Cero regresiones.

**Suite con `HEALTH_BRAIN_TYPE=llm` real activo** (el `.env` real de esta máquina): confirmé puntualmente que el fix de la sección 1 funciona (`test_ventana_de_gracia_no_crashea_con_health_brain_type_llm_activo`, pasa) y que el corpus completo pasa con drafting real activo (9s, llamadas reales). Intenté correr la suite COMPLETA en ese modo como verificación extra — la detuve a los ~2 minutos porque muchos tests no gateados empezaron a hacer llamadas reales no pedidas (costo/tiempo innecesario) — no es la barra de verificación estándar de este proyecto, la suite estándar sí lo es.

## 5. Archivos tocados (sin commitear)

- `domains/health/hrmm_appointment_service.py` — `misma_hora` en la idempotencia adicional.
- `domains/health/gateway.py` — fallback de menú institucional + fix del bug de prioridad + fix de `_evaluar_ventana_de_gracia`.
- `domains/health/intent.py` — `classify_intent_or_none_estricto` (nueva).
- `tests/domains/health/test_hrmm_appointment_service.py` — 2 tests nuevos.
- `tests/domains/health/test_llm_brain.py` — 1 test nuevo.
- `tests/domains/health/corpus_regresion/` — nuevo directorio, README + 2 escenarios (4 archivos).
- `.ai/CONVERSATION_COVERAGE.md` — nuevo.
- `.ai/DEPLOYMENT.md` — nueva sección de checklist.
- `scripts/verificar-antes-de-desplegar.sh` — nuevo.

## 6. Pendiente de tu parte

Todo implementado, probado (incluida la verificación real contra producción), y documentado. Solo falta tu aprobación para comitear y pushear.
