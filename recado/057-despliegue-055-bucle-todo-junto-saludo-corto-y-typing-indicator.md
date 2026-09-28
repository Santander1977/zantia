# 057 — Despliegue de 055, bug "todo junto" reaparecido, saludo corto tras cierre, indicador de escritura en Telegram

**Fecha**: 2026-09-07
**Estado**: Implementado con autonomía completa (pedido explícito del usuario). 468 passed, 8 skipped. Cero regresiones.

---

## Punto 1 — El recado 055 nunca se había desplegado, porque nunca se había commiteado

**Causa raíz confirmada**: aprobaste el recado 055 y pediste explícitamente "comitea y pushea", pero ese mensaje llegó en medio de mi investigación del hallazgo del recado 056 (la hora alucinada) y el commit nunca se ejecutó — quedó pendiente sin que yo lo señalara. `git log`/`git ls-remote` confirmaron que `origin/main` seguía en el commit del recado 053 (`2e3e9a8`), sin nada de 055. Por eso Telegram seguía mostrando el formato viejo — el contenedor de EasyPanel SÍ tenía el código más reciente disponible, porque ese código nunca había llegado al repositorio en primer lugar.

**Corregido**: recados 055 y 056 (ver detalle completo en sus propios archivos) ya están commiteados y pusheados — hash final abajo. **Falta que redespliegues EasyPanel con este commit** (acción tuya, regla fija #1).

Revisé el resto del código buscando otros lugares con el mismo texto corrido sin lista que no se hubieran tocado en el recado 055, y corregí 6 más encontrados: `_VARIANTES_SERVICIO_AMBIGUO`/`_VARIANTES_SERVICIO_NO_IDENTIFICADO`/`_VARIANTES_FECHA_AMBIGUA`/`_VARIANTES_HORARIO_AMBIGUO` (mensajes de aclaración/ambigüedad en `brain.py`), `_iniciar_reprogramacion` (brain.py) y su equivalente en `gateway.py` (`_iniciar_verificacion_para_gestion`), y dos duplicados más del catálogo de servicios en `gateway.py` (`_determinar_servicio_inicial`, alcanzado cuando `_resolver_programar_cita` nunca pasa por `HealthBrain` — mismo patrón del recado 049). Además encontré y corregí, en `gateway.py:_elegir_opcion_ordinal`, la MISMA vulnerabilidad de substring del recado 053 (nunca corregida en esta copia local) y el mismo problema de orden no-cronológico del recado 056 en las opciones de reprogramación.

## Punto 2 — El bug "todo junto" reaparecido: causa raíz real, distinta a como se veía

Reproduje exactamente "hola" → "consultar" → "listamelas". La causa NO era una regresión del recado 048 — era un hueco que el 048 nunca cerró: `classify_intent_or_none` solo trataba como "sin intención" un SALUDO puro. Cualquier otro texto sin ninguna palabra clave reconocida — incluida una palabra completamente sin sentido como "listamelas" — seguía cayendo al default histórico del recado 030 (`PROGRAMAR_CITA`), arrancando el flujo de reserva completo en silencio (por eso se veía "pegado": no era un re-saludo, era una reserva nueva arrancando sola).

**Corregido**: el fallback a `PROGRAMAR_CITA` ahora exige una señal mínima de intención — afirmación ("sí", "claro", "dale"...) o un verbo/fórmula típica de pedido ("necesito", "quiero", "ayuda", "por favor"...). Sin ninguna de esas señales, se trata como "sin intención" (`None`), igual que un saludo puro — mostrando el menú en vez de arrancar la reserva. Probé cuidadosamente que esto NO rompiera los 2 casos reales que motivaron el default original (recado 030, "Sí, claro, ayúdame..." y recado 049/050, "necesito otra cita de urgencias") — ambos siguen funcionando exactamente igual.

## Punto 3 — Saludo corto al volver poco después de un cierre

**Mecanismo elegido** (decisión autónoma, pedida explícitamente): nuevo campo `HealthGateway._cierre_reciente` (`patient_reference -> (momento real del cierre, nombre conocido)`), poblado en `_cerrar_si_definitivo` — deliberadamente SEPARADO de la ventana de gracia del recado 050 (`_recien_cerrada`), porque resuelve un problema distinto: no "¿este mensaje es sobre lo que se acaba de cerrar?" sino "¿ya lo saludé hace un momento?". Con timestamp real (nunca simulado) y umbral de **30 minutos** (decisión autónoma: corto para dar la sensación de "misma sesión", largo para cubrir una distracción breve del paciente).

Dentro del umbral: `"¡{hora real}, {señor/señora} {nombre}! ¿Puedo ayudarlo en algo más?"` — sin presentación institucional ni menú. Pasado el umbral: saludo completo de siempre. Diseño no bloqueante preservado: si el mismo mensaje de regreso ya trae una intención clara, se procesa de inmediato con el saludo corto antepuesto.

## Punto 4 — Indicador de "escribiendo..." en Telegram

`TelegramChannel.send_typing_action()` (nuevo) llama a `sendChatAction` de la Bot API real. En `service/app.py`, el procesamiento del mensaje (`handle_inbound_message`, que puede incluir una llamada real a Anthropic) ahora corre en un hilo aparte (`asyncio.to_thread`) mientras una tarea de fondo (`asyncio.create_task`) repite `sendChatAction` cada 4 segundos — **decisión autónoma sobre la repetición**: Telegram apaga el indicador nativo solo a los ~5 segundos, así que sin este refresco periódico desaparecería a mitad de una respuesta lenta, dando la falsa impresión de que el bot dejó de responder. Se cancela la tarea de fondo apenas termina el procesamiento real. Best-effort: un fallo puntual del indicador (cosmético) nunca interrumpe el procesamiento real del mensaje.

## Verificación — resultado, sin detalle paso a paso

1. ✅ Hash real confirmado (`git ls-remote` == `git rev-parse HEAD`, ver abajo) — 055 y 056 ahora sí están en el remoto.
2. ✅ Reproducción exacta del bug "todo junto" + corrección verificada (`tests/domains/health/test_fallback_sin_intencion_no_arranca_reserva.py`, 11 tests).
3. ✅ Saludo corto vs. completo según tiempo transcurrido, con y sin nombre conocido, y compatibilidad con intención clara en el mismo mensaje (`tests/domains/health/test_saludo_corto_tras_cierre_reciente.py`, 4 tests).
4. ✅ Indicador de escritura confirmado disparándose (mock de red, nunca contra Telegram real) y repitiéndose durante un procesamiento simulado lento (`tests/service/test_app.py`, 1 test nuevo + 2 actualizados).
5. ✅ Suite completa: **468 passed, 8 skipped** — cero regresiones.

## Archivos tocados

- `domains/health/brain.py`, `domains/health/gateway.py`: listas numeradas adicionales (Punto 1), saludo corto (Punto 3), `_elegir_opcion_ordinal` (Punto 1, fix de substring + orden).
- `domains/health/intent.py`: `_tiene_senal_de_intencion` (nueva), fallback de `classify_intent_or_none` (Punto 2).
- `channels/telegram_channel.py`: `send_typing_action` (nuevo).
- `service/app.py`: `_mantener_indicador_de_escritura`/`_procesar_con_indicador_de_escritura` (nuevos), webhook usa el nuevo flujo.
- Nuevos: `tests/domains/health/test_fallback_sin_intencion_no_arranca_reserva.py`, `tests/domains/health/test_saludo_corto_tras_cierre_reciente.py`; actualizados: `tests/service/test_app.py`.

## Lo que genuinamente requiere tu acción (nunca mi decisión de diseño)

1. **Redesplegar EasyPanel** con el commit final de abajo — regla fija, nunca lo hago yo.
2. **Código de verificación** de la cita real mal reservada del recado 056 (`CITA-9782ae7085`, documento 72302972) — ya enviado a su correo, sigue pendiente.
3. `HEALTH_BRAIN_TYPE` no se tocó en ningún archivo de configuración real — sigue siendo tu decisión, tal como confirma la regla fija #4.

## Hash del commit final

Ver mensaje de cierre de la sesión — commiteado y pusheado, confirmado con `git ls-remote` contra el hash local.
