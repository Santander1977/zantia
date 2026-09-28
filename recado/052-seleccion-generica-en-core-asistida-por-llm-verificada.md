# 052 — Mecanismo genérico en el Core: interpretación de selección asistida por LLM, siempre verificada

**Fecha**: 2026-09-07
**Estado**: Implementado y probado. 413 passed, 5 skipped (390 previas + 23 nuevas). Cero regresiones. Incluye 1 llamada real contra la API de Anthropic, confirmada. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo — pendiente de tu aprobación de diseño/tono antes de considerar esto cerrado, tal como pediste.

---

## Contexto rápido: qué pasó en este repo desde el recado 048

Antes de este trabajo, otra sesión (con el protocolo "RECADO PARA CHATGPT") avanzó los recados 049-051 sobre este mismo repositorio: ventana de gracia tras cierre de conversación (050), y — el más relevante para este recado — reconocimiento flexible de fecha/horario en `_interpretar_fecha`/`_interpretar_horario` (051): ordinal, día de semana, número de día, fecha/hora completa. Este recado 052 construye directamente sobre esa base (recado 051, sin tocarlo) para el ÚLTIMO nivel de reconocimiento: lenguaje verdaderamente libre ("la del medio") que ninguna regla determinista puede anticipar.

## 1. Dónde vive el mecanismo genérico y por qué ahí

**`core/selection.py`** (nuevo módulo de Core, agnóstico de dominio). Contiene:
- `SelectionOption(id, text)` — una opción real ofrecida este turno.
- `SelectionProposer` (Protocol) — `propose(free_text, options) -> Optional[str]`.
- `AnthropicSelectionProposer` — implementación real (import perezoso de `anthropic`, mismo criterio que `core.brain.AnthropicBrain`/`domains.health.llm_brain.AnthropicResponseDrafter`).
- `interpret_selection(free_text, options, proposer) -> SelectionResult` — **único punto de entrada seguro**: nunca devuelve una opción que no esté literalmente en `options` (por `id`), nunca deja pasar una excepción del proposer sin capturarla, nunca elige si el proposer alucina un id o si dos opciones comparten id por error del dominio.

**Por qué en `core/` y no en `domains/health/` ni en `guardrails/`**: el Core ya tiene un componente estructuralmente equivalente y probado — `core.brain.AnthropicBrain`/`domains.health.llm_brain.AnthropicResponseDrafter` — un colaborador que un dominio puede usar OPCIONALMENTE, con el mismo patrón de import perezoso, gate por variable de entorno, y verificación posterior. `core/selection.py` sigue ese MISMO patrón para un problema distinto (interpretar una selección, no redactar texto), y por eso vive junto al resto del contrato Core↔Brain, no dentro de `domains/health/`: cualquier dominio futuro (seguridad ciudadana, el ejemplo que diste) que necesite "el usuario elige entre varias opciones reales ya ofrecidas" lo importa tal cual, sin reconstruirlo — `core/selection.py` no importa nada de `domains/`, ni sabe que existen fechas, horarios, ni citas.

## 2. Decisión de diseño: verificación INTERNA al mecanismo, no un guardrail que reemplaza el flujo — pero SÍ un guardrail como segunda capa

Pediste decidir y justificar entre "verificación interna" o "guardrail de Core separado". Implementé **ambos**, con roles distintos:

1. **Verificación interna (`interpret_selection`)** — la garantía PRIMARIA. Un guardrail de Core solo actúa DESPUÉS de que el Brain ya construyó su `BrainOutput` completo (`tool_requerida`, cambios de estado) — para una selección, eso es demasiado tarde: no queremos que el Brain llegue a proponer `book_appointment` con un `slot_id` sin verificar y confiar en que un guardrail lo bloquee después. La selección debe verificarse ANTES de que el Brain decida qué hacer con ella — por eso `interpret_selection` es quien verifica, dentro del propio mecanismo, no un guardrail.
2. **`SeleccionAsistidaPorLLMNoVerificadaGuardrail` (Core, `guardrails/rules.py`)** — SEGUNDA capa, independiente. Mismo patrón declarativo que `DatoInventadoGuardrail`: el dominio declara, vía `VerificacionDeSeleccion` (nueva, `guardrails/base.py`) en `BrainOutput.verificacion_de_seleccion`, qué ids eran reales este turno y cuál se aceptó vía LLM; el guardrail (agnóstico, no sabe qué es una fecha) vuelve a comparar. Con un mecanismo correctamente implementado, esta regla SIEMPRE hace ALLOW en la práctica — existe por el mismo motivo que `ConfirmacionEstructuradaRequeridaParaWriteGuardrail` existe pese a que ningún Brain de hoy la viola: convertir una invariante que hoy solo sostiene la disciplina del código en un contrato explícito y auditable por el Core, a prueba de un Brain futuro (de cualquier dominio) que se salte la verificación interna por accidente.

Verificado con un forzado deliberado a nivel de GUARDRAIL (sin pasar por `interpret_selection`, construyendo `GuardrailContext` a mano con una `VerificacionDeSeleccion` deliberadamente inconsistente) — confirma que la segunda capa, por sí sola, también bloquea.

## 3. Conexión con `domains/health/`

`HealthBrain.__init__` gana un parámetro opcional `selection_proposer: Optional[SelectionProposer] = None` (default `None` → cero cambio de comportamiento/cero llamada de red para cualquier construcción existente, incluida toda la suite de tests). `_interpretar_fecha`/`_interpretar_horario` ahora prueban, en este orden:

1. Ordinal (`_elegir_opcion`, sin cambios).
2. Texto libre específico del dominio (recado 051: día de semana, número de día, fecha/hora completa).
3. **Si ninguno de los dos encontró NADA (ni ambigüedad)** — nuevo método `_interpretar_seleccion_asistida_por_llm`, que arma `List[SelectionOption]` con las fechas/horas REALES de `datos["fechas_ofrecidas"]`/`datos["horas_ofrecidas"]` (`domains/health/` nunca le pasa al Core nada más que texto + un id determinista que el propio dominio ya usa — el Core nunca supo que eran fechas) y llama a `core.selection.interpret_selection`.
4. Si tampoco hay nada — el fallback rotativo de siempre (recado 034), sin cambios.

**Orden determinista-primero, justificado por costo/latencia**: el matching determinista (pasos 1-2) es gratis e instantáneo, y ya cubre la inmensa mayoría de respuestas reales (ordinal, día de la semana, fecha exacta). Consultar un LLM en cada turno, incluso cuando el determinista ya resolvió todo, gastaría una llamada de red real sin ningún beneficio. El LLM solo se consulta cuando de verdad hace falta — lenguaje genuinamente libre que ninguna regla anticipó. La ambigüedad genuina (2+ candidatos deterministas) tampoco consulta al LLM: ya es, por sí sola, suficientemente informativa (se le muestran ambas opciones reales en disputa), y resolverla con una llamada real no aporta nada que el mensaje de aclaración ya no ofrezca.

**Garantía de determinismo preservada**: una vez que `interpret_selection` verifica la propuesta, el `id` devuelto (la fecha/hora real) se usa EXACTAMENTE igual que si hubiera llegado por ordinal — mismo `_ofrecer_horarios`/mismo `tool_requerida={"name": "book_appointment", ...}`/mismo `confirmacion_estructurada_para_write=True`. Verificado con una prueba dedicada que compara el `BrainOutput` completo de ambos caminos con la MISMA Activity (`test_seleccion_via_llm_produce_decision_identica_a_elegir_por_ordinal`) — idénticos salvo `verificacion_de_seleccion` (que solo puebla el camino asistido, por diseño).

`domains/health/config.py:build_health_brain()` activa `selection_proposer` con el MISMO gate que ya existía para la redacción de texto (`HEALTH_BRAIN_TYPE=llm` + `ANTHROPIC_API_KEY` configurada) — ningún env var nuevo, ninguna decisión de activación separada.

## 4. Verificación (los 6 puntos pedidos)

- `tests/core/test_selection.py` (9 tests) — unidad, agnóstico de dominio (ejemplo de "trámites", no de salud).
- `tests/guardrails/test_seleccion_llm_guardrail.py` (4 tests) — el guardrail en sí, forzando el caso de fallo a mano.
- `tests/domains/health/test_seleccion_asistida_por_llm.py` (10 tests + 1 gateado) — conexión real con `HealthBrain`.

1. ✅ Interpretación exitosa con lenguaje natural variado: "la del medio", "esa que dijiste primero", "la última que mencionaste" (fecha) y "la del medio" (horario) — con un proposer de prueba que interpreta usando la LISTA COMPLETA de opciones (igual que lo haría un LLM real), nunca vocabulario de dominio.
2. ✅ Guardrail (y el mecanismo mismo) bloqueando una interpretación alucinada: `test_no_avanza_si_el_llm_alucina_una_opcion_que_no_fue_ofrecida`/`test_no_avanza_ni_reserva_si_el_llm_alucina_un_horario` — confirmado que ni la fecha ni la reserva avanzan, y `test_bloquea_una_seleccion_alucinada...` a nivel de guardrail puro.
3. ✅ Fallback correcto sin LLM disponible: `test_sin_selection_proposer_configurado_usa_solo_la_logica_deterministica` — "la del medio" sin `selection_proposer` cae al mensaje de aclaración de siempre, nunca falla.
4. ✅ Selección verificada = valor determinista idéntico al ordinal: `test_seleccion_via_llm_produce_decision_identica_a_elegir_por_ordinal` (`tool_requerida`/`confirmacion_estructurada_para_write`/`propuesta_de_actualizacion_de_estado` idénticos).
5. ✅ Prueba real contra la API de Anthropic, gateada por `ZANTIA_RUN_REAL_LLM_TESTS` (mismo patrón que recado 038): `test_seleccion_asistida_por_llm_contra_la_api_real` — corrida en esta sesión, **Claude real interpretó correctamente "la del medio, por favor" como la fecha del martes** (la opción intermedia de 3 fechas reales).
6. ✅ Suite completa: **413 passed, 5 skipped** — cero regresiones.

Adicional (no pedido explícitamente, pero necesario para cerrar el hueco de "¿el guardrail de verdad recibe esto en producción?"): `test_de_extremo_a_extremo_por_el_orchestrator_y_guardrails_reales` — conversación completa a través de `Orchestrator`/`GuardrailEngine` REALES (no solo llamadas directas a `HealthBrain`), confirmando que `verificacion_de_seleccion` llega hasta el guardrail y una selección legítima asistida por LLM nunca se bloquea en el camino real.

## Archivos tocados

- Nuevo: `core/selection.py` (`SelectionOption`, `SelectionResult`, `SelectionProposer`, `AnthropicSelectionProposer`, `interpret_selection`).
- `guardrails/base.py`: `VerificacionDeSeleccion` (nueva), campo `verificacion_de_seleccion` en `GuardrailContext`.
- `guardrails/rules.py`: `SeleccionAsistidaPorLLMNoVerificadaGuardrail` (nueva), agregada a `reglas_core_por_defecto`.
- `guardrails/__init__.py`: exports nuevos.
- `core/brain.py`: campo `verificacion_de_seleccion` en `BrainOutput`.
- `core/orchestrator.py`: `GuardrailContext(..., verificacion_de_seleccion=brain_output.verificacion_de_seleccion)`.
- `domains/health/brain.py`: `HealthBrain.__init__(..., selection_proposer=None)`, `_interpretar_seleccion_asistida_por_llm` (nuevo), `_interpretar_fecha`/`_interpretar_horario` (tercer nivel de intento).
- `domains/health/config.py`: `build_health_brain()` construye `AnthropicSelectionProposer` bajo el mismo gate que la redacción de texto.
- Nuevos: `tests/core/test_selection.py`, `tests/guardrails/test_seleccion_llm_guardrail.py`, `tests/domains/health/test_seleccion_asistida_por_llm.py`.

## Pendiente de tu decisión

1. **Aprobación de diseño/tono** — pediste explícitamente no dar esto por cerrado hasta tu revisión.
2. Revisar si quieres que commitee y pushee este trabajo.
3. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo.
4. Dominio futuro (seguridad ciudadana, mencionado como ejemplo): cuando exista, reutiliza `core/selection.py` tal cual — no requiere ningún cambio en este mecanismo, solo que ese dominio arme sus propias `SelectionOption` con sus propios ids/textos.
