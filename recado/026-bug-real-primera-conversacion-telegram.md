# 026 — Bug real encontrado en la primera conversación real de ZANTIA (Telegram)

**Fecha**: 2026-09-05
**Disparador**: el usuario reportó dos fallas reales observadas en la primera conversación real de ZANTIA con una persona real, por Telegram, después de que la identidad del canal ya se había confirmado correctamente.

## Advertencia honesta sobre el alcance de esta investigación

El pedido incluía "[pega aquí la transcripción completa que ya tienes]" como marcador de posición — la transcripción completa **nunca llegó a pegarse** en el mensaje real. Todo lo que hay para trabajar es el resumen/paráfrasis que el usuario escribió a mano, más las tres frases citadas literalmente ("Qué citas tengo programadas", "Se más amable", "Si").

Además, **no hay ningún log persistente de esta conversación específica que se pueda inspeccionar desde este repo**:

- `observability/events.py:EventLog` es **en memoria de proceso únicamente** — nunca se serializa a disco (riesgo `R-11` en `.ai/RISKS.md`, ya conocido y ABIERTO desde antes de esta sesión). Si el proceso siguió corriendo, los eventos existen en la memoria de ESE proceso — inaccesibles desde aquí — no en un archivo que se pueda grep.
- El `.env` local de este repo tiene `ZANTIA_DB_PATH=` y `ZANTIA_IDENTIDAD_DB_PATH=` **vacías** — si el despliegue real (EasyPanel) usa la misma configuración vacía, el `ConversationState` de esta conversación tampoco sobrevive a un reinicio (cae a `:memory:`, con un `logger.warning` explícito en cada conversación nueva, ver recado `021`/R-22). **No se puede confirmar desde este repo si el `.env` del despliegue real en EasyPanel tiene esas variables configuradas distinto** — esa es la única fuente que podría tener el `ConversationState` real de esta conversación, y no es accesible desde aquí.
- Los `logger.warning`/`logger.info` de `service/app.py` van a stdout del proceso — en EasyPanel, eso vive en el panel de logs de la plataforma, no en este repo.

**Conclusión de este punto**: el pedido #1 ("revisar los logs reales de esta conversación") **no se pudo cumplir tal cual se pidió** — no porque no se buscara, sino porque la infraestructura de observabilidad actual (R-11, ya documentada como riesgo abierto) no lo permite, y el `chat_id`/`conversation_id` real tampoco se compartió. Si se quiere una confirmación 100% verificada de la causa EXACTA del punto 1 de abajo, hace falta revisar los logs crudos de EasyPanel para esa ventana de tiempo, o repetir la conversación con logging temporal activado (mismo patrón ya usado en el commit `91c42a7`, "debug: log temporal de diagnóstico").

Dicho esto, la lectura directa del código sí permitió encontrar, confirmar y corregir una causa raíz real (punto 2) y una causa raíz altamente probable con mecanismo confirmado (punto 1).

## Hallazgo 1 — "Necesito una cita" activó escalamiento genérico en vez de ofrecer disponibilidad

**Clasificación: `[CONFIRMADO]` el mecanismo por el que esto puede pasar. `[INFERIDO]` que fue exactamente esto lo que pasó en esta conversación real específica — sin logs, no se puede subir a `[CONFIRMADO]`.**

Descartado primero, con evidencia directa: **`domains/health/intent.py:_PROGRAMAR` YA incluye `"necesito una cita"` como frase reconocida** (línea 12) — `classify_intent("necesito una cita")` devuelve `PROGRAMAR_CITA` correctamente, verificado leyendo el código. El catálogo de intención NO es el problema; el pedido #2 del usuario queda respondido: no hace falta ampliarlo para esta frase exacta.

Lo que sí se encontró: el texto que el usuario citó — *"Voy a registrar tu caso... no puedo garantizar contacto"* — coincide **casi literal** con el mensaje de `guardrails/rules.py:NoPrometerContactoGuardrail` ("Voy a **registrar** tu caso para que el equipo lo revise. No puedo garantizar un contacto ni un tiempo específico"), y NO con los otros dos mensajes de escalamiento del proyecto (`domains/health/gateway.py:_MENSAJE_ESCALAMIENTO_INBOUND` y `core/orchestrator.py:_MENSAJE_ESCALADO_ESTANDAR`, ambos dicen "voy a **pasar** tu caso"). Esa diferencia de una palabra ("registrar" vs. "pasar") es la pista: **la respuesta que el paciente recibió salió del guardrail, no del camino de escalamiento explícito.**

`NoPrometerContactoGuardrail` reescribe EN SILENCIO cualquier respuesta propuesta por `HealthBrain` que contenga una frase de `_PROMESAS_PROHIBIDAS` (`"te contactamos"`, entre otras — lección directa de Dani, 002). Se encontraron dos lugares en `domains/health/brain.py` donde el Brain SÍ podía proponer exactamente esa frase: el mensaje de "sin disponibilidad" en `_ofrecer_disponibilidad` y en `_iniciar_reprogramacion`, ambos terminaban en *"...te contactamos pronto."* — si `AppointmentService.get_availability()` no tenía turnos para el servicio pedido en ese momento, el Brain componía ese mensaje, el guardrail lo interceptaba y lo reemplazaba por el genérico de escalamiento — **sin que se haya escalado nada de verdad** (`necesidad_de_escalar` nunca se activa en esa rama). El paciente recibe un mensaje que suena a "tu caso quedó en manos de alguien más", cuando la realidad es "no hay cupos ahora mismo".

Esto es coherente con "Necesito una cita" siendo tratada correctamente como `PROGRAMAR_CITA`, pero sin cupos disponibles en el momento real de esa conversación contra `hrmm-backend` (que sí está en modo `production` real, ver R-6/R-24 previas). No se pudo confirmar con una llamada real a `get_availability` en el momento exacto de la conversación (no hay timestamp ni logs), así que queda `[INFERIDO]`, no `[CONFIRMADO]`.

**Corregido de todas formas, independientemente de si fue exactamente esto lo que pasó**: los dos mensajes de "sin disponibilidad" se reformularon sin la frase prohibida, para que un paciente real reciba la razón real (sin cupos ahora) en vez de un mensaje de escalamiento fantasma. Ver diff en `domains/health/brain.py`.

## Hallazgo 2 — "sí"/"Si" no avanzaba la conversación (bug real, `[CONFIRMADO]`)

Reproducido literalmente con el texto citado por el usuario: el paciente escribió `"Si"` (sin tilde) como mensaje completo, en respuesta a "¿Te gustaría que te ayude a programar tu atención? Puedes responder sí o no."

`domains/health/brain.py:_ACEPTA` (antes de este fix) era:

```python
_ACEPTA = ("sí", "si,", " si ", "acepto", "me interesa", "claro que", "dale", "vale", "de acuerdo", "está bien")
```

`texto = "si"` (después de `.lower().strip()`) **no coincide con ningún elemento** de esa tupla:
- `"sí"` exige la tilde — "si" no la tiene.
- `"si,"` exige una coma — no hay coma en un "Si" solo.
- `" si "` exige un espacio ANTES y DESPUÉS — imposible en un string de 2 caracteres exactos.

El diseño original (substring, sin tilde/coma/espacios de sobra) fue deliberado para evitar falsos positivos (un "si" bare como substring habría matcheado "as**í**stir"... en realidad ni siquiera esa, pero sí "sin**si**eramente" o cualquier palabra que contenga "si") — pero el efecto secundario no anticipado fue que la respuesta MÁS NATURAL a una pregunta de sí/no ("Si" sin tilde, muy común al escribir rápido en un teléfono) **nunca calzaba**, dejando al Brain repitiendo la misma pregunta para siempre (`_interpretar_decision` siempre caía al fallback final, para cualquier mensaje que no matcheara ningún patrón — incluida la respuesta "correcta").

Mismo defecto en `_DECLINA` (un "No" bare tampoco declinaba), y en los otros dos puntos donde `_ACEPTA` se reutiliza (`_interpretar_confirmacion_beneficiario`, `_interpretar_confirmacion_olvido` — este último parte del mecanismo de habeas data de "olvida mi información", recado 016).

### Corrección aplicada

`domains/health/brain.py` — nuevas constantes y helpers, usados en los 4 puntos donde `_ACEPTA`/`_DECLINA` se consultaban:

```python
_ACEPTA_PALABRA_UNICA = ("si", "sí")
_DECLINA_PALABRA_UNICA = ("no",)

def _es_palabra_unica(texto: str, palabras: tuple) -> bool:
    return texto.strip(" .!¡¿?,") in palabras

def _es_afirmativo(texto: str) -> bool:
    return _contains_any(texto, _ACEPTA) or _es_palabra_unica(texto, _ACEPTA_PALABRA_UNICA)

def _es_negativo(texto: str) -> bool:
    return _contains_any(texto, _DECLINA) or _es_palabra_unica(texto, _DECLINA_PALABRA_UNICA)
```

Deliberadamente **NO** se agregó `"si"`/`"no"` como substring suelto a `_ACEPTA`/`_DECLINA` — eso habría reintroducido el falso positivo que el diseño original evitaba (matchear "asistir", "sinceramente", etc.). La comparación es por IGUALDAD del mensaje completo, ya limpio de puntuación de borde (`"Si."`, `"¡si!"` también funcionan).

### Test de regresión

`tests/domains/health/test_respuesta_una_palabra.py` — 5 tests nuevos:
- `"Si"` (sin tilde) avanza a ofrecer disponibilidad, no repite la pregunta.
- `"si"` (minúscula) también.
- `"¡Si!"` (con puntuación) también.
- `"No"` (bare) declina correctamente.
- El mensaje de "sin disponibilidad" ya no contiene la frase prohibida ni termina marcando la Activity como `ESCALATED`.

Suite completa: **174 tests pasando + 2 deshabilitados a propósito** (antes: 169 + 2), cero regresiones.

## Qué queda pendiente / no se hizo en esta sesión

- **No se pudo confirmar contra logs reales cuál fue el disparador EXACTO del hallazgo 1** (ver advertencia arriba) — recomendado: revisar el panel de logs de EasyPanel para la ventana de tiempo de esa conversación, o pedirle al usuario el `chat_id` de Telegram y repetir la consulta con logging temporal (mismo patrón del commit `91c42a7`).
- **R-11 (`ConversationMemory`/`EventLog` en memoria, sin persistir) sigue ABIERTO** — este incidente es evidencia real y concreta de por qué importa: sin él, ninguna auditoría de un incidente real de producción puede reconstruirse después de los hechos. No se resolvió en esta sesión (fuera del alcance del pedido — el usuario pidió diagnosticar y corregir el bug conversacional, no rediseñar observabilidad); queda documentado en `.ai/RISKS.md` como motivo adicional para priorizarlo antes de más conversaciones reales.
- No se tocó `domains/health/intent.py` — ya estaba correcto para la frase reportada.
- Los otros dos mensajes de escalamiento casi-duplicados (`gateway.py:_MENSAJE_ESCALAMIENTO_INBOUND` y `orchestrator.py:_MENSAJE_ESCALADO_ESTANDAR`, texto idéntico entre sí) no se tocaron — es una duplicación menor, no causante de este bug, fuera de alcance de este pedido.

## Riesgo actualizado

`.ai/RISKS.md` — nueva fila `R-24` (RESUELTO, 2026-09-05) documentando el hallazgo 2 y la corrección relacionada del hallazgo 1.
