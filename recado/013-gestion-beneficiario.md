# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Gestión "en nombre de otro paciente" — separar identidad del CANAL (titular, resuelta en recado 012) de identidad del BENEFICIARIO (para quién es la gestión), extensión de R-15.
Objetivo: Documentar cómo se distingue "gestor" de "beneficiario" en el modelo de datos y en el EventLog, y el resultado de las pruebas.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = decisión o dato aún no confirmable, nunca inventado.

---

## Resumen ejecutivo

HECHO: implementado el flujo de "gestión para un beneficiario" en `domains/health/brain.py` (**primera vez que se toca este archivo en todo el proyecto** — protegido explícitamente en las fases 007-012, autorizado por el usuario de forma explícita solo para esta fase) y una extensión mínima de auditoría en `domains/health/agent.py`. **120 tests pasando + 1 deshabilitado a propósito** (121 recolectados) — 5 tests nuevos, 0 de los 115 tests previos modificados o rotos.

**NO se tocó** (restricción explícita del usuario, verificada): la tabla/mecanismo de `identidad_canal` (`HealthGateway._identidad_resuelta`, `_gestionar_identificacion`) ni el sub-flujo de verificación por código (`_iniciar_verificacion_para_gestion`, `_enviar_codigo_y_pausar`, `_procesar_intento_de_codigo`) — todos sin cambios, sin tests nuevos sobre ellos.

## Distinción gestor / beneficiario en el modelo de datos

Documentado formalmente en `.ai/DATA_MODEL.md` (regla `fuente-de-verdad.md`) — resumen:

- **Titular del canal**: quién tiene el número/canal (resuelto por el gate de identidad, 012, vive en `HealthGateway._identidad_resuelta`).
- **Gestor**: el titular, en el momento de una gestión concreta — siempre `Activity.patient_reference` para una Activity sintética iniciada por el paciente. NO cambia aunque la gestión sea para un beneficiario.
- **Beneficiario**: la persona para quien es la cita, cuando es distinta del titular — vive en `ConversationState.datos_recopilados["beneficiario_documento"]`/`["beneficiario_nombre"]` (por conversación, ámbito de `HealthBrain`), nunca en el modelo `Activity` (no se tocó `domains/health/models.py`).

**Regla de uso**: `AppointmentService` (disponibilidad/reserva) SIEMPRE recibe el documento del BENEFICIARIO cuando existe uno confirmado — nunca el del gestor. Esto es lo que hace que R-15 quede realmente resuelto para este caso, no solo "declarado".

## Mecanismo (flujo de 3 turnos)

1. **Declaración** (en cualquier momento de la etapa `esperando_decision`): el titular dice algo que matchea `_PARA_OTRO` (`"es para mi mamá"`, `"para mi hijo"`, etc.) — `HealthBrain._interpretar_decision` detecta la frase y pide el documento del beneficiario. Gateado por `getattr(appointment_service, "buscar_paciente", None) is not None` (mismo duck-typing que ya usa `resolve_patient_identity` en `gateway.py`, sin importar nada de ahí — cero acoplamiento nuevo entre Brain y Gateway) — con `MockAppointmentService` esta frase se ignora COMPLETAMENTE, comportamiento idéntico al de antes de esta extensión (requisito #5, verificado con test dedicado).
2. **Validación del documento**: el siguiente mensaje se interpreta como el documento del beneficiario (`_interpretar_documento_beneficiario`) — se llama `buscar_paciente(documento)` (mismo `GET /citas/buscar-paciente` público, 009). Si no hay match: mensaje claro, se puede reintentar, NO se inventa ni se continúa. Si hay match: se guarda el par documento/nombre como "candidato" y se pide confirmación explícita.
3. **Confirmación explícita**: el titular debe responder afirmativamente (mismo vocabulario `_ACEPTA` ya usado en el resto de `HealthBrain`) a "Vamos a agendar para {nombre} — ¿es correcto?". Solo entonces `beneficiario_documento`/`beneficiario_nombre` pasan de "candidato" a confirmados, y el flujo continúa a ofrecer disponibilidad (reutilizando la MISMA lógica que la aceptación directa del titular — extraída a `_ofrecer_disponibilidad`, sin duplicar código).

En `_interpretar_seleccion` (donde se arma la tool `book_appointment`), el `patient_reference` del payload es `datos.get("beneficiario_documento") or self._activity.patient_reference` — solo cambia cuando hay un beneficiario confirmado; el caso por defecto (titular gestiona para sí mismo) usa exactamente el mismo valor que antes de esta extensión.

## Auditoría en EventLog (requisito #4)

En `agent.py:handle_patient_message`, justo donde YA se registraba `APPOINTMENT_CONFIRMED` (sin tocar esa parte), se agregó un bloque que — SOLO si `resultado.state.datos_recopilados.get("beneficiario_documento")` está presente — registra un evento adicional:

```python
context.orchestrator.events.record(
    context.activity.activity_id, EventType.STATE_TRANSITION,
    evento="GESTION_EN_NOMBRE_DE_BENEFICIARIO",
    gestor_documento=context.activity.patient_reference,
    beneficiario_documento=beneficiario_documento,
)
```

`gestor_documento` y `beneficiario_documento` son campos SEPARADOS y explícitos del payload del evento — nunca fusionados en un solo string (requisito #4, verificado con `test_eventlog_registra_gestor_y_beneficiario_por_separado`). Se reutilizó `EventType.STATE_TRANSITION` (ya existente en `observability/events.py`, Core) en vez de inventar un `EventType` nuevo — evita tocar el Core para esto.

El caso por defecto (titular gestiona para sí mismo) NO genera ningún evento nuevo — verificado explícitamente (`test_titular_gestiona_para_si_mismo_sin_cambios` confirma que la lista de eventos `GESTION_EN_NOMBRE_DE_BENEFICIARIO` queda vacía).

## Bug real encontrado y corregido (no oculto)

`HealthBrain.interpret()` hace `texto = message.lower().strip()` al inicio, para el matching de palabras clave — esto se aplicaba SIN QUERER también al documento del beneficiario cuando la etapa era `esperando_documento_beneficiario`, corrompiendo cualquier documento con letras (ej. `"BENEF-002"` → `"benef-002"`) antes de compararlo contra `buscar_paciente`. Encontrado al correr el test con un documento de prueba alfanumérico (no representativo de una cédula colombiana real, que es solo dígitos — por eso este bug no se habría notado con documentos puramente numéricos, pero es una corrección real de todas formas). Corregido: la rama `esperando_documento_beneficiario` en `interpret()` ahora pasa `message.strip()` (el mensaje ORIGINAL, sin lowercase) en vez de `texto` (la versión lowercaseada) a `_interpretar_documento_beneficiario`.

## Mejora opcional (requisito #6) — declarada PENDIENTE, no implementada

"Recordar la relación" (ej. etiqueta "mamá" → documento ya validado, para no repetir la búsqueda en conversaciones futuras) requeriría una nueva capa de persistencia que:
- Viva MÁS ALLÁ de una sola conversación (el titular puede tener Activities distintas en días distintos) — `ConversationState.datos_recopilados` (donde vive hoy `beneficiario_documento`) es por conversación, se pierde al cerrar la Activity.
- Se inyecte como una dependencia NUEVA en el constructor de `HealthBrain` (hoy solo recibe `activity_provider` y `appointment_service`) — implica tocar la firma de `HealthBrain.__init__`, y todos los lugares donde se construye (`agent.py:build_health_agent_context`).
- Se mantenga sincronizada con `buscar_paciente` en el momento de CADA reutilización (requisito #6: "debe seguir siendo un documento verificado... nunca aceptado sin validar"), no solo al guardarla.

Esto es un cambio de diseño, no una extensión de bajo esfuerzo — se declara PENDIENTE explícitamente, no se inventa una versión simplificada que no cumpla el requisito de re-validación. Documentado en `.ai/RISKS.md` R-15.

## Alcance no cubierto, declarado explícitamente

El flujo de beneficiario solo cubre RESERVA (vía `HealthBrain`, `PROGRAMAR_CITA`). Reprogramar/cancelar contra `HrmmAppointmentService` real pasan por el wizard de verificación por código en `gateway.py` (`_iniciar_verificacion_para_gestion`, explícitamente NO TOCADO por instrucción del usuario) — ese wizard sigue usando la identidad del titular ya resuelta (`_documento_resuelto`, recado 012), sin ninguna noción de beneficiario. Extenderlo sería un trabajo separado, no incluido aquí.

## Tests

Nuevo archivo: `tests/domains/health/test_beneficiario_gestion.py` (5 tests, contra `HrmmAppointmentService` real con `FakeHttpClient` — sin red real):

1. `test_titular_gestiona_para_si_mismo_sin_cambios` — PASA. Sin declarar beneficiario, la reserva usa el documento del titular, exactamente como antes; cero eventos `GESTION_EN_NOMBRE_DE_BENEFICIARIO`.
2. `test_titular_declara_beneficiario_valido_reserva_usa_su_documento` — PASA. "es para mi mamá" + documento válido → la reserva real (verificada en el `POST /api/agenda/citas` capturado por el `FakeHttpClient`) usa el documento del BENEFICIARIO, no el del titular.
3. `test_documento_beneficiario_invalido_no_continua` — PASA. Documento no encontrado → mensaje claro, la etapa se queda en `esperando_documento_beneficiario` (puede reintentar), CERO llamadas de reserva.
4. `test_eventlog_registra_gestor_y_beneficiario_por_separado` — PASA. Confirma el evento `GESTION_EN_NOMBRE_DE_BENEFICIARIO` con `gestor_documento` y `beneficiario_documento` en campos distintos y distintos entre sí.
5. `test_mock_appointment_service_ignora_la_frase_de_beneficiario` — PASA (control adicional, no pedido explícitamente pero de bajo costo). Confirma que `MockAppointmentService` ignora "es para mi mamá" por completo.
6. (Requisito #5 de la mejora opcional — reutilizar relación guardada): NO APLICA, la mejora opcional no se implementó (ver arriba).
7. Suite completa: `.venv/bin/pytest -q` → **120 passed, 1 skipped**. Comando ejecutado y confirmado en esta sesión — 0 de los 115 tests previos modificados.

## Pendiente (no resuelto aquí, ni inventado)

- Mejora opcional de "recordar la relación" (ver sección dedicada arriba).
- Extender el flujo de beneficiario a reprogramar/cancelar vía el wizard de verificación (`gateway.py`, Hrmm) — fuera de alcance de este pedido.
- Probar este mecanismo contra la red real de hrmm-backend (sigue bloqueado por no tener `HRMM_BACKEND_SECRET`).
- Decisión de producto sobre pacientes genuinamente nuevos (titular o beneficiario) que `buscar-paciente` no encuentra — heredada de recado 012, sin resolver.

RECADO GENERADO: /Users/enzoalfonso/recado/013-gestion-beneficiario.md
