# CONTRATOS API — ZANTIA

> Endpoints/contratos que ESTE proyecto expone hacia afuera (lo que otros consumen de él). Para lo que este proyecto consume de sistemas externos, ver `.ai/INTEGRATIONS.md`.

Cada endpoint documentado aquí en el mismo cambio que lo crea o modifica (regla R-API-2, ver `.claude/rules/contratos-api.md`). Ningún endpoint consumido por más de un componente cambia de contrato sin versión nueva o período de compatibilidad documentado (R-API-1).

| Endpoint | Método | Auth | Consumidores conocidos | Versión |
|---|---|---|---|---|
| `/health` | GET | Ninguna (mismo patrón que hrmm-backend) | Chequeo de salud de la plataforma de despliegue (EasyPanel) | Sin versionar — endpoint de infraestructura, no de negocio |
| `/webhook/chatwoot` | POST | Ninguna del lado de ZANTIA (Chatwoot no firma sus webhooks salientes por defecto) — riesgo abierto, ver nota abajo. Responde `503` si Chatwoot no está configurado (`CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID`, opcional desde D-8) | Instancia de Chatwoot de este ecosistema (inbox de prueba) — no configurada actualmente, ver `.ai/RISKS.md` R-4 | Sin versionar — un solo consumidor conocido hoy |
| `/webhook/telegram` | POST | `secret_token` de Telegram (`X-Telegram-Bot-Api-Secret-Token`, verificado contra `TELEGRAM_WEBHOOK_SECRET` — recado 023, ver nota abajo) | Bot API de Telegram (bot propio, decisión D-7) | Sin versionar — un solo consumidor conocido hoy |

## Notas de versionado

Sin esquema de versión todavía — ningún endpoint de negocio expuesto (solo transporte/webhook). A definir cuando exista un segundo consumidor real de algún endpoint.

## Nota de seguridad — `/webhook/chatwoot` sin autenticación (2026-09-01, recado 011)

Decisión consciente, documentada aquí como exige `.claude/rules/contratos-api.md` (nunca un olvido silencioso): Chatwoot no firma sus webhooks salientes con un secreto compartido por defecto en su configuración estándar. `/webhook/chatwoot` valida la FORMA del payload (`event == "message_created"`, `message_type == "incoming"`) pero no autentica el origen de la petición. Mitigación mínima aplicada: el endpoint solo puede afectar conversaciones ya conocidas por Chatwoot (usa el `conversation.id`/`source_id` que trae el propio payload, no puede leer ni escribir nada fuera de `MockAppointmentService` mientras `HRMM_BACKEND_ENV=mock`). PENDIENTE antes de producción real: restringir por IP de origen de Chatwoot, o activar un secreto de webhook si la versión de Chatwoot del ecosistema lo soporta — no inventado aquí porque no se verificó si esa instancia de Chatwoot lo permite. **Actualización 2026-09-05 (recado 024, D-8)**: Chatwoot es ahora OPCIONAL — el usuario decidió usar solo Telegram por ahora, así que este riesgo queda en la práctica inactivo (el endpoint responde `503` sin exponer nada) hasta que se decida activar Chatwoot.

## Nota de seguridad — `/webhook/chatwoot` es OPCIONAL desde recado 024 (decisión D-8)

Sin `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID` configuradas, `service/app.py` arranca igual con el canal de Chatwoot deshabilitado — `/webhook/chatwoot` responde `503 {"procesado": false, "motivo": "..."}` si alguien lo invoca de todas formas, nunca un `500` ni un silencio. Decisión del usuario: por ahora solo usar Telegram, sin conectar WhatsApp/Instagram vía Chatwoot.

## Nota de seguridad — `/webhook/telegram` SÍ autentica el origen (2026-09-05, recado 023, cierra R-23)

A diferencia de `/webhook/chatwoot` (R-18, sin mitigación disponible en Chatwoot), la Bot API de Telegram ofrece un `secret_token` real: se pasa como parámetro al llamar `setWebhook`, y Telegram lo reenvía en cada petición como header `X-Telegram-Bot-Api-Secret-Token`. `service/app.py:webhook_telegram` valida ese header contra `TELEGRAM_WEBHOOK_SECRET` (`TelegramChannel.verificar_secreto_webhook`, `hmac.compare_digest`) ANTES de leer el body como JSON — sin coincidir, responde `401` sin procesar nada. `TELEGRAM_WEBHOOK_SECRET` sigue siendo obligatoria para que el proceso arranque (fail-fast) incluso después de que Chatwoot pasó a ser opcional (D-8, recado 024) — Telegram nunca debe quedar expuesto sin poder validar su origen.
