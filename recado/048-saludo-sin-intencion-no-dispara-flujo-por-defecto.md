# 048 — "hola" (sin intención) ya no dispara el flujo de reserva por defecto en el mismo turno

**Fecha**: 2026-09-06
**Estado**: Implementado y probado. 350 passed, 4 skipped (337 previas + 13 nuevas). Cero regresiones. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo del repo.

---

## 1. Causa raíz exacta (confirmada con código, no supuesta)

`domains/health/gateway.py:_enrutar_solicitud_nueva` clasifica cualquier mensaje sin conversación previa con:

```python
intent = _interpretar_opcion_menu(text) or classify_intent(text)
```

`_interpretar_opcion_menu("hola")` devuelve `None` correctamente (no reconoce ningún ordinal/palabra del menú). El problema estaba en `domains/health/intent.py:classify_intent`: al no coincidir con ninguna categoría específica, **siempre** devolvía `RequestIntent.PROGRAMAR_CITA` por defecto (decisión documentada del recado 030: "se trata como intención de programar, dado que es el punto de entrada más seguro"). Esa decisión tenía sentido **antes** de que existiera el menú institucional (recado 046) — sin menú, algo había que hacer con un mensaje ambiguo. Con el menú ya construido, ese mismo default hace que **cualquier** mensaje sin palabras clave reconocidas — incluido un saludo puro como "hola" — dispare de inmediato `_resolver_programar_cita`: crea una `Activity` sintética, registra el contexto, y devuelve "¿para cuál servicio te gustaría agendar?" — todo en el MISMO turno que el saludo+menú, sin esperar a que el paciente responda al menú.

No es que el diseño "no bloqueante" del recado 046 tratara "hola" como si tuviera intención — es que `classify_intent` nunca tuvo, hasta ahora, ninguna forma de decir "no hay ninguna intención aquí, ni siquiera ambigua" — su contrato siempre fue "devuelve algo útil".

## 2. Comportamiento correcto (confirmado contigo, ahora implementado)

- **"hola" (sin ninguna otra palabra de contenido)** → el turno termina mostrando SOLO el saludo institucional + menú. No se crea ninguna `PatientRequest` ni `Activity`. La etapa de "espera" es, literalmente, la ausencia de cualquier conversación abierta — el siguiente mensaje se re-evalúa desde cero.
- **Responder al menú después** ("1", "reservar", etc.) → `_interpretar_opcion_menu` lo reconoce de inmediato (sin pasar por `classify_intent` en absoluto) y AHÍ SÍ avanza a la pregunta de servicio — en el turno siguiente, nunca en el mismo que "hola".
- **Mensaje con intención clara desde el primer turno** ("necesito una cita de pediatría") → sigue funcionando exactamente igual que antes (diseño no bloqueante del recado 046, intacto): el saludo se antepone, pero el flujo avanza de una vez, sin pasar por el menú.

## 3. Diseño de la corrección

### 3.1. `classify_intent_or_none` (nueva, `domains/health/intent.py`)

Misma cadena de chequeos que `classify_intent`, pero distingue explícitamente "mensaje que es ÚNICAMENTE un saludo" (nueva función `_es_solo_saludo`, mismo vocabulario que `brain.py:_SALUDOS`, deliberadamente duplicado — mismo criterio ya documentado en el archivo para `_INFORMACION`) de "mensaje ambiguo pero con contenido":

- `"hola"`, `"buenas tardes"`, `"¿qué tal?"` → `_es_solo_saludo` es `True` → devuelve `None`.
- `"Sí, claro, ayúdame, puedes orientarme mejor"` (recado 030, sigue intacto) → no matchea ningún saludo de `_SALUDOS` → conserva el default `PROGRAMAR_CITA` de siempre.
- `"hola, necesito una cita"` → nunca llega a evaluarse como saludo puro, porque ya matcheó `_PROGRAMAR` ANTES en la misma cadena (orden de chequeo sin cambios).

`classify_intent` (la función existente, usada por todo lo demás) ahora es un envoltorio de una línea: `classify_intent_or_none(text) or RequestIntent.PROGRAMAR_CITA` — su contrato NO cambió para ningún llamador existente (un saludo puro sigue devolviendo `PROGRAMAR_CITA` ahí también). Solo `gateway.py` usa la versión que distingue el caso `None`.

### 3.2. `gateway.py` — no crear nada cuando no hay intención

`_enrutar_solicitud_nueva` ahora usa `_interpretar_opcion_menu(text) or classify_intent_or_none(text)`; si el resultado es `None`, devuelve `None` sin crear ninguna `PatientRequest`/`Activity`. `handle_inbound_message` interpreta ese `None` como "no avanzar" — devuelve solo el saludo/menú.

Un detalle que hizo falta cubrir: si el paciente sigue escribiendo mensajes ambiguos ("hola" dos veces seguidas), el saludo institucional completo (presentación de "Andrés", nombre del hospital) NO debe repetirse turno tras turno — se agregó `HealthGateway._saludo_mostrado` (un `set[str]` de `patient_reference`), poblado la primera vez que se le muestra el saludo mientras todavía no existe ninguna conversación abierta para él. Un segundo mensaje ambiguo recibe un recordatorio corto del menú (`_MENSAJE_INTENCION_NO_RECONOCIDA`), no la presentación completa de nuevo. Esta marca se libera en `_cerrar_si_definitivo` (mismo punto donde se libera `_open_conversations`) para que un ciclo de conversación genuinamente NUEVO, más adelante, sí vuelva a ver el saludo completo — mismo criterio que ya aplicaba al camino de intención clara.

## 4. Verificación (los 4 puntos pedidos)

Todo en `tests/domains/health/test_saludo_sin_intencion_no_avanza.py` (13 tests nuevos), contra un `HrmmAppointmentService` real con 2 servicios (Medicina General + Odontologia — con un solo servicio el hallazgo no sería observable, porque `_determinar_servicio_inicial` nunca pregunta):

1. ✅ `test_hola_sin_intencion_muestra_solo_saludo_y_menu`: "hola" → saludo + menú, "servicio"/"fechas disponibles" NUNCA aparecen en la respuesta, cero `PatientRequest` creada, `find_open_context` sigue `None`.
2. ✅ `test_tras_hola_responder_al_menu_avanza_a_pregunta_de_servicio` (×2, "1" y "reservar"): el turno SIGUIENTE sí pregunta servicio, sin repetir la presentación institucional completa; ahora sí existe una `PatientRequest`/contexto real.
3. ✅ `test_mensaje_con_intencion_clara_sigue_avanzando_de_una_vez`: "necesito una cita de pediatría" en el primer turno sigue avanzando de inmediato (diseño no bloqueante del recado 046 intacto).
4. ✅ Suite completa: **350 passed, 4 skipped** (337 previas + 13 nuevas) — cero regresiones, incluidas las dos que antes dependían del default de `classify_intent` para un mensaje ambiguo CON contenido (recado 030, `test_respuesta_afirmativa_sin_tilde_como_primera_palabra_avanza` y su variante) — confirmado que siguen pasando sin cambios.

Adicional (no pedido explícitamente, pero necesario para no dejar un hueco nuevo): `test_segundo_hola_seguido_no_repite_la_presentacion_completa` — dos "hola" seguidos no repiten el guion institucional completo, solo un recordatorio corto del menú.

## Archivos tocados

- `domains/health/intent.py`: `classify_intent_or_none` (nueva), `_es_solo_saludo`/`_SALUDOS`/`_RE_SALUDOS`/`_RE_PUNTUACION` (nuevas), `classify_intent` (ahora delega, sin cambiar su contrato).
- `domains/health/gateway.py`: `_saludo_mostrado` (nuevo campo en `HealthGateway`), `_MENSAJE_INTENCION_NO_RECONOCIDA` (nueva constante), `_enrutar_solicitud_nueva` (devuelve `Optional[str]`, usa `classify_intent_or_none`), `handle_inbound_message` (maneja el caso `None`), `_cerrar_si_definitivo` (libera `_saludo_mostrado`).
- Nuevo: `tests/domains/health/test_saludo_sin_intencion_no_avanza.py` (13 tests).

## Pendiente de tu decisión

1. Revisar si quieres que commitee y pushee este trabajo.
2. El push de los 2 commits del recado 047 (`8d37606`, `9837724`) sigue bloqueado por el clasificador de modo automático — `origin/main` sigue en `f37e24d`. Necesito que lo corras tú (`! git push origin main`) o que ajustes el permiso, según lo que ya te reporté.
3. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo.
