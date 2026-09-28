# 045 — HALLAZGO CRÍTICO: gestión de beneficiario ignorada fuera de "esperando_decision" (real, en producción)

**Fecha**: 2026-09-06
**Estado**: SOLO INVESTIGACIÓN — nada corregido, tal como pediste explícitamente. Hallazgo real de producción, con `HEALTH_BRAIN_TYPE=llm` activo.
**Gravedad**: ALTA — una cita real fue reservada al nombre/documento del titular del canal cuando el paciente declaró explícitamente que era para un beneficiario (su hija).

## Resumen ejecutivo

1. **[CONFIRMADO, consulta real]**: `CITA-1bbb8bc467` (Odontologia, 2026-09-07 08:00, Consultorio 4) existe, está **CONFIRMED**, y está registrada bajo el documento 72302972 (el titular/usuario, no el beneficiario declarado).
2. **[CONFIRMADO, lectura de código]**: `_PARA_OTRO` (`domains/health/brain.py`, detección de "es para mi hija"/"es para mi mamá"/etc., recado 013) se revisa en **UN SOLO lugar de todo el archivo** — dentro de `_interpretar_decision`, el manejador de la etapa `esperando_decision` (el primer turno de la conversación). Confirmado con `grep -n "_PARA_OTRO" domains/health/brain.py` → una sola ocurrencia de uso (línea 498), más la definición de la tupla (línea 118).
3. **[CONFIRMADO, lectura de código]**: `_interpretar_servicio`, `_interpretar_fecha`, `_interpretar_horario` — las funciones que manejan CUALQUIER etapa posterior a la primera — **no tienen ningún código que revise `_PARA_OTRO`**. `_interpretar_servicio` (línea 559 en adelante) hace exclusivamente match de nombre de servicio (exacto o con tolerancia a tipeo, recado 036) — nada más.
4. **[CONFIRMADO, lectura de código]**: `HealthAnthropicBrain.interpret()` (`domains/health/llm_brain.py`) llama PRIMERO a `self._brain_determinista.interpret(message, state, recent_turns)` con el `message` completo, SIN MODIFICAR — el Brain determinista ve el mensaje íntegro del paciente ("Odontologia pero es para mi hija") ANTES de que el LLM intervenga en absoluto. El LLM solo toca `respuesta_propuesta`/`verificaciones_de_datos`/`texto_base_para_comparacion` DESPUÉS — `propuesta_de_actualizacion_de_estado` y `tool_requerida` se copian sin tocar desde la decisión determinista ya tomada.

## Respuesta directa a la pregunta central del pedido (punto 3)

**El LLM NO intercepta el mensaje antes que el código determinista.** El código determinista recibe siempre el mensaje completo, primero. El bug NO es "el LLM ocultó información del sistema real" — es que **la función determinista que procesó ese mensaje en esa etapa específica (`_interpretar_servicio`) nunca tuvo lógica para buscar una declaración de beneficiario**, con o sin LLM de por medio. Esta brecha existe desde el recado 013 y afecta EXACTAMENTE IGUAL al `HealthBrain` puro, sin ningún LLM conectado, si un paciente combina "declaro que es para un beneficiario" con la respuesta a cualquier pregunta que no sea la primera del flujo.

## El riesgo real y NUEVO que sí introduce la conexión del LLM

Aunque el LLM no causó la brecha estructural, sí la hizo más peligrosa de una forma específica: el texto redactado por Claude reconoció "tu hija" en su prosa (porque el paciente lo mencionó en su propio mensaje, y el prompt de sistema permite usar ese contexto real para el tono) — **sin que eso implique que el sistema procesó o actuó sobre esa declaración**. El paciente recibe una respuesta que SUENA como si el sistema hubiera entendido y fuera a gestionar la cita para la beneficiaria, cuando el `ConversationState` real nunca registró ningún `beneficiario_documento`, y la reserva se ejecutó exactamente como si el paciente jamás hubiera mencionado a su hija.

**Esto es un vacío de guardrail nuevo, distinto a los 3 hallazgos anteriores (recados 038, 040, 042)**: ninguno de los guardrails existentes (`DatoInventadoGuardrail`, `TipoDePreguntaAlteradaGuardrail`, `ConfirmacionEstructuradaRequeridaParaWriteGuardrail`, `FueraDeAlcanceGuardrail`, `OpinionPersonalGuardrail`) compara "lo que el paciente declaró como relevante para la decisión" contra "lo que el `ConversationState` efectivamente registró" — todos verifican datos factuales en el TEXTO, ninguno verifica coherencia entre la INTENCIÓN expresada y el ESTADO interno resultante.

## Respuesta a la pregunta 4 (¿es un caso general?)

**Sí, confirmado como estructural, no como un caso aislado.** Cualquier información que cambiaría el FLUJO de decisión (no solo el contenido a mencionar) — beneficiario declarado es el único ejemplo real conocido hoy, pero el patrón se generalizaría a cualquier declaración similar que el paciente combine con la respuesta a una pregunta distinta a la que originalmente activa esa lógica — queda silenciosamente ignorada si no se declara en la etapa EXACTA donde el código la busca. Esto es un límite del enfoque "una frase clave por etapa fija" (`.ai/RISKS.md` R-13, NLU real pendiente), expuesto con más claridad ahora que existe una capa (el LLM) que puede sonar coherente incluso cuando el flujo subyacente no lo es.

## Lo que NO se hizo en esta sesión, a propósito

- No se corrigió `_interpretar_servicio`/`_interpretar_fecha`/`_interpretar_horario` para agregar la revisión de `_PARA_OTRO`.
- No se canceló `CITA-1bbb8bc467` — queda pendiente de tu decisión explícita.
- No se diseñó ningún guardrail nuevo para la discrepancia intención-declarada vs. estado-registrado.
- No se desactivó `HEALTH_BRAIN_TYPE=llm` — esa decisión también queda en tus manos (aunque, dado que la brecha de `_PARA_OTRO` es 100% independiente del LLM, desactivarlo NO resolvería este problema específico — solo evitaría que el texto sonara como si lo hubiera resuelto).

## Limitación de esta investigación, dicha explícitamente

No tuve acceso a la transcripción completa que mencionaste como adjunta — no llegó ningún archivo a esta sesión. La reconstrucción de "en qué etapa exacta llegó el mensaje" es una inferencia razonable a partir de la evidencia de código y del resultado real (marcado `[INFERIDO]`, no `[CONFIRMADO]`) — si me compartes la transcripción real, puedo confirmar la etapa exacta con certeza en vez de inferirla.

## Pendiente de tu decisión

1. ¿Cancelo `CITA-1bbb8bc467` (mismo mecanismo real de verificación por código, con tu autorización explícita)?
2. ¿Quieres que comparta contigo la transcripción real (si la tienes a mano) para confirmar con certeza la etapa exacta, en vez de inferirla?
3. ¿Cómo quieres proceder con la corrección? (no propuesta todavía, a la espera de que confirmes que este diagnóstico es correcto antes de diseñar nada).
