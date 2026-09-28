# 059 — Correo de confirmación real (054), brecha de despliegue del 058 y salida garantizada del menú

**Fecha**: 2026-09-07
**Estado**: Implementado, probado, **commiteado y pusheado** (ver hash al final, verificado con `git log` + `git ls-remote`).

---

## 1. Tu pregunta más urgente, respondida primero: ¿se comiteó el 058?

**No.** Confirmado con evidencia real ANTES de tocar nada más, tal como pediste:

```
$ git log --oneline -1
f7db18a feat: bug "todo junto" corregido, saludo corto tras cierre, indicador de escritura en Telegram (recado 057)

$ git status --short
 M domains/health/brain.py
 M domains/health/gateway.py
 M domains/health/hrmm_appointment_service.py
 M domains/health/models.py
 M domains/health/tools.py
?? tests/domains/health/test_pregunta_correo_y_despedida.py

$ git ls-remote origin main
f7db18ad0c20014594b265575b52ad90f7560a3b	refs/heads/main
```

`origin/main` seguía en `f7db18a` (recado 057) — el trabajo del recado 058 (categorías de despedida/correo) nunca llegó a commitearse ni desplegarse, porque tu mensaje de aprobación llegó mientras yo ya había arrancado el trabajo del 054 a pedido tuyo explícito ("implementa primero el recado 054, ya priorizado"), y ese commit combinado quedó pendiente hasta ahora. **Esto explica el 100% del bucle de 6+ turnos que reportaste** — producción no tenía absolutamente ninguna detección de despedida todavía.

Encontré, además, dos huecos reales en el propio vocabulario del 058 (todavía sin desplegar) que tu transcripción nueva expuso: "chao" no estaba en ninguna lista, y "no gracias q tengas buenas noches" no coincidía con ningún patrón existente. Corregidos en este mismo trabajo (sección 3).

## 2. Correo de confirmación real (recado 054, implementado)

### Qué se descubrió

El recado 054 (diagnóstico) ya había encontrado, leyendo el código real de hrmm-backend, que `POST /api/agenda/citas` **nunca** dispara ningún correo — existe un endpoint aparte, `POST /citas/{id}/enviar-confirmacion` (genérico y público, sirve para reservar/cancelar/reprogramar por igual), que hay que llamar explícitamente.

Al implementar esto encontré algo más: **`tests/domains/health/test_flujo_en_etapas_y_correo.py` (recado 035, del 2026-09-06) ya asumía que hrmm-backend enviaba el correo de forma nativa** — una decisión de producto que en su momento confirmaste, pero que nunca se verificó contra el código real del backend. Era falsa. ZANTIA llevaba dos días prometiendo en texto un correo que nunca se enviaba de verdad. Actualicé esos 3 tests para reflejar la realidad (ver sección 5) y dejé la nota en el propio archivo.

### Qué se implementó

- `HrmmAppointmentService.enviar_confirmacion_email(appointment_id, correo)` — llama al endpoint real.
- `_intentar_enviar_confirmacion(appointment_id, correo)` — best-effort: si no hay correo, no intenta nada (`None`); si falla, lo registra en logs y sigue (`False`) — **nunca revierte ni rompe la reserva/cancelación/reprogramación ya exitosa**.
- `book_appointment` / `cancel_appointment_verified` / `reschedule_appointment_verified` ahora aceptan un `correo` opcional y disparan el envío real; el resultado (`Appointment.correo_confirmacion_enviado`: `True`/`False`/`None`) viaja con la cita.
- El mensaje final al paciente (tras reservar/cancelar/reprogramar, en `agent.py` y en el sub-flujo de código de `gateway.py`) es ahora **dinámico** según ese resultado real — nunca una promesa ciega.

### Los textos finales (los que pediste ver antes de aprobar)

**Sufijo tras confirmar una acción** (`sufijo_confirmacion_correo`):
- Envío confirmado: *" Te enviamos un correo de confirmación con todos los detalles."*
- Envío intentado y fallido: *" Intentamos enviarte un correo de confirmación, pero no pudimos verificar que llegara — si no te llega, avísame y lo revisamos con el equipo."*
- Nunca intentado (sin correo conocido — el caso de hoy, siempre): **cadena vacía** — se omite el tema por completo, en vez de forzar una frase sobre algo que no ocurrió.

**Respuesta a "¿me enviaste el correo?"** (`respuesta_pregunta_sobre_correo` — nunca vacía, una pregunta directa merece respuesta directa):
- Envío confirmado: *"Sí — te enviamos la confirmación por correo, deberías tenerla en tu bandeja."*
- Envío intentado y fallido: *"Intentamos enviarte la confirmación por correo, pero no pudimos verificar que llegara. Si no te llegó, avísame y lo revisamos con el equipo."*
- Nunca intentado: *"Buena pregunta — hoy no tenemos un correo tuyo registrado en este canal, así que no se envió ninguna confirmación por ese medio."*

### Un límite real que sigue abierto (documentado en `.ai/RISKS.md` R-21)

Este mecanismo queda completo y probado, pero **hoy siempre se ejecuta con `correo=None`**, porque ZANTIA no captura el correo del paciente en ningún punto de la conversación (ni el catálogo de `buscar_paciente` lo trae, ni ningún wizard lo pide). Habilitar el caso "éxito" de verdad requiere una decisión de producto nueva y separada (¿se pide el correo en la conversación? ¿se reutiliza uno ya registrado en hrmm-backend por otro canal?) — fuera de alcance de este trabajo, documentado, no decidido en tu nombre.

## 3. Vocabulario de despedida ampliado

Añadido a `_DESPEDIDA` (brain.py), con la misma disciplina de evitar falsos positivos:

- **"chao" / "chau" / "adios"** — únicas palabras sueltas de toda la lista (el resto exige 3+ palabras): una despedida coloquial en español no necesita ningún acompañamiento para ser inequívoca.
- **"que tengas buen" / "q tengas buen"** — cubre "que tengas buen día/buena tarde/buenas noches", con la abreviatura real "q" que usaste en tu propio ejemplo.

Deliberadamente **no** agregué "salir"/"terminar" sueltos aquí: dentro de una conversación en curso tienen falsos positivos reales ("quiero terminar de agendar" significa seguir, no cerrar). Esas dos palabras se reconocen en cambio SOLO en el contexto sin ambigüedad del menú (sección 4).

## 4. Salida garantizada del menú (5ta opción)

### Diseño (mismo mecanismo existente, sin camino nuevo)

- `RequestIntent.SALIR` — un valor más en el mismo enum que ya usan las otras 4 opciones del menú.
- `_MENU_NUMERADO` ahora incluye `"5. Salir / terminar"` — aparece automáticamente en el saludo institucional Y en `_MENSAJE_INTENCION_NO_RECONOCIDA` (ambos ya interpolaban esta misma constante, cero código nuevo para eso).
- `_MENU_OPCIONES` gana una entrada más: `("5", RequestIntent.SALIR, ("salir", "terminar"))` — reconocida por la MISMA función `_interpretar_opcion_menu` que ya resolvía "1"-"4".
- `_resolver_por_intent` gana una rama más para `RequestIntent.SALIR` — misma despedida cálida del recado 058 (`_texto_despedida`, extraída a su propia función para que brain.py y gateway.py compartan el mismo texto exacto, nunca una copia duplicada).

### El hallazgo que hizo falta para que esto realmente cierre el bucle

Tu transcripción real ("No gracias q tengas buenas noches", "Chao", etc.) ocurrió **sin ninguna conversación abierta todavía** — el paciente nunca había elegido ninguna opción del menú. El detector de despedida de brain.py (`_es_despedida`/`_DESPEDIDA`) solo se evalúa DENTRO de una conversación ya abierta (`HealthBrain.interpret()`) — en ese punto, era inalcanzable.

Por eso `_enrutar_solicitud_nueva` (gateway.py, el camino de "sin conversación abierta") ahora también revisa `_es_despedida` como último recurso, reutilizando la MISMA lista/función de brain.py (import directo, nunca copiada) — si coincide, se resuelve con `RequestIntent.SALIR`, el mismo mecanismo de arriba. Esto significa que tanto la opción numerada como el lenguaje natural de despedida cierran la conversación desde el mismo lugar sin conversación abierta, y ambos caminos comparten el mismo texto final.

## 5. Verificación

Suite completa: **489 passed, 9 skipped** (el nuevo test real gateado contra hrmm-backend, ver abajo). Cero regresiones.

1. ✅ **Reproducción EXACTA del bucle de 6+ turnos** (`test_reproduce_bucle_real_de_despedida_sin_conversacion_abierta`) — las 4 frases reales de tu mensaje ("No gracias q tengas buenas noches", "No ya terminé", "Chao", "No sé que hacer chao") cierran correctamente, ninguna cae en `_MENSAJE_INTENCION_NO_RECONOCIDA`.
2. ✅ **Opción "5"/"salir"/"terminar"** (`test_opcion_de_menu_salir_cierra_la_conversacion`, 4 variantes incluida "Salir, gracias") cierra la conversación correctamente.
3. ✅ **`_MENSAJE_INTENCION_NO_RECONOCIDA` incluye la opción de salir** (`test_mensaje_no_reconocido_incluye_la_opcion_de_salir`).
4. ✅ Los 3 tests viejos de `test_flujo_en_etapas_y_correo.py` (recado 035) actualizados para reflejar el hallazgo honesto de la sección 2 — dejaron de asumir un envío nativo que nunca ocurría.
5. ✅ Nuevo test real gateado (`ZANTIA_RUN_REAL_HRMM_TESTS=1`, `test_enviar_confirmacion_email_contra_hrmm_backend_real`) que crea una cita de prueba claramente marcada (`ZANTIA-TEST-CORREO-<epoch>`), llama `enviar_confirmacion_email` real, y cancela la cita al final con un código real de limpieza. **No lo ejecuté yo mismo en esta sesión** — sigue el mismo patrón ya establecido en este repo (`test_identidad_canal_real_e2e`, recado 015): es manual/interactiva a propósito, porque tanto la confirmación de recepción como el código de cancelación llegan por correo real y ningún agente puede leerlos por sí mismo. Si quieres que lo corra contigo (con `pytest -s`, revisando un correo real en vivo), decime cuál usar.

## 6. Archivos tocados

- `domains/health/models.py` — `Appointment.correo_confirmacion_enviado`, `sufijo_confirmacion_correo`, `respuesta_pregunta_sobre_correo`, `RequestIntent.SALIR`.
- `domains/health/hrmm_appointment_service.py` — `enviar_confirmacion_email`, `_intentar_enviar_confirmacion`, `correo` en los 3 métodos de escritura.
- `domains/health/tools.py` — `BookAppointmentTool` ya no pierde `correo_confirmacion_enviado` en la relectura de `confirm_appointment`.
- `domains/health/agent.py` — mensaje final dinámico (lee `resultados_tools`, no una relectura fresca).
- `domains/health/brain.py` — `_texto_despedida` extraída; `_DESPEDIDA` ampliada (chao/chau/adios, "que tengas buen"); `_detectar_interrupcion_de_contexto` recibe `resultado_de_herramientas` y responde con el estado REAL del correo.
- `domains/health/gateway.py` — `_MENU_NUMERADO`/`_MENU_OPCIONES`/`_resolver_por_intent` con la 5ta opción; `_enrutar_solicitud_nueva` revisa despedida como último recurso; `_evaluar_ventana_de_gracia` pasa `resultado_de_herramientas`; `_procesar_intento_de_codigo` usa el sufijo dinámico.
- `.ai/RISKS.md` — nota en R-21 (sigue ABIERTO: el mecanismo de envío ya existe, la causa raíz — sin fuente de correo — no).
- Tests: `test_pregunta_correo_y_despedida.py` (+9 tests), `test_flujo_en_etapas_y_correo.py` (3 assertions corregidas + docstring), `test_hrmm_appointment_service.py` (+1 test real gateado).

## 7. Commit y despliegue

Commiteado y pusheado en este mismo trabajo — hash final, evidencia de `git log` y `git ls-remote origin main`, abajo de este mensaje en el chat (no en este recado, para no quedar desactualizado si se hace un commit adicional).

**Sí, hace falta redesplegar EasyPanel** — hay commits nuevos en `origin/main` que el despliegue actual no tiene.
