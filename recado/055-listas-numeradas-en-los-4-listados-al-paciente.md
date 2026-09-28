# 055 — Listas numeradas (una opción por línea) en los 4 listados que ZANTIA muestra al paciente

**Fecha**: 2026-09-07
**Estado**: Implementado y probado. 439 passed, 7 skipped (428 previas + 11 nuevas). Cero regresiones. Incluye 2 llamadas reales verificadas contra la API de Anthropic. **Pendiente de tu aprobación de texto/tono antes de comitear**, tal como pediste.

---

## Los 4 ejemplos exactos, confirmados contra el código real (no supuestos)

### Lugar 1 — Catálogo de servicios (`HealthBrain._ofrecer_catalogo_servicios`)

```
Claro, estas son las opciones disponibles:
1. Medicina General
2. Odontologia
3. Pediatria
4. Psicologia
5. Urgencias
¿Para cuál te gustaría agendar?
```

**Nota importante**: los nombres van EXACTAMENTE como los devuelve el catálogo real de hrmm-backend — confirmado en recados anteriores que ese catálogo real **no usa tildes** ("Odontologia", no "Odontología"). Tu ejemplo del pedido tenía tildes; no las agregué — inventar acentos que el dato real no tiene sería exactamente el tipo de alteración de datos que este proyecto evita en todos los demás guardrails. Si prefieres tildes, es un cambio en hrmm-backend (el catálogo), no en ZANTIA.

### Lugar 2 — Fechas disponibles (`HealthBrain._ofrecer_fechas`)

```
Estas son las fechas disponibles:
1. Lunes 7 de septiembre
2. Martes 8 de septiembre
3. Miércoles 9 de septiembre
¿Cuál te queda mejor?
```

Idéntico a tu ejemplo.

### Lugar 3 — Horarios disponibles (`HealthBrain._ofrecer_horarios`)

```
Para el Miércoles 9 de septiembre tengo estos horarios disponibles en Consultorio 3:
1. 07:00
2. 07:30
3. 08:00
¿Cuál prefieres?
```

Dos notas:
- **"Miércoles" con mayúscula** (no "miércoles" como en tu ejemplo) — es el mismo formato que ya produce `_formatear_fecha_humana` en TODO el resto del archivo (incluida la lista de fechas de arriba, que sí escribiste con mayúscula) — mantuve la consistencia con esa función ya existente en vez de crear una variante en minúscula solo para este lugar. Avísame si prefieres que sea distinto aquí.
- **El consultorio se menciona en la introducción SOLO si todas las opciones ofrecidas comparten el mismo** (el caso real más común: un profesional cubre ese servicio+fecha) — si dos profesionales distintos ofrecen el mismo servicio ese día con consultorios distintos, se mantiene el consultorio en cada línea (nunca se inventa un consultorio único que no sea real para todas). Verificado con un test dedicado a este segundo caso.

### Lugar 4 — Consultar mis citas (`HealthBrain._detectar_interrupcion_de_contexto`, categoría del recado 053)

```
Aquí tienes tus 6 citas activas:
1. Medicina General — Lunes 7 de septiembre, 07:00, Consultorio 2
2. Pediatria — Lunes 7 de septiembre, 08:00, Consultorio 3
3. Odontologia — Martes 8 de septiembre, 08:00, Consultorio 4
4. Odontologia — Miércoles 9 de septiembre, 07:30, Consultorio 4
5. Pediatria — Miércoles 9 de septiembre, 08:00, Consultorio 3
6. Pediatria — Martes 15 de septiembre, 10:30, Consultorio 3
```

Mismas dos notas de mayúscula/tildes que arriba (nombres de servicio tal como vienen del catálogo real, fecha con el mismo formato ya establecido en el resto del archivo). Singular correcto para 1 sola cita: "Aquí tienes tu 1 cita activa:".

## Alcance adicional (no pedido explícitamente, pero necesario para consistencia)

`domains/health/gateway.py:_resolver_consulta` tenía el MISMO texto corrido para "consultar mis citas" alcanzado desde el PRIMER contacto (sin conversación abierta todavía) — un duplicado exacto del Lugar 4, en una capa distinta (mismo patrón de duplicación entre `gateway.py`/`brain.py` ya visto en recados anteriores). Lo corregí también: sin este cambio, el mismo paciente vería un formato distinto según en qué momento de la conversación pregunte por sus citas. Reutiliza `_formatear_fecha_humana`/`_lista_numerada` importados de `brain.py` (única excepción a la separación de capas ya establecida — son funciones puras sin estado, mismo criterio que ya se usa para importar `_PROGRAMAR`/`_sin_tildes` de `intent.py`).

`domains/health/brain.py:_iniciar_reprogramacion` tiene un listado similar ("1) ...; 2) ...; 3) ...") — **deliberadamente NO tocado**: no es uno de los 4 lugares que pediste, y tocarlo habría sido alcance no solicitado.

## Hallazgo real encontrado al implementar (corregido en el mismo trabajo)

`guardrails/rules.py:TipoDePreguntaAlteradaGuardrail` detecta si un mensaje es "una pregunta de selección" buscando "¿Cuál...?" O al menos 2 marcadores `"1)"`/`"2)"` — el nuevo formato usa `"1."`/`"2."` con salto de línea real, que ese regex **nunca reconocía**. En la práctica el guardrail seguía funcionando porque los 4 mensajes también contienen "¿Cuál...?" (detectado por la otra mitad del OR) — pero era una coincidencia, no una garantía: un mensaje con lista numerada sin esa palabra exacta se habría quedado sin esta protección. Corregido ampliando el patrón para reconocer AMBOS formatos (`\b[1-3]\)` para el formato en línea que `_iniciar_reprogramacion` sigue usando, más `(?:^|\n)\s*[1-3]\.` para el nuevo formato de lista).

## Prompt de sistema reforzado (regla 7, nueva)

`domains/health/llm_brain.py:_PROMPT_SISTEMA` — regla 7 explícita: cualquier lista numerada en el "mensaje de contenido" debe preservarse EXACTAMENTE (mismo número de opciones, mismo texto, mismo orden, cada una en su propio renglón) — el LLM solo puede reformular la introducción y la pregunta final, nunca el contenido de la lista. Incluye un ejemplo explícito de qué NO hacer (fusionar la lista en una oración con comas). También actualicé el ejemplo de la regla 5 (preservar el TIPO de pregunta), que todavía citaba el formato viejo "1) ... 2) ...".

## Verificación (los 5 puntos pedidos)

Todo en `tests/domains/health/test_listas_numeradas.py` (11 tests + 2 gateados):

1. ✅ Los 4 lugares, formato exacto con salto de línea real — confirmado contra `MockAppointmentService` con datos de prueba reales.
2. ✅ `HealthAnthropicBrain` preserva el formato con un drafter simulado bien portado, y **2 llamadas REALES contra la API de Anthropic** (`ZANTIA_RUN_REAL_LLM_TESTS=1`, corridas en esta sesión) confirmando que Claude real no reformula ninguna de las 2 listas probadas (catálogo de 5 servicios, fechas de 3 opciones) en prosa.
3. ✅ Caso de una sola opción — catálogo con 1 servicio y "consultar mis citas" con 1 cita, ambos mantienen el formato de lista con "1." (y singular correcto "tu 1 cita activa").
4. ✅ Caso vacío (catálogo sin servicios, citas sin ninguna activa) — sigue con el mensaje simple de siempre, sin forzar una lista vacía.
5. ✅ Suite completa: **439 passed, 7 skipped** — cero regresiones. Solo 2 tests preexistentes necesitaron actualizarse (esperaban la fecha ISO cruda en "consultar mi cita", ahora correctamente en formato humano — consecuencia esperada de la mejora, no una regresión accidental).

## Archivos tocados

- `domains/health/brain.py`: `_lista_numerada` (nueva), Lugares 1-4 reformateados.
- `domains/health/gateway.py`: `_resolver_consulta` (Lugar 4, duplicado) reformateado; import de `_formatear_fecha_humana`/`_lista_numerada` desde `.brain`.
- `domains/health/llm_brain.py`: `_PROMPT_SISTEMA` regla 7 (nueva) + ejemplo de regla 5 actualizado.
- `guardrails/rules.py`: `_RE_OPCION_NUMERADA` ampliado para reconocer el nuevo formato.
- `tests/domains/health/test_bidirectional_gateway.py`: 1 test actualizado (fecha humana en vez de ISO).
- `tests/domains/health/test_expresion_emocional_y_consulta_en_cualquier_etapa.py`: 1 test actualizado (idem).
- Nuevo: `tests/domains/health/test_listas_numeradas.py` (11 tests + 2 gateados).

## Pendiente de tu decisión

1. **Aprobación de texto/tono** — pediste explícitamente no comitear hasta confirmar los 4 ejemplos. Dos puntos concretos a confirmar: (a) nombres de servicio sin tildes (dato real del catálogo, no los agregué), (b) "Miércoles"/días con mayúscula en Lugar 3 y 4 (consistente con el resto del archivo, distinto de tu ejemplo en minúscula).
2. Revisar si quieres que commitee y pushee este trabajo.
3. El recado 054 (correo de confirmación nunca enviado) sigue pendiente de tu decisión de producto — no relacionado con este trabajo, documentado por separado.
