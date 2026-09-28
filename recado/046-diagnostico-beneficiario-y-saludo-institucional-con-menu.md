# 046 — Diagnóstico crítico de beneficiario (sin corregir) + saludo institucional con menú numerado

**Fecha**: 2026-09-06
**Estado**: Parte 1 completa (solo diagnóstico, nada corregido). Parte 2 implementada y probada (329 passed, 4 skipped, incluida 1 llamada real). `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo, no se probó Telegram.

---

## PARTE 1 — Diagnóstico completo: cita mal asignada al beneficiario (SIN CORREGIR)

### 1. Estado real de la cita — CONFIRMADO con consulta real

`CITA-1bbb8bc467`: Odontologia, 2026-09-07 08:00, Consultorio 4, **status: CONFIRMED**, documento 72302972 (el titular, no la beneficiaria declarada). Reconsultado dos veces en esta sesión, sin cambios.

### 2. Causa raíz — CONFIRMADA con ejecución de código real, no supuesta

`_PARA_OTRO` (`domains/health/brain.py`, detección de "es para mi hija"/etc., recado 013) se revisa en **UN SOLO lugar de todo el archivo**: dentro de `_interpretar_decision`, el manejador de la etapa `esperando_decision` (confirmado con `grep -n "if etapa =="` sobre todo `brain.py` — 8 etapas listadas, `_PARA_OTRO` solo vive en el bloque de la primera). `_interpretar_servicio`, `_interpretar_fecha`, `_interpretar_horario` no tienen ningún código que la busque.

Reproducido con una llamada REAL a `HealthBrain._interpretar_servicio` con el mensaje exacto reportado:

```
mensaje: "Odontologia pero es para mi hija"
texto_base (determinista): "Estas son las fechas disponibles: 1) Lunes 7 de septiembre. ¿Cuál te queda mejor?"
etapa resultante: esperando_fecha
beneficiario_documento presente: False
```

Y la llamada REAL correspondiente a Claude sobre ese mismo texto base:

```
texto redactado (Claude real): "¡Claro que sí! Tengo disponible el lunes 7 de septiembre para la cita de odontología de tu hija. ¿Te queda bien esa fecha?"
```

### 3. ¿El LLM intercepta el mensaje? — CONFIRMADO QUE NO

`HealthAnthropicBrain.interpret()` llama PRIMERO a `self._brain_determinista.interpret(message, state, recent_turns)` con el `message` completo, sin modificar. El LLM solo toca `respuesta_propuesta`/`verificaciones_de_datos`/`texto_base_para_comparacion` DESPUÉS de que la decisión determinista (estado, `tool_requerida`) ya está fijada. El código determinista SIEMPRE ve el mensaje íntegro — el problema es que, en la etapa donde este mensaje cayó, ninguna función revisa `_PARA_OTRO`.

### 4. ¿Es un caso general? — SÍ, confirmado con evidencia de código, más amplio de lo reportado inicialmente

Revisando TODAS las ramas de "interrupción" de `_interpretar_decision` (`grep` sobre cada `_contains_any(texto, ...)` de esa función), encontré que **5 categorías completas**, no solo `_PARA_OTRO`, están igual de acotadas a la etapa `esperando_decision`:

| Categoría | Qué detecta | Dónde se revisa |
|---|---|---|
| `_INFO_NO_AUTORIZADA` | Pedido de información clínica no autorizada | Solo `esperando_decision` |
| `_HUMANO` | Solicitud de escalar a una persona | Solo `esperando_decision` |
| `_NO_PUEDE_AHORA` | Paciente no puede seguir ahora | Solo `esperando_decision` |
| `_PIDE_INFO` | Pide más información antes de decidir | Solo `esperando_decision` |
| `_PARA_OTRO` | Declaración de beneficiario | Solo `esperando_decision` |

En contraste, `_OLVIDAR` y `_REPROGRAMAR`/`_CANCELAR`/`_CONFIRMA` SÍ se revisan en CUALQUIER etapa (al inicio de `interpret()`, antes del dispatch) — confirmado que esas 5 categorías de arriba son la excepción, no la norma del archivo.

**Esto significa, con evidencia de código, no especulación**: si un paciente dice "quiero hablar con un asesor" mientras responde CUÁL servicio quiere, o menciona que necesita información clínica no autorizada mientras elige una fecha, esas señales también se pierden en silencio — el mismo patrón estructural exacto que causó el bug del beneficiario, mucho antes de que existiera cualquier LLM. La conexión del LLM no creó esta brecha — la hizo más peligrosa, porque ahora el texto puede sonar como si la señal SÍ se hubiera procesado.

### Ejemplos concretos adicionales, para tu evaluación (NINGUNO implementado)

- Paciente menciona una alergia real ("soy alérgico a la penicilina, ¿me pueden anotar eso?") mientras confirma un horario — `HealthBrain` no tiene NINGÚN mecanismo para capturar información clínica (correctamente, por diseño — ZANTIA no es un sistema clínico), pero el LLM podría reconocerlo empáticamente en su redacción, dando al paciente la falsa impresión de que quedó registrado en algún lado.
- Paciente describe una urgencia real con palabras DISTINTAS a las 4 de `RISK_KEYWORDS_DEMO` (genérico, no clínico, R-1/R-13 — ej. "si no me ven hoy se puede complicar mucho") mientras responde otra pregunta — el detector determinista de riesgo (`core/orchestrator.py:detect_risk_keywords`) sí corre de forma independiente en TODO mensaje (a diferencia de `_PARA_OTRO`), pero solo reconoce ese vocabulario fijo — este es el caso de mayor gravedad potencial de toda la lista, aunque técnicamente es un límite YA conocido (R-1), no uno nuevo.

## No corregido, tal como pediste explícitamente

Nada de `brain.py` se tocó en esta sesión para esta Parte 1. Queda completamente a tu decisión cómo y cuándo abordarlo.

---

## PARTE 2 — Saludo institucional consistente + menú numerado

### Decisión de diseño clave: NO bloqueante (confirmada contigo a mitad de la implementación)

Mi primer intento fue un menú BLOQUEANTE (esperar la respuesta 1-4 antes de procesar cualquier cosa) — rompió 84 tests existentes, porque intercepta y difiere CUALQUIER intención que el paciente ya haya expresado en su primer mensaje. Te pregunté y elegiste la opción **no bloqueante**: el saludo + menú se antepone SIEMPRE como guía visible, pero si el mensaje ya tiene una intención clara, se procesa en el mismo turno. Con este diseño, la migración de tests bajó de 84 a solo 3 ajustes (dos textos de saludo desactualizados, más un hallazgo real nuevo, ver abajo).

### Hallazgo real encontrado al migrar los tests (corregido en el mismo trabajo)

**"programar" es substring literal de "reprogramar"** ("re" + "programar"). Mi primer intento de interpretación de menú usaba `in` simple, así que CUALQUIER mensaje de reprogramar matcheaba la opción 1 (reservar) por error — y además, incluir las listas completas de `intent.py` (`_PROGRAMAR`, etc.) en mi propia función se saltaba el orden de prioridad YA establecido en `classify_intent` (recado 027: "Programar cuál servicios tienes disponible" debe clasificarse como pregunta de catálogo, no como reserva, precisamente por contener la palabra "programar"). Corregido:
1. Límite de palabra (`\b`) en TODOS los chequeos de `_interpretar_opcion_menu`, no solo el ordinal.
2. `_interpretar_opcion_menu` ya NO incluye las listas completas de `intent.py` — solo agrega las formas BARE que `classify_intent` nunca reconocía por sí solo ("reservar", "cancelar", "consultar" como palabra suelta). "reprogramar" ya lo maneja `classify_intent` correctamente, con su propio orden de prioridad intacto.

### Implementación

- `domains/health/gateway.py`: `_saludo_segun_hora_bogota` (America/Bogota real, `zoneinfo` estándar — confirmado con una prueba real dentro del contenedor Docker que la base de zonas horarias SÍ está disponible en `python:3.11-slim`, sin paquete adicional), `_tratamiento_formal` (heurística documentada: nombre termina en "a" → "señora", si no → "señor" — sin fuente de dato real de género, ni en `identity_store` ni en `buscar-paciente` de hrmm-backend), `_MENU_NUMERADO` (4 líneas fijas), `_interpretar_opcion_menu`, `_saludo_primer_contacto`.
- El guion se construye ENTERAMENTE en `gateway.py`, concatenado FUERA de cualquier llamada a `HealthBrain.interpret()`/`HealthAnthropicBrain` — estructuralmente imposible que el LLM lo altere (no hizo falta reforzar el prompt de sistema para esto: nunca se le muestra el texto del saludo).
- Paciente nuevo: `"{hora}. Soy Andrés, tu asistente virtual para la gestión de tus citas médicas del Hospital Regional del Magdalena Medio. ¿Qué deseas hacer?\n1. Reservar una cita\n2. Reprogramar una cita\n3. Cancelar una cita\n4. Consultar mis citas"` — antepuesto al mensaje que sea, incluyendo el que pide documento.
- Paciente reconocido: `"¡{hora}, {tratamiento} {nombre}! ¿Qué desea hacer hoy?\n{mismo menú}"` — sin repetir "soy Andrés".
- Opción 4 ("Consultar mis citas"): `RequestIntent.CONSULTAR_CITA` → `_resolver_consulta` YA EXISTÍA y ya usa `get_patient_appointments` — no hizo falta conectar nada nuevo, solo reutilizar el dispatch existente (extraído a `_resolver_por_intent` para reutilizarlo desde `_enrutar_solicitud_nueva` sin duplicar lógica).
- `_enrutar_solicitud_nueva` ahora usa `_interpretar_opcion_menu(text) or classify_intent(text)` — mejora estrictamente aditiva (nunca cambia una clasificación que ya funcionaba, solo agrega interpretación correcta para ordinales/palabras sueltas que antes caían al default incorrecto).

### Verificación (los 5 puntos pedidos)

1. ✅ Saludo completo + menú para paciente nuevo, 3 franjas horarias — `test_saludo_completo_paciente_nuevo_3_franjas_horarias`.
2. ✅ Saludo personalizado + menú para paciente reconocido — `test_saludo_personalizado_paciente_reconocido`.
3. ✅ Menú acepta número Y palabra para las 4 opciones — `test_interpretar_opcion_menu_acepta_numero_o_palabra` (parametrizado).
4. ✅ Contenido/formato numerado nunca se pierde con `HEALTH_BRAIN_TYPE=llm` — probado con drafter simulado agresivo Y con 1 llamada REAL nueva a Anthropic (`test_saludo_y_menu_nunca_pasan_por_el_llm_con_llamada_real`, gateada por `ZANTIA_RUN_REAL_LLM_TESTS`, corrida en esta sesión: 25/25 tests pasaron incluyendo la real).
5. ✅ Suite completa: **329 passed, 4 skipped** — cero regresiones.

## Archivos tocados

- `domains/health/gateway.py`: saludo institucional, menú numerado, `_interpretar_opcion_menu`, `_resolver_por_intent` (extraído), wiring en `handle_inbound_message`.
- `tests/domains/health/test_nombre_y_tono_humano.py`: 2 tests actualizados al nuevo guion.
- Nuevo: `tests/domains/health/test_saludo_institucional.py` (25 tests).

## Pendiente de tu decisión

1. **Parte 1**: ¿cómo y cuándo quieres abordar la brecha estructural (5 categorías de interrupción acotadas a `esperando_decision`)? No till propuesta de corrección todavía, a la espera de tu criterio.
2. **Parte 1**: ¿cancelo `CITA-1bbb8bc467` con el mecanismo real de verificación, como en casos anteriores?
3. **Parte 2**: revisar si quieres que commitee y pushee este trabajo.
4. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo.
