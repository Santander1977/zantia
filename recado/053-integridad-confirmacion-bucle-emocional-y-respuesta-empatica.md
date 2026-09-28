# 053 — Integridad de datos en la confirmación, bucle tras mensaje emocional, y nueva categoría de respuesta empática

**Fecha**: 2026-09-07
**Estado**: Partes 1-3 implementadas y probadas. 428 passed, 5 skipped (418 previas + 10 nuevas). Cero regresiones. **Pendiente de tu código de verificación** para completar la cancelación real de la cita mal reservada de Giselle Tornay (código ya enviado a su correo real).

---

## PARTE 1 — Integridad de datos en la confirmación (URGENTE)

### 1. Hora real registrada — CONFIRMADA con consulta real

`GET /api/agenda/citas` (documento 22669564, Giselle Tornay) contra hrmm-backend real:

```
CITA-af8f98cb8c: Psicologia, 2026-09-08, 08:00, Consultorio 6, CONFIRMED
```

**No fue solo un error de texto — se reservó la hora incorrecta de verdad.** El texto ("Quedó confirmado... a las 08:00") y la reserva real COINCIDEN — ambos están mal, de forma consistente entre sí.

### 2-3. Causa raíz — CONFIRMADA con código, distinta de tu hipótesis original

Tu hipótesis (que `DatoInventadoGuardrail` verificaba contra "cualquier hora ofrecida en la conversación" en vez de "la hora específica elegida este turno") era razonable, pero **la evidencia real apunta a otro lugar**: el guardrail nunca llegó a intervenir porque la reserva ya estaba mal ANTES de que existiera ningún texto que verificar.

`HealthBrain._elegir_opcion` (el matcher de ordinal compartido por `_interpretar_fecha`/`_interpretar_horario`/`_interpretar_seleccion_reprogramacion`) usaba `in` simple sobre las claves `"1"`/`"2"`/`"3"`:

```python
for clave, indice in mapa_ordinal.items():
    if clave in texto and indice < len(opciones):   # ANTES
        return opciones[indice]
```

`"3"` es substring literal de `"7:30"` (`"7:"` + `"3"` + `"0"`). Secuencia real reconstruida:
- Paciente: **"7"** → `_elegir_opcion` no matchea nada (correcto) → `_emparejar_horario_por_texto` (recado 051) detecta ambigüedad genuina entre 07:00/07:30 (08:00 correctamente excluido, coincide con tu propia descripción) → pide aclarar.
- Paciente: **"7:30"** → `_elegir_opcion` corre PRIMERO otra vez → `"3" in "7:30"` es `True` → interpreta esto como el ORDINAL "3" (tercera opción = 08:00) → nunca llega a ejecutarse `_emparejar_horario_por_texto`, que sí habría reconocido "7:30" correctamente.

Mismo patrón exacto que el bug real "programar"/"reprogramar" del recado 046 (`gateway.py:_interpretar_opcion_menu`) — nunca corregido en `_elegir_opcion`, el punto que de verdad decide la reserva en `brain.py`.

**Por qué ningún guardrail podía haber atrapado esto**: una vez que `_elegir_opcion` decide (mal) el slot, TODO lo demás —texto, `tool_requerida`, la reserva real— es consistente con esa decisión. `DatoInventadoGuardrail`/`SeleccionAsistidaPorLLMNoVerificadaGuardrail` (recado 052) verifican "¿es un valor REAL?" — 08:00 es un valor real, genuinamente ofrecido. Ningún guardrail puede detectar "se ejecutó correctamente sobre un dato real, pero no es el que el paciente quiso decir" — eso es un problema de INTERPRETACIÓN, resuelto en el punto donde se interpreta, no verificable después con datos.

### Corrección aplicada

```python
for clave, indice in mapa_ordinal.items():
    if re.search(_RE_PALABRA.format(re.escape(clave)), texto) and indice < len(opciones):  # AHORA
        return opciones[indice]
```

`\b...\b` exige que el dígito sea un TOKEN propio — nunca matchea dentro de "7:30", "13:00", "08:00", pero sigue reconociendo "3" sola, "opción 3", "la 3", exactamente igual que antes para esos casos reales.

### 4. Cancelación de la cita mal reservada

**Código de verificación YA ENVIADO** al correo real de Giselle (`send_verification_code("22669564")` → `{'enviado': True, 'correo_parcial': 'd***@barranquillasegura.com'}`). **Necesito el código de 6 dígitos que le llegó para completar `cancel_appointment_verified` sobre `CITA-af8f98cb8c`** — mismo mecanismo de siempre, pendiente de que me lo compartas.

### Verificación

`tests/domains/health/test_elegir_opcion_no_confunde_digito_con_ordinal.py` (5 tests): reproduce el caso EXACTO ("7" ambiguo → "7:30" reserva `SLOT-0730`, nunca `SLOT-0800`), confirma que "13"/"13 de septiembre" tampoco colisionan con ordinales, y control positivo (el ordinal literal "1"/"2"/"3"/"la segunda"/"opción 3" sigue funcionando exactamente igual).

---

## PARTE 2 — El bucle tras mensaje emocional/fuera de flujo

### 1. Confirmado: mismo patrón estructural que los recados 047/049/050

`_interpretar_opcion_menu` (gateway.py) solo se evalúa dentro de `_enrutar_solicitud_nueva` — alcanzable ÚNICAMENTE cuando no hay conversación abierta. El mensaje real ("sabes que me deprime ir al médico") no matcheaba ninguna categoría de `classify_intent_or_none` (recado 048 solo trata como "sin intención" un SALUDO puro) → cayó al default histórico `PROGRAMAR_CITA` (recado 030) → creó una Activity sintética con etapa `"esperando_servicio"`. Desde ahí, `HealthBrain._interpretar_servicio` SOLO sabe comparar contra nombres de servicio reales — nunca conoce el menú global — así que "consultar mis citas" (literal, opción 4) nunca se reconocía: mismo tipo de hueco exacto que motivó los recados 047 (interrupciones)/049-050 (ventana de gracia).

### 2-3. Corrección

Dos categorías NUEVAS en el detector CENTRALIZADO ya existente (`HealthBrain._detectar_interrupcion_de_contexto`, recado 047) — se revisan en CUALQUIER etapa de una conversación abierta, sin duplicar lógica:

- `_CONSULTA_CITAS_EXISTENTES` ("consultar mis citas", "mis citas", etc.) — llama a `appointment_service.get_patient_appointments` (real, parte del Protocol, nunca duck-typed) y devuelve las citas reales, sin cambiar de etapa.

Como este mismo detector YA es reutilizado por la ventana de gracia de un turno (recado 050, `gateway.py:_evaluar_ventana_de_gracia`, sobre la Activity que ACABA de cerrarse), **ambas correcciones se heredan gratis ahí también** — es exactamente el mensaje del caso real reportado (justo después de una reserva exitosa). No hizo falta tocar `gateway.py` en absoluto para esto.

### 3 (saludo). Por qué `_saludo_mostrado` no lo cubrió

`_saludo_mostrado` (recado 048) solo protege el camino de `_enrutar_solicitud_nueva` — nunca se llegó a evaluar ahí, porque con la corrección de Parte 3 el mensaje ahora se resuelve ANTES, dentro de la ventana de gracia (recado 050), que construye su respuesta directamente y nunca pasa por `handle_inbound_message`'s lógica de saludo en absoluto. Antes de esta corrección, el mensaje SÍ llegaba a `_enrutar_solicitud_nueva` como una solicitud "nueva" genuina (mal clasificada) — y como la conversación anterior YA había cerrado (`_cerrar_si_definitivo` libera `_saludo_mostrado` para ese `patient_reference`, correctamente, para que un ciclo REALMENTE nuevo vuelva a ver el saludo completo), este ciclo "parecía" nuevo y mostraba el saludo — un síntoma correcto de una causa equivocada (la clasificación), no un fallo de `_saludo_mostrado` en sí.

---

## PARTE 3 — Respuesta empática breve + reorientación al contexto

Nueva categoría (`_EXPRESION_EMOCIONAL`), última en el orden de prioridad del detector centralizado (una frase más específica y accionable, ej. "cancela mi cita", gana si aparece también) — reconoce frases como "me deprime", "estoy triste/angustiado/a", "me siento mal", "esto me supera". Nunca incluye ninguna palabra de `core.brain.RISK_KEYWORDS_DEMO` — la detección de riesgo real corre en el Core, ANTES e INDEPENDIENTE del Brain, con prioridad absoluta (verificado con un test explícito: un mensaje con "emergencia" sigue escalando aunque también use lenguaje emocional).

Respuesta: `"Entiendo, y lamento que te sientas así. {recordatorio breve de la etapa vigente}"` — el recordatorio (`_RECORDATORIO_BREVE_POR_ETAPA`) es una pregunta CORTA por etapa (ej. "¿me confirmas para cuál servicio te gustaría agendar?"), nunca la presentación institucional ni el catálogo/lista completa de nuevo. `etapa`/`datos` nunca cambian — el paciente retoma exactamente donde iba.

**Con `HealthAnthropicBrain`**: funciona automáticamente (mismo mecanismo de composición de siempre) — reforcé el prompt de sistema (`_PROMPT_SISTEMA`, regla 6 nueva) para que el LLM pueda variar la calidez de la validación pero NUNCA diagnostique, aconseje, ni profundice — y siempre preserve el recordatorio de contexto tal cual.

### Verificación (los 5 puntos pedidos, Partes 2-3)

Todo en `tests/domains/health/test_expresion_emocional_y_consulta_en_cualquier_etapa.py` (10 tests):
1. ✅ Reproducción EXACTA del bucle real: reserva → mensaje emocional (sin saludo repetido, sin crear Activity nueva) → "consultar mis citas" (ya no queda en loop, muestra la cita real).
2. ✅ Confirmado: menú/consulta funciona en CUALQUIER etapa de una conversación abierta (parametrizado ×5 etapas) y mensaje emocional MID-FLUJO (no ligado a cierre) tampoco reinicia.
3. ✅ Respuesta breve, empática, sin "deberías"/"te recomiendo", vuelve al contexto correcto por etapa — nunca reinicia.
4. ✅ Un mensaje con "emergencia" sigue escalando pese a sonar también emocional — el detector de riesgo real nunca se ve interferido.
5. ✅ Suite completa: **428 passed, 5 skipped** — cero regresiones.

## Archivos tocados

- `domains/health/brain.py`: `_elegir_opcion` (Parte 1, fix de word-boundary), `_CONSULTA_CITAS_EXISTENTES`/`_EXPRESION_EMOCIONAL`/`_RECORDATORIO_BREVE_POR_ETAPA`/`_es_expresion_emocional` (nuevas), `_detectar_interrupcion_de_contexto` (2 categorías nuevas), `_responder_expresion_emocional` (nuevo).
- `domains/health/llm_brain.py`: `_PROMPT_SISTEMA` regla 6 (nueva).
- Nuevos: `tests/domains/health/test_elegir_opcion_no_confunde_digito_con_ordinal.py` (5 tests), `tests/domains/health/test_expresion_emocional_y_consulta_en_cualquier_etapa.py` (10 tests).

## Pendiente de tu decisión

1. **URGENTE**: compárteme el código de verificación que le llegó a Giselle para completar la cancelación real de `CITA-af8f98cb8c`.
2. Revisar si quieres que commitee y pushee este trabajo.
3. `HEALTH_BRAIN_TYPE` sigue activo (`llm`) en tu `.env` local — sin cambios de mi parte, sigue siendo tu decisión.
