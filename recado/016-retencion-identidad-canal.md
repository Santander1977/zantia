# RECADO PARA CHATGPT

Fecha: 2026-09-03
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Política de retención de `identidad_canal` (R-20) — vencimiento automático a 180 días + eliminación a pedido del paciente ("olvida mi información")
Objetivo: Documentar la implementación, el bug real encontrado (una escalación falsa disparada por una transición de fase inválida), y el resultado de las 8 pruebas pedidas.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = no resuelto, nunca inventado.

---

## Resumen ejecutivo

HECHO: R-20 (`.ai/RISKS.md`) pasó de ABIERTO a **MITIGADO**. Dos decisiones de producto del usuario, ambas implementadas:

1. **Vencimiento automático a 180 días** (`domains/health/identity_store.py:RETENCION_IDENTIDAD_DIAS`, constante única y nombrada). `IdentidadCanal.vigente()` — VERIFICADO y dentro de la ventana. Vencida, se trata como si no existiera, sin mensaje especial, wizard completo de nuevo. Re-verificar actualiza `verificado_en` (UPSERT ya existente desde 014), nunca duplica fila.
2. **Eliminación a pedido del paciente**: `HealthBrain` (`brain.py:_OLVIDAR`) detecta la intención en CUALQUIER etapa de una conversación abierta, exige confirmación explícita, y `gateway.py:_procesar_olvido_si_corresponde` ejecuta el borrado REAL (`identity_store.eliminar`) + registra `IDENTIDAD_ELIMINADA_A_PEDIDO` en EventLog.

HECHO: **142 tests pasando + 2 deshabilitados a propósito** (144 recolectados) — 12 tests nuevos de esta fase (6 en `test_identidad_persistente.py`, 6 en `test_identidad_olvido.py`, nuevo), 0 de los 130 anteriores rotos.

## La constante de 180 días — dónde vive

```python
# domains/health/identity_store.py
RETENCION_IDENTIDAD_DIAS = 180
```
Único lugar del proyecto que define este valor. `IdentidadCanal.vigente(ahora=None) -> bool` la usa; `gateway.py` la consume solo a través de `.vigente()`, nunca repite el número. Requisito #1.3 del pedido ("constante nombrada y fácil de encontrar/cambiar") cumplido literalmente.

## Frases detectadas para "olvido" (`brain.py:_OLVIDAR`)

```
olvida mi número / olvida mi numero / olvida mi información / olvida mi informacion
olvida mis datos / olvídame / olvidame
borra mi número / borra mi numero / borra mi información / borra mi informacion / borra mis datos
elimina mi información / elimina mi informacion / elimina mis datos
no quiero que tengas mis datos / deja de guardar mis datos
```
Conjunto razonable, no exhaustivo — mismo criterio que el resto de conjuntos de palabras clave de `brain.py` (sin NLU real, ver R-13).

## Mecanismo (arquitectura)

- **`HealthBrain.interpret()`**: el chequeo de `_OLVIDAR`/etapa `"confirmando_olvido"` corre ANTES que cualquier otro dispatch (incluso antes de reprogramar/cancelar/confirmar) — misma prioridad que una interrupción global del Core. Wizard de 2 pasos propio (`confirmando_olvido` → `olvido_confirmado`), sin tocar ningún campo del flujo de beneficiario (013).
- **El Brain nunca borra nada** — solo propone el cambio de etapa a `"olvido_confirmado"`. El borrado real vive en `gateway.py:_procesar_olvido_si_corresponde` (llamado tras cada `handle_patient_message` en la rama de conversación abierta de `handle_inbound_message`), porque `identity_store` es un servicio de `HealthGateway` (compartido por el proceso), no de `HealthAgentContext` (por Activity) — mismo criterio arquitectónico usado para la hidratación de identidad (014).
- Solo una aceptación clara (`_ACEPTA`, vocabulario ya existente) confirma; cualquier otra respuesta restaura la etapa exacta previa (`etapa_antes_de_olvido`), sin perder el lugar del paciente en la conversación.

## Bug real encontrado y corregido (no oculto)

La rama de "el paciente NO confirmó" proponía `proxima_accion_propuesta="preguntar_intencion"` — copiado sin pensar del patrón usado en otras partes de `_interpretar_decision`. Un test de esta misma extensión (`test_declina_no_borra_nada`) reveló que esto disparaba una **escalación REAL** (`fase_actual -> ESCALADO_ESTANDAR`, mensaje "Voy a pasar tu caso al equipo...") en vez de simplemente cancelar la solicitud de olvido.

Causa raíz, investigada con trazas manuales del Orchestrator/GuardrailEngine (no fue un guardrail — ambos evaluaron ALLOW): `core/orchestrator.py:handle_message` calcula la fase siguiente y llama `validate_transition(fase_actual, siguiente_fase)`; si es inválida, **captura la excepción y escala automáticamente** ("error de transición"). `"preguntar_intencion"` mapea a `IDENTIFICACION_DE_INTENCION`, una transición que `state/machine.py:VALID_TRANSITIONS` NO permite desde `RECOPILACION_DE_DATOS` (la fase típica cuando el olvido se pide a mitad de, por ejemplo, `"esperando_seleccion"`). Corregido: `"preguntar_dato_faltante"` (válida desde cualquier fase relevante, ya usada correctamente en la rama de inicio del olvido).

Esto es un hallazgo real sobre el propio Core (validación de transiciones + escalamiento automático ante error), no solo sobre esta extensión — vale la pena que cualquier BrainOutput nuevo que se agregue a este proyecto revise contra qué fase actual puede ejecutarse antes de elegir `proxima_accion_propuesta`.

## Resultado de las 8 pruebas pedidas

1. **Verificada hace menos de 180 días → reconocimiento automático**: PASA (`test_identidad_reciente_se_reconoce_automaticamente_via_gateway`).
2. **Verificada hace más de 180 días → wizard completo de nuevo**: PASA (`test_identidad_vencida_dispara_wizard_completo_de_nuevo`) — confirmado que NO aparece ningún mensaje de "venció".
3. **Re-verificación tras vencimiento → actualiza sin duplicar**: PASA (`test_reverificacion_tras_vencimiento_actualiza_sin_duplicar_fila`) — `SELECT COUNT(*)` confirma 1 sola fila.
4. **"Olvida mi número" → pide confirmación**: PASA (`test_pide_confirmacion_antes_de_borrar`) — fila sigue existiendo, EventLog vacío.
5. **Confirma → borra de verdad + EventLog**: PASA (`test_confirmado_borra_la_fila_y_registra_evento`) — `store.get()` devuelve `None`, evento `IDENTIDAD_ELIMINADA_A_PEDIDO` con `telefono`/`documento` en el payload.
6. **Pide olvidar pero no confirma → NO se borra**: PASA, dos variantes: `test_declina_no_borra_nada` (respuesta explícita "no") y `test_declina_restaura_la_etapa_anterior_y_la_conversacion_continua` (además confirma que la conversación sigue funcionando con normalidad después).
7. **No afecta beneficiario ni Activity**: PASA, dos tests — `test_no_interfiere_con_flujo_de_beneficiario` (declara beneficiario, interrumpe con olvido, declina, confirma que `beneficiario_documento_candidato` sigue intacto y la reserva final usa el documento del beneficiario) y `test_camino_activity_outbound_sigue_funcionando_igual` (demanda inducida completa sin mencionar olvido, sin cambios de comportamiento).
8. **Suite completa 100%**: PASA — 142 passed, 2 skipped (los 2 tests de red real deshabilitados a propósito, sin relación con este cambio).

## Alcance no cubierto, declarado explícitamente

- El olvido solo se detecta dentro de una conversación YA abierta (rama `contexto_existente` de `gateway.py:handle_inbound_message`) — un primer mensaje de un teléfono SIN conversación previa que diga "olvida mi información" se clasifica por `intent.py` como cualquier otra intención y nunca llega a `HealthBrain` (la conversación inbound nueva alimenta una frase canónica fija al Brain, no el texto crudo del paciente — ver docstring de `_resolver_programar_cita`).
- `agent.py:handle_reminder_response` (respuesta a un recordatorio) no pasa por `gateway.py`, así que el olvido tampoco se detecta ahí.
- Ninguna de las dos limitaciones se corrigió (no pedido) — ambas quedaron documentadas en `docs/health-demand-agent.md` y en el docstring de `_procesar_olvido_si_corresponde`.

## Documentación actualizada

`.ai/RISKS.md` (R-20 → MITIGADO, R-3 anotada como parcialmente cubierta), `.ai/DATA_MODEL.md` (política de retención real), `.ai/TESTING.md`, `docs/health-demand-agent.md` (nueva sección).

RECADO GENERADO: /Users/enzoalfonso/recado/016-retencion-identidad-canal.md
