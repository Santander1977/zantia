# 030 — Cuarto hallazgo real: loop de conversación por tildes faltantes + servicio nunca confirmado

**Fecha**: 2026-09-06
**Continúa**: recados 026, 027, 028, 029 (misma conversación real de Telegram)
**Severidad**: la más alta de los cuatro hallazgos — un paciente real quedaba efectivamente atrapado, sin ninguna combinación de mensajes que lo sacara del ciclo.

## Resumen ejecutivo

Dos causas raíz distintas, la segunda dependiente de la primera, ambas confirmadas leyendo código y reproduciendo la conversación real con un script:

1. **"Que tienes disponible para citas" (sin tilde en "que") no se reconocía como pregunta de catálogo.** El fix del recado 027 solo cubría la forma CON tilde ("qué"). Un paciente real que omite tildes al escribir rápido en Telegram —extremadamente común— caía en silencio al fallback por defecto (`PROGRAMAR_CITA`), que además asume un servicio ("medicina general") que el paciente nunca pidió.
2. **Una vez en "sin disponibilidad", ni siquiera un "sí" inequívoco lograba avanzar.** "Si claro ayúdame puedes orientarme mejor" — con "si" siendo la PRIMERA palabra, sin tilde, sin coma — no coincidía con ningún patrón de aceptación del recado 026 (todos exigían tilde, coma o espacios alrededor). El paciente quedaba alternando entre el mismo "sin disponibilidad" y la pregunta fija de sí/no, sin salida real.

## 1. Diagnóstico confirmado con `classify_intent()` directo

```python
>>> classify_intent("Que tienes disponible para citas")
RequestIntent.PROGRAMAR_CITA   # ANTES del fix — debía ser INFORMACION_SERVICIO
>>> classify_intent("Qué tienes disponible para citas")  # CON tilde
RequestIntent.INFORMACION_SERVICIO   # esta forma sí funcionaba desde el recado 027
```

Confirmado exhaustivamente: **toda** variante de la pregunta de catálogo sin tilde en "qué"/"cuál(es)" fallaba — "que tienes disponible", "cual tienes", "cuales servicios tienes", "que servicios tienen", etc. — devolvían `PROGRAMAR_CITA` por el mismo motivo. No era un problema de la palabra "citas" (la hipótesis inicial del usuario) — ninguna de las frases de `_PROGRAMAR` coincide con este texto; es el fallback POR DEFECTO de `classify_intent` ("sin coincidencia clara, se asume programar") el que se activaba, porque `_INFORMACION` nunca llegaba a coincidir en primer lugar.

**Causa raíz**: mismo patrón exacto que el recado 026 (bug de "sí"/"si"), aplicado ahora a "qué"/"cuál" — un paciente real omite tildes con mucha frecuencia, y toda comparación por palabras clave que EXIJA la tilde falla en silencio contra el español real.

## 2. Corrección — normalización de tildes, acotada

`domains/health/intent.py` y `domains/health/brain.py` ahora normalizan tildes (`á→a, é→e, í→i, ó→o, ú→u`, **nunca** `ñ→n` — "año"/"ano" son palabras distintas, eso no es lo que se corrige) antes de comparar contra `_INFORMACION`/`_CONSULTAR_SERVICIOS`. Deliberadamente **acotado** a estas dos comparaciones (las directamente implicadas en el bug reportado) — no se generalizó a todo el archivo de una vez. Ver recomendación de alcance más amplio al final de este documento.

## 3. Diagnóstico del segundo hallazgo — "sí" que tampoco avanzaba

Reproducido literalmente: tras "sin disponibilidad", el paciente escribió "Si claro ayúdame puedes orientarme mejor". `_ACEPTA` (recado 026) era:
```python
_ACEPTA = ("sí", "si,", " si ", ...)
```
- `"sí"` exige tilde — el mensaje no la tiene.
- `"si,"` exige coma inmediatamente después — el mensaje tiene un espacio, no coma.
- `" si "` exige un espacio ANTES de "si" — imposible, "si" es la PRIMERA palabra del mensaje (nada antes).

Ninguna de las tres calzaba, a pesar de que la respuesta es inequívocamente afirmativa para cualquier lector humano.

## 4. Corrección — reconocimiento por límite de palabra + reordenamiento de prioridad

`_es_afirmativo`/`_es_negativo` ahora reconocen "sí"/"no" como **palabra completa** (`\bsi\b`/`\bno\b`, regex) sobre el texto ya sin tildes — en CUALQUIER posición del mensaje, no solo con coma/espacios exactos alrededor. Sigue evitando el falso positivo original que motivó el diseño anterior (nunca matchea "asistir"/"sinceramente", porque `\b` exige un límite de palabra real).

Esto amplía significativamente qué cuenta como "no" — lo cual obligó a **reordenar la prioridad** dentro de `_interpretar_decision`: las ramas específicas (`_HUMANO`, `_NO_PUEDE_AHORA`, `_PIDE_INFO`, catálogo, beneficiario) ahora se revisan **antes** que el chequeo genérico de "no". Sin este reordenamiento, "no, prefiero hablar con un asesor" se habría declarado como un simple "no gracias" en vez de escalar a una persona — una regresión real que se detectó y evitó durante esta misma sesión, antes de que llegara a producción (tests `test_no_puedo_asistir_ahora_no_se_confunde_con_declinar` y `test_no_quiero_hablar_con_alguien_escala_y_no_declina`).

**Costo conocido y aceptado**: un "no" suelto en cualquier posición (ej. "no sé si quiero") ahora se interpreta como declinar. Es un límite estructural del enfoque 100% determinista por palabras clave (`.ai/RISKS.md` R-13) — preferible a la alternativa (quedar sin ninguna forma de avanzar), pero documentado explícitamente como trade-off, no como efecto colateral silencioso.

## 5. El servicio nunca confirmado — causa estructural de fondo

Independiente de las tildes: **¿por qué había "sin disponibilidad" en primer lugar, si el paciente nunca pidió un servicio específico?** `domains/health/gateway.py:_nueva_activity_sintetica` asignaba `service="medicina general"` de forma HARDCODEADA para **toda** solicitud nueva de "programar cita" — sin que el paciente lo haya nombrado ni confirmado nunca. Con el catálogo real de `hrmm-backend` teniendo varios servicios (5, confirmado en el recado 025), asumir uno específico a ciegas es estructuralmente incorrecto.

**Corrección**: nueva función `_determinar_servicio_inicial` — si `AppointmentService.list_services()` (recado 027) devuelve **más de un** servicio real, `gateway.py` ya NO asume ninguno: pregunta primero ("¿Para cuál servicio te gustaría agendar? Estas son las opciones: ...") mediante una nueva etapa de `HealthBrain` (`"esperando_servicio"` → `_interpretar_servicio`), y solo consulta disponibilidad una vez el paciente nombra uno real del catálogo (comparación también sin tildes). Con 0 o 1 servicio real no hay nada que desambiguar — comportamiento sin cambios (confirmado con `MockAppointmentService`, que solo tiene uno).

## Reproducción completa, antes/después

```
ANTES:
>>> "Que tienes disponible para citas"
<<< "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio..."
>>> "Hola"
<<< "¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir."
>>> "Piensa"
<<< "¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir."
>>> "Si claro ayudame puedes orientarme mejor"
<<< "¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir."   <- SIN SALIDA
>>> "Si claro necesito tu ayuda"
<<< "¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir."   <- SIN SALIDA

DESPUÉS:
>>> "Que tienes disponible para citas"
<<< "Estos son los servicios que tenemos disponibles: medicina general. ¿Te gustaría agendar una cita para alguno de ellos?"
>>> "Hola"
<<< "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio..."  (ver nota)
>>> "Piensa"
<<< "No logré entender si es un sí o un no — ¿me confirmas si quieres que te ayude a agendar tu atención?"
>>> "Si claro ayudame puedes orientarme mejor"
<<< "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio..."  (honesto: SÍ avanzó, y el mock está deliberadamente sin cupos en esta prueba)
>>> "Si claro necesito tu ayuda"
<<< "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio..."  (honesto, mismo motivo)
```

**Nota importante**: en la reproducción de arriba, el `MockAppointmentService` de la prueba se drenó A PROPÓSITO (cero cupos) para simular el escenario real reportado. El punto que importa no es que "sin disponibilidad" siga apareciendo — es que ahora aparece **porque de verdad no hay cupos**, después de que el sistema SÍ entendió correctamente cada "sí" y cada pregunta de catálogo. Antes, aparecía o se quedaba sin avanzar **sin que el sistema entendiera nada de lo que el paciente escribía**. Con cupos reales disponibles (`MockAppointmentService` sin drenar), la misma frase "Si claro ayúdame..." avanza directo a "opciones disponibles" — confirmado con test (`test_respuesta_afirmativa_sin_tilde_como_primera_palabra_avanza`).

## Respondiendo los 4 puntos pedidos

**1. ¿En qué etapa exacta queda la conversación tras "sin disponibilidad"?** `[CONFIRMADO]` `datos_recopilados.etapa = "finalizada"` y `fase_actual` pasa a `RESPUESTA` y luego, automáticamente, a `CIERRE` (mecanismo YA EXISTENTE en el Core, `_normalizar_tras_turno`, sin relación con este bug). **¿Por qué cualquier mensaje siguiente se interpretaba dentro del mismo contexto viejo?** No era exactamente eso: el Core SÍ reabre el ciclo automáticamente (`_reabrir_ciclo`, ya existente) cada vez que un turno termina en `CIERRE` — el problema real es que, una vez reabierto a `datos_recopilados = {}` (etapa fresca "esperando_decision"), **ninguna palabra clave existente reconocía las respuestas reales del paciente** (ni el "sí" sin tilde, ni la pregunta de catálogo sin tilde) — así que caía una y otra vez al mismo fallback genérico, sin importar que el ciclo SÍ se hubiera reabierto de verdad.

**2. ¿Existe un mecanismo de escape/reinicio? ¿Un saludo debería resetear?** El mecanismo de reapertura (`CIERRE` → `_reabrir_ciclo`) YA EXISTE y SÍ funciona — confirmado con logging turno a turno. Lo que faltaba no era un reinicio de estado, sino reconocimiento de lo que el paciente realmente escribía. Se agregó además un reconocimiento ligero de saludo (`_es_saludo` — "hola", "buenas", "buenos días", etc.) que antepone "¡Hola! " a la respuesta de aclaración cuando corresponde, para que un saludo a mitad de conversación no se sienta ignorado — sin disparar ningún cambio de estado nuevo (el reinicio real ya lo cubre el mecanismo de `CIERRE` existente).

**3. Salida real para frases que no son claramente sí/no**: implementada — nuevo mensaje de aclaración explícito: *"No logré entender si es un sí o un no — ¿me confirmas si quieres que te ayude a agendar tu atención?"* (redacción sugerida por el propio usuario en el pedido), en vez de repetir la pregunta original sin ningún reconocimiento.

**4. ¿Rediseño más amplio necesario?** Sí — ver recomendación abajo, deliberadamente NO implementada en esta sesión (alcance mayor, decisión de producto, no solo de código).

## Recomendación de alcance mayor (documentada, NO implementada)

El patrón "determinista por palabras clave, con normalización de tildes agregada donde se reportó un bug" seguirá encontrando casos nuevos — cada vez que aparezca una variante real de lenguaje que nadie anticipó, hará falta otro parche puntual (van tres seguidos: 026, 027, 030). Alternativas reales para una decisión de producto, no de código:

- **Generalizar la normalización de tildes** a TODO el archivo `brain.py`/`intent.py` (`_PIDE_INFO`, `_HUMANO`, `_REPROGRAMAR`, `_CANCELAR`, `_CONFIRMA`, `_PARA_OTRO`, `_OLVIDAR` — ninguno de estos se auditó todavía contra este mismo riesgo). Esfuerzo relativamente bajo, mismo patrón ya validado tres veces.
- **Un umbral de intentos fallidos que escale automáticamente**: si el paciente lleva N turnos seguidos sin que ninguna rama lo reconozca, escalar a una persona en vez de seguir repitiendo variantes de la misma pregunta — evita que el "techo" del enfoque determinista se sienta como una trampa sin salida, incluso en el próximo caso no anticipado.
- **Un Brain real basado en LLM para esta etapa específica** (`core/brain.py:AnthropicBrain` ya existe pero nunca se activó — R-13, `.ai/RISKS.md`) — resolvería la clase ENTERA de bugs de reconocimiento de lenguaje natural, al costo de perder el determinismo 100% auditable que el proyecto ha priorizado deliberadamente hasta ahora.

Ninguna de las tres se implementó en esta sesión — quedan como recomendación explícita para una decisión del usuario, no del código.

## Verificación

- **14 tests nuevos** (`tests/domains/health/test_tildes_y_servicio_inicial.py`) — reproducen: catálogo sin tilde, "sí" sin tilde como primera palabra, el reordenamiento de prioridad (control de regresión para "no puedo asistir ahora"/"no, hablar con un asesor"), el mensaje de aclaración nuevo, y el flujo completo de "preguntar servicio primero" con un catálogo de 2 servicios (incluyendo que nombrarlo SIN tilde también reconoce el nombre real CON tilde del catálogo).
- Suite completa: **199 tests recolectados, 197 pasando + 2 deshabilitados a propósito** (antes de esta sesión: 183). Cero regresiones.
- `tests/guardrails/test_guardrails.py` — sin cambios, sigue pasando completo.
- Grep final de las frases de `_PROMESAS_PROHIBIDAS`: cero ocurrencias fuera de `guardrails/rules.py` y los comentarios que las mencionan explícitamente.
