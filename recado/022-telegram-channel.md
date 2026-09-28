# RECADO PARA CHATGPT

Fecha: 2026-09-05
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: `TelegramChannel` — segundo canal real (además de Chatwoot), hablando directo con la Bot API de Telegram, con el mismo gate de identidad persistente ya construido
Objetivo: Documentar la decisión webhook vs. polling, el diseño del canal, su integración con el mecanismo de correlación e identidad ya existentes, y el resultado de los tests.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = no resuelto, nunca inventado.

---

## Resumen ejecutivo

HECHO: se construyó `TelegramChannel` (`channels/telegram_channel.py`), implementando el mismo `Channel` Protocol que `ChatwootChannel` (sin tocarlo), contra la Bot API pública de Telegram — por **webhook**, no polling (decisión D-7, justificada abajo). Wireado en `service/app.py` como un endpoint nuevo (`POST /webhook/telegram`), compartiendo el MISMO `HealthGateway`/`identity_store` que ya usa Chatwoot — un usuario de Telegram nuevo pasa por el wizard completo de identificación (documento → código → `identidad_canal`, con vencimiento a 180 días y olvido a pedido, recados 012/014/016) con un solo cambio de una línea (`_CANALES_SIN_IDENTIFICADOR_DOCUMENTO = {"chatwoot", "telegram"}`).

HECHO: **160 tests pasando + 2 deshabilitados a propósito** (162 recolectados) — 13 tests nuevos de esta fase, 0 de los 147 anteriores rotos.

## Decisión: webhook, no polling (D-7)

`docs/decisions/d-7-telegram-webhook-vs-polling.md` (formato completo: decisión/motivo/alternativas/ventajas/desventajas/riesgo/impacto/estado). Resumen: ZANTIA ya se despliega como un servicio HTTP simple (FastAPI+uvicorn, D-5) en EasyPanel, igual que el resto del ecosistema — no hay (ni se construyó acá) ninguna infraestructura de proceso de fondo (ver R-10: ni el scheduler de recordatorios, mucho más simple, existe todavía). Polling (`getUpdates` en bucle) exigiría construir esa infraestructura desde cero. Webhook reutiliza EXACTAMENTE el mismo patrón ya construido y probado para Chatwoot — un endpoint más en `service/app.py`, cero componentes nuevos de infraestructura.

## Diseño del canal

**Sin tabla de correlación interna** (diferencia deliberada frente a `ChatwootChannel`): Chatwoot necesita recordar la relación entre el identificador de canal (teléfono) y su propio ID interno de conversación (dos números distintos) para poder responder. Telegram no tiene ese problema — el `chat.id` que llega en cada Update ES, literalmente, el mismo valor que `sendMessage` necesita para responder. `conversation_id` es simplemente `str(chat_id)`; `send()` hace `int(message.conversation_id)` de vuelta. Cero tabla nueva que sincronizar.

**Autenticación de la API, distinta de Chatwoot**: la Bot API de Telegram exige el token EN LA RUTA (`https://api.telegram.org/bot<TOKEN>/sendMessage`), no en un header — así lo define la API pública de Telegram (no es una elección de este proyecto). `send()` valida `TELEGRAM_BOT_TOKEN` de forma PEREZOSA (en el momento de enviar, no al construir el canal) — mismo patrón exacto, ya probado, que `ChatwootChannel.api_token_env_var`/`CHATWOOT_API_TOKEN`.

**`handle_webhook_payload`**: ignora silenciosamente (sin error) cualquier Update que no traiga `message` (edited_message, callback_query, channel_post, etc.) o que no traiga texto (foto, sticker, audio) — mismo criterio que `ChatwootChannel` ignorando el eco de sus propios mensajes salientes. Si HAY texto pero falta `chat.id` (nunca debería pasar según el contrato público de Telegram), se rechaza explícitamente en vez de inventar una correlación — mismo criterio que Chatwoot rechazando un webhook sin remitente.

**Integración con identidad (requisito #3 del pedido)**: el ÚNICO cambio necesario en `domains/health/gateway.py` fue agregar `"telegram"` a `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO` (antes `{"chatwoot"}`, ahora `{"chatwoot", "telegram"}`). Todo el resto del mecanismo — pedir documento, validar contra `buscar-paciente`, código de verificación por correo, persistencia en `identidad_canal`, vencimiento a 180 días, "olvida mi información" — se activa sin ningún código nuevo, porque el gate ya era genérico por diseño desde 012. Verificado con un test dedicado (`test_identity_gate_telegram.py`, 2 tests: wizard completo para un `chat_id` nuevo, reconocimiento inmediato para uno ya verificado).

**Token nunca pedido en el chat**: `TELEGRAM_BOT_TOKEN` se lee de variable de entorno (ver `.env.example`), tal como pidió el usuario explícitamente — en ningún momento de esta sesión se solicitó ni se recibió un valor real de token.

## Hallazgo/decisión de seguridad, documentada no implementada

A diferencia de `/webhook/chatwoot` (R-18, sin mitigación conocida), la Bot API de Telegram SÍ ofrece un mecanismo real para autenticar el origen del webhook: un `secret_token` configurable en `setWebhook`, que Telegram reenvía en cada petición como header `X-Telegram-Bot-Api-Secret-Token`. No implementado en esta fase (no fue pedido) — documentado como **R-23** en `.ai/RISKS.md`, distinto de R-18 precisamente porque acá SÍ hay un mecanismo confirmado y disponible, no una incógnita.

## Tests

- `tests/channels/test_telegram_channel.py` (8 tests): Update con texto se traduce, Update sin `message` se ignora, Update sin texto se ignora, Update sin `chat.id` falla explícito, `send` llama `sendMessage` con el `chat_id` correcto, `send` funciona SIN haber recibido antes (a diferencia de Chatwoot), sin token falla explícito, `ok: false` de Telegram falla explícito.
- `tests/service/test_app.py` (+3 tests): flujo completo `/webhook/telegram` con `MockAppointmentService`, Update sin mensaje de texto ignorado, fallo al responder no produce 500 — mismo patrón que los 3 tests equivalentes de Chatwoot.
- `tests/domains/health/test_identity_gate_telegram.py` (2 tests, nuevo): confirma el requisito #3 (wizard completo para un chat_id nuevo, reconocimiento inmediato para uno ya verificado) — deliberadamente NO repite la cobertura completa del wizard (ya vive en `test_identity_gate_chatwoot.py`), solo prueba que el mismo mecanismo se activa igual.
- Suite completa: **160 passed, 2 skipped** (los 2 deshabilitados de red real, sin relación con este cambio).

## Documentación actualizada

`docs/decisions/d-7-telegram-webhook-vs-polling.md` (nuevo), `.ai/DECISIONS.md`, `.ai/ARCHITECTURE.md` (componentes + rutas críticas), `.ai/API_CONTRACTS.md` (+endpoint, +nota de seguridad), `.ai/INTEGRATIONS.md` (+sistema externo), `.ai/SECURITY.md` (+secreto, +nota de auditoría), `.ai/RISKS.md` (R-23 nuevo, R-4/R-15 actualizados), `.ai/DATA_MODEL.md` (aclaración sobre la columna `telefono`), `.ai/TESTING.md`, `.env.example` (+`TELEGRAM_BOT_TOKEN`).

## Pendiente (no resuelto aquí, ni inventado)

- Crear el bot real con @BotFather, configurar `TELEGRAM_BOT_TOKEN`, y registrar el webhook (`setWebhook` contra la URL pública de ZANTIA) — nunca se hizo en esta sesión (sin token/bot disponibles).
- R-23: validar `X-Telegram-Bot-Api-Secret-Token` — no implementado, no pedido.
- Nunca probado contra la red real de Telegram — toda la cobertura es con fixtures/mocks, mismo criterio que `ChatwootChannel` en su momento (recado 011).

RECADO GENERADO: /Users/enzoalfonso/recado/022-telegram-channel.md
