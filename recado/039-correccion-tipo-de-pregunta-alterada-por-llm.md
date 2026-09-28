# 039 — Corrección del hallazgo del Caso 2 (recado 038): tipo de pregunta alterado por el LLM

**Fecha**: 2026-09-06
**Estado**: implementado, probado (286 passed, 3 skipped), **con evidencia real repetida** — sin commitear todavía, pendiente de tu revisión.
**Continúa**: recado 038 (hallazgo del "Caso 2" en la primera llamada real a Claude).

## Resultado más importante — respuesta directa a tu pregunta

> "dime cuál de los dos fue el que realmente lo detuvo esta vez"

**El prompt reforzado (Parte 1) resolvió el problema por sí solo, en las 4 llamadas reales que hice para confirmarlo** (2 en la corrida completa de los 3 casos + 2 repeticiones adicionales del Caso 2 específico, para no confiar en una sola muestra dado que un LLM no es 100% determinista). En ninguna de las 4 corridas reales el guardrail nuevo tuvo que intervenir — Claude preservó "¿Cuál prefieres?" en las 4.

**Esto NO significa que el guardrail (Parte 2) esté de más.** Un LLM no es determinista: la ausencia de fallas en 4 muestras es evidencia real, pero no una garantía para la muestra 5, 50 o 500. El guardrail queda como la RED DE SEGURIDAD estructural — si el prompt alguna vez fallara (un mensaje del paciente más ambiguo, un cambio de modelo, cualquier variación), el guardrail sigue ahí para que el paciente nunca vea la pregunta mal formulada. Verificado con un test de regresión que reproduce el Caso 2 exacto de forma sintética (nunca depende de que la red real vuelva a fallar para poder probarlo).

## Parte 1 — Prompt reforzado

Regla 5 agregada a `_PROMPT_SISTEMA` (`domains/health/llm_brain.py`), con el Caso 2 real como ejemplo explícito de qué NO hacer:

```
5. Si el "mensaje de contenido" termina en una pregunta que espera que el paciente ELIJA entre varias opciones ya enumeradas (por ejemplo, contiene "¿Cuál...?" o una lista numerada como "1) ... 2) ..."), tu respuesta reformulada DEBE seguir siendo ese MISMO tipo de pregunta — nunca la conviertas en una pregunta de sí/no, ni asumas que el paciente ya eligió una opción, aunque su mensaje anterior te dé esa impresión. Ejemplo de lo que NUNCA debes hacer: si el mensaje de contenido es "Para el Martes 8 de septiembre, estos son los horarios disponibles: 1) 09:00 en Sede Norte; 2) 10:30 en Consultorio 2. ¿Cuál prefieres?", NUNCA respondas algo como "Entonces quedarías agendado a las 10:30 en Consultorio 2. ¿Confirmamos esa cita?" — eso asume una elección que el paciente todavía no confirmó de forma verificable. La forma correcta es mantener la pregunta abierta, por ejemplo: "Para el martes 8 de septiembre tengo estos horarios: 09:00 en Sede Norte o 10:30 en Consultorio 2. ¿Cuál prefieres?"
```

## Parte 2 — `TipoDePreguntaAlteradaGuardrail` (Core, agnóstico de dominio)

### Dónde vive y por qué

Lo puse en **Core** (`guardrails/rules.py`), no en `domains/health/`: la detección ("¿Cuál...?" y/o al menos 2 marcadores numerados "1)"/"2)") es sobre la ESTRUCTURA genérica de una pregunta de selección por chat — no depende de vocabulario de salud/citas. Cualquier dominio futuro que ofrezca opciones numeradas comparte esta misma forma, mismo criterio que ya justificó poner `FueraDeAlcanceGuardrail` en Core (recado 037) aunque también use frases hardcodeadas en español.

### Cómo funciona

1. `HealthAnthropicBrain` ahora también declara `BrainOutput.texto_base_para_comparacion` (nuevo campo, `None` por default — nunca poblado por un Brain 100% determinista) con el texto ANTES de la redacción del LLM.
2. `Orchestrator` lo reenvía a `GuardrailContext.texto_base_para_comparacion`.
3. `TipoDePreguntaAlteradaGuardrail.evaluate()`: si no hay nada que comparar, o el texto base no era una pregunta de selección → ALLOW inmediato (nunca interfiere con nada más). Si el texto base SÍ era una pregunta de selección y el texto redactado dejó de serlo → **`MODIFY`, restaurando el texto base tal cual** como `modified_response`.

### Nota de transparencia — diferencia con `DatoInventadoGuardrail`

Al diseñar esto encontré que tu descripción original ("bloquear y usar texto_base tal cual, igual que ya hace DatoInventadoGuardrail cuando bloquea") no era del todo exacta: revisando `core/orchestrator.py`, un `BLOCK` de `DatoInventadoGuardrail` **no restaura el texto base** — genera un mensaje genérico ("No puedo continuar con esa acción todavía: ..."). Para este guardrail nuevo, como SÍ tenemos el texto base exacto disponible, usé **`MODIFY`** (no `BLOCK`) para restaurarlo literalmente — mejor experiencia para el paciente (sigue viendo la pregunta real, no una disculpa genérica) y evita romper la conversación. No toqué el comportamiento existente de `DatoInventadoGuardrail` (ya committeado en el recado 037) — señalado aquí como una inconsistencia real entre ambos guardrails, no corregida en esta sesión por estar fuera de lo pedido.

## Verificación (los 4 puntos pedidos)

1. ✅ **Test que reproduce el Caso 2 exacto** — `tests/guardrails/test_tipo_de_pregunta_alterada.py::test_caso_2_real_queda_bloqueado_y_se_restaura_el_texto_base` (con los textos REALES, literales, del recado 038) + `tests/domains/health/test_llm_brain.py::test_guardrail_de_tipo_de_pregunta_restaura_el_texto_base_reproduciendo_caso_2` (de extremo a extremo, contra el `Orchestrator`/`GuardrailEngine` reales, confirmando además que el turno SIGUIENTE del paciente — un ordinal — sigue siendo interpretable).
2. ✅ **Test de que el Caso 1 (reformulación válida) NO se bloquea** — `test_caso_1_real_reformulacion_valida_no_se_bloquea`, con los textos reales literales del Caso 1.
3. ✅ **Prueba real repetida** — ver "Resultado más importante" arriba. 4 llamadas reales, las 4 preservaron el tipo de pregunta con el prompt reforzado.
4. ✅ **Suite completa**: 286 passed, 3 skipped (280 anteriores + 6 nuevos) — cero regresiones.

## Archivos tocados

- `domains/health/llm_brain.py`: regla 5 en `_PROMPT_SISTEMA`; `HealthAnthropicBrain.interpret()` ahora también declara `texto_base_para_comparacion`.
- `core/brain.py`: `BrainOutput.texto_base_para_comparacion: Optional[str] = None`.
- `guardrails/base.py`: mismo campo en `GuardrailContext`.
- `guardrails/rules.py`: `_es_pregunta_de_seleccion`, `TipoDePreguntaAlteradaGuardrail`, agregado a `reglas_core_por_defecto()`.
- `guardrails/__init__.py`: export del guardrail nuevo.
- `core/orchestrator.py`: reenvía el campo nuevo al `GuardrailContext`.
- Nuevo: `tests/guardrails/test_tipo_de_pregunta_alterada.py` (5 tests).
- `tests/domains/health/test_llm_brain.py`: 1 test nuevo de extremo a extremo.

## Pendiente de tu revisión

1. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo — ningún cambio de comportamiento real todavía.
2. La inconsistencia `BLOCK` (genérico) vs `MODIFY` (restaura texto base) entre `DatoInventadoGuardrail` y `TipoDePreguntaAlteradaGuardrail` queda documentada — decisión tuya si quieres unificar el criterio en una sesión futura.
3. Con este hallazgo corregido y confirmado con evidencia real, ¿autorizas avanzar a una prueba en Telegram real, o prefieres seguir revisando el mecanismo primero?
4. Revisar si quieres que commitee y pushee este trabajo.
