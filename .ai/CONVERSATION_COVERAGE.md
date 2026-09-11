# Matriz de cobertura conversacional — ZANTIA (dominio salud)

> Recado 068 — creada para que auditar un punto nuevo de la conversación
> sea CONSULTAR esta tabla, no reconstruir la investigación desde cero
> (patrón repetido en los recados 062/063/064/066/067/068: el mismo tipo
> de hallazgo apareciendo uno a la vez en lugares distintos). Se actualiza
> en el MISMO cambio que se audita/corrige un punto — nunca "se
> documenta después" (mismo criterio que `.ai/API_CONTRACTS.md`).

**Cómo leer esta tabla**: cada fila es un punto donde el sistema espera
una respuesta específica del paciente. Las 3 columnas centrales
responden, con evidencia real (no supuesta — ver el recado que se cita
en cada fila):

- **Determinista**: ¿hay matching por palabras clave/formato exacto,
  sin necesitar ningún LLM? (Siempre la primera línea de defensa —
  gratis, sin red, sin latencia.)
- **LLM asistido**: ¿hay un último recurso que consulta un LLM
  VERIFICADO (nunca confía en la propuesta sin comprobarla contra
  valores/categorías reales — `core/selection.py`, recado 052) cuando
  lo determinista no encontró nada? "N/A (dato sensible)" significa
  que NUNCA debe haberlo, a propósito — ver la columna Notas.
- **Salir**: ¿"salir"/"exit" (coincidencia exacta, nunca fuzzy —
  recado 062) cierra la conversación desde este punto?

| # | Punto | Determinista | LLM asistido | Salir | Recado(s) | Notas |
|---|---|---|---|---|---|---|
| 1 | Menú principal (sin conversación abierta) | Sí (`_interpretar_opcion_menu`/`classify_intent_or_none_estricto`/pregunta institucional exacta) | Sí (`_clasificar_solicitud_nueva_via_llm`: menú 1-5, emocional, información institucional) | Sí | 048/056/059/064/066/068 | La versión COMPLETA de `classify_intent_or_none` (con su último recurso amplio) es el ÚLTIMO nivel, después del LLM — no antes (hallazgo del recado 068, Parte 2). |
| 2 | Selección de servicio (`esperando_servicio`) | Sí (ordinal + exacto + fuzzy typo, recado 070) | **No** — sin conectar todavía | Sí (recado 067) | 030/036/067/070 | **Hallazgo real de producción (recado 070)**: hasta el recado 070, esta era la ÚNICA de las 4 filas de "selección de una lista numerada" (#2/#3/#4/#6) que NO aceptaba el ordinal ("3" para elegir la 3ra opción) — confirmado con `git log` que fue una decisión de diseño original del recado 030/036, nunca una regresión. Un paciente real reportó exactamente este síntoma (responder "3"/"2" al catálogo numerado, sin ser reconocido). Corregido reutilizando `_indice_ordinal_seguro` (ampliado de 3 a 10 posiciones). LLM asistido sigue sin conectar — mismo hueco documentado, no corregido sin evidencia real. |
| 3 | Selección de fecha (`esperando_fecha`) | Sí (ordinal + texto libre, recado 051) | Sí (recado 052) | Sí (recado 067) | 035/051/052/067 | Ordinal limitado a mensajes de ≤8 palabras (recado 068 — ver fila de hallazgos). |
| 4 | Selección de horario (`esperando_horario`) | Sí (ordinal + texto libre, recado 051) | Sí (recado 052) | Sí (recado 067) | 035/051/052/067 | Mismo límite de 8 palabras que fecha. |
| 5 | Decisión inicial sí/no (`esperando_decision`) | Sí (`_ACEPTA`/`_DECLINA`, recado 024/053) | No aplica (binario, no una lista de opciones) | Sí (recado 067) | 024/053/067 | — |
| 6 | Selección al reprogramar (`esperando_seleccion_reprogramacion`) | Sí (ordinal, `_elegir_opcion`) | **No** — sin conectar todavía | Sí (recado 067) | 067 | Mismo hueco que selección de servicio — documentado, no corregido sin evidencia real. |
| 7 | Documento de un beneficiario (`esperando_documento_beneficiario`) | Sí (validado contra `buscar_paciente` real) | N/A (dato sensible — un documento de identidad NUNCA debe interpretarse "de forma flexible") | Sí (recado 067 — antes sin ninguna salida, ni escalamiento) | 013/067 | — |
| 8 | Confirmación de beneficiario (`esperando_confirmacion_beneficiario`) | Sí (`_es_afirmativo`) | No aplica (binario) | Sí (recado 067) | 013/067 | — |
| 9 | Wizard de código de verificación — cancelar/reprogramar (`_pending_verifications`) | Sí (código exacto contra hrmm-backend; interrupciones — salir/reenviar/pregunta correo/consulta citas/emocional — determinista+fuzzy) | Sí, SOLO para clasificar la INTERRUPCIÓN (recado 064) — el código en sí NUNCA se interpreta con LLM, siempre exacto contra el backend real | Sí (recado 062) | 009/062/064 | — |
| 10 | Wizard de identidad de canal (`_pending_identity`) | Igual que #9 | Igual que #9 (interrupción sí, documento/código nunca) | Sí (recado 063) | 012/014/063/064 | Consulta de citas redirigida sin revelar datos hasta confirmar el 2do factor (decisión de seguridad explícita, recado 063). |
| 11 | Confirmación de "olvida mis datos" (`confirmando_olvido`) | Sí (`_es_afirmativo`; cualquier otra respuesta cancela el olvido sin borrar nada y restaura la etapa anterior) | No aplica (binario) | Indirecto — cualquier no-afirmación (incluido "salir") cancela y restaura, nunca un callejón sin salida | 016/067 | Verificado explícitamente en el recado 067 que NO es un hueco real. |
| 12 | Ventana de gracia tras un cierre (`_evaluar_ventana_de_gracia`) | Sí (reevalúa las 5 categorías + despedida contra el `HealthBrain` determinista) | Hereda el de la etapa que interrumpe (no es un punto propio) | Hereda (la despedida es una de las 5 categorías reevaluadas) | 050/068 | **Hallazgo grave del recado 068**: con `HEALTH_BRAIN_TYPE=llm` activo, este mecanismo llamaba un método que NO existe en `HealthAnthropicBrain` — crasheaba con `AttributeError`. Corregido extrayendo siempre el `HealthBrain` determinista subyacente (`_brain_determinista`). |

## Hallazgos estructurales encontrados construyendo esta matriz (recado 068)

- **#2 y #6 sin LLM asistido**: nunca reportados como bug real — no se
  "corrigieron" sin evidencia, siguiendo la disciplina del proyecto
  (`.claude/rules/discovery-antes-de-modificar.md`). Quedan como
  `[CONFIRMADO — pendiente, no urgente]` hasta que un caso real lo
  amerite.
- **#12 (ventana de gracia + `HEALTH_BRAIN_TYPE=llm`)**: el `.env` real
  de esta máquina tiene `HEALTH_BRAIN_TYPE=llm` configurado — este
  hallazgo pudo estar afectando conversaciones reales en producción
  (si EasyPanel comparte esa misma configuración) sin que ningún
  recado anterior lo hubiera detectado, porque ningún test de la suite
  ejercía la combinación exacta "ventana de gracia + Brain con LLM
  activo" hasta ahora.

## Cómo mantener esta tabla al día

Cualquier cambio que toque uno de estos 12 puntos (o agregue uno
nuevo) actualiza la fila correspondiente en el MISMO commit — nunca
"se documenta después" (regla general del proyecto,
`.claude/rules/documentacion-y-memoria.md`). Si se agrega un punto
nuevo (ej. un wizard futuro), agregar una fila nueva ANTES de
implementarlo, con las 3 columnas marcadas `[PROPUESTO]` hasta que se
confirmen con evidencia real tras implementar.
