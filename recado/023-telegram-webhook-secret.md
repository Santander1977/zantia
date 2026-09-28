# RECADO PARA CHATGPT

Fecha: 2026-09-05
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Cierre de R-23 — verificación del `secret_token` de Telegram en `POST /webhook/telegram`, antes de registrar el webhook real
Objetivo: Documentar la implementación y el resultado de los tests.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = no resuelto, nunca inventado.

---

## Resumen ejecutivo

HECHO: R-23 (`.ai/RISKS.md`) pasó de ABIERTO a **RESUELTO**. `TelegramChannel.verificar_secreto_webhook()` (`channels/telegram_channel.py`) valida el header `X-Telegram-Bot-Api-Secret-Token` contra una variable de entorno nueva, `TELEGRAM_WEBHOOK_SECRET`, usando `hmac.compare_digest` (comparación en tiempo constante — mismo criterio ya verificado en recado 015 para `hrmm-backend/app/trusted_auth.py`). `service/app.py:webhook_telegram` la llama ANTES de leer el body como JSON — sin coincidir, responde `401` sin procesar absolutamente nada.

HECHO: **167 tests pasando + 2 deshabilitados a propósito** (169 recolectados) — 7 tests nuevos de esta fase, 0 de los 160 anteriores rotos.

## Diseño

**`TelegramChannel.verificar_secreto_webhook(secreto_recibido)`**: nuevo método, nuevo campo `webhook_secret_env_var: str = "TELEGRAM_WEBHOOK_SECRET"`. Si la variable de entorno no está configurada, LANZA (`TelegramChannelError`) en vez de devolver `True`/`False` en silencio — sin ella no hay nada contra qué comparar, y aceptar cualquier petición sin secreto configurado sería degradar la protección en silencio.

**Fail-fast al arrancar** (decisión, no pedida explícitamente pero consistente con el resto del proyecto): se agregó `_construir_canal_telegram()` en `service/app.py`, que exige `TELEGRAM_WEBHOOK_SECRET` al importar el módulo — mismo criterio que `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID` para Chatwoot. Sin esta variable, el proceso ni siquiera arranca, en vez de arrancar y fallar en cada request. `TELEGRAM_BOT_TOKEN` (el otro secreto de Telegram) SIGUE validándose de forma perezosa en `send()` — solo se necesita para responder, no para poder recibir con seguridad; son necesidades distintas, se resolvieron distinto a propósito.

**Orden en el endpoint**: `webhook_telegram` verifica el header PRIMERO — ni siquiera llama a `request.json()` todavía si el secreto no coincide. Requisito #2 del pedido ("rechaza la petición con 401 antes de procesar nada") cumplido literalmente, no solo en espíritu.

**Actualización del comando de `setWebhook`** (`.env.example`): ahora incluye el parámetro `secret_token=<TELEGRAM_WEBHOOK_SECRET>` — el usuario genera este valor él mismo (ej. `openssl rand -hex 32`, Telegram no lo provee) y debe pasar el MISMO valor tanto en `TELEGRAM_WEBHOOK_SECRET` como en el parámetro `secret_token` al registrar el webhook.

## Resultado de los tests pedidos (y algunos adicionales, mismo rigor)

**Unitarios (`tests/channels/test_telegram_channel.py`, 4 tests nuevos)**:
1. `test_verificar_secreto_webhook_coincide` — PASA.
2. `test_verificar_secreto_webhook_no_coincide` — PASA.
3. `test_verificar_secreto_webhook_header_ausente_no_coincide` — PASA (header `None`, no lanza error de tipo).
4. `test_verificar_secreto_webhook_sin_variable_configurada_falla_explicito` — PASA.

**Integración (`tests/service/test_app.py`, 3 tests nuevos, los explícitamente pedidos)**:
1. `test_webhook_telegram_sin_secret_token_correcto_rechaza_con_401` — PASA: sin header Y con header incorrecto, ambos devuelven `401` con `procesado: false`, sin tocar el dominio.
2. `test_webhook_telegram_con_secret_token_correcto_se_procesa_normal` — PASA: mismo payload, con el header correcto, `200` y `procesado: true`.
3. `test_arranque_falla_sin_telegram_webhook_secret` — PASA (adicional, no pedido explícitamente pero de bajo costo y consistente con el resto del proyecto): sin `TELEGRAM_WEBHOOK_SECRET`, el módulo no se puede importar/recargar.

Los 3 tests de `/webhook/telegram` ya existentes de recado 022 se actualizaron para incluir el header correcto (ahora obligatorio) — sin tocar su lógica de aserción.

**Suite completa**: 167 passed, 2 skipped (deshabilitados de red real, sin relación con este cambio).

## Documentación actualizada

`.ai/RISKS.md` (R-23 → RESUELTO), `.ai/ARCHITECTURE.md` (🟡→🟢 para `/webhook/telegram`), `.ai/API_CONTRACTS.md` (auth real, nota de seguridad reescrita), `.ai/SECURITY.md` (+secreto, +nota de auditoría), `.ai/INTEGRATIONS.md`, `.ai/TESTING.md`, `.env.example` (+`TELEGRAM_WEBHOOK_SECRET`, comando `setWebhook` actualizado con `secret_token`).

## Pendiente (no resuelto aquí, ni inventado)

- Generar el valor real de `TELEGRAM_WEBHOOK_SECRET` y registrar el webhook con `setWebhook` (incluyendo `secret_token`) — acción del usuario, no ejecutada en esta sesión.
- Nunca probado contra la red real de Telegram — toda la cobertura sigue siendo con fixtures/mocks.

RECADO GENERADO: /Users/enzoalfonso/recado/023-telegram-webhook-secret.md
