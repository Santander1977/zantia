# D-7: TelegramChannel usa webhook, no polling (getUpdates)

**Decisión**: `TelegramChannel` (`channels/telegram_channel.py`) recibe mensajes vía webhook (Telegram llama a `POST /webhook/telegram` en `service/app.py`, registrado una sola vez contra la Bot API con `setWebhook`) — nunca hace polling (`getUpdates` en bucle).

**Motivo**: ZANTIA ya se despliega como un servicio HTTP simple (FastAPI + uvicorn, decisión D-5) en EasyPanel, exactamente igual que el resto de este ecosistema (hrmm-backend, panel-admin) — procesos que responden a peticiones entrantes, no que mantienen un bucle propio corriendo en segundo plano. `ChatwootChannel` (D-5) ya usa este mismo modelo.

**Alternativas consideradas**:
1. **Polling** (`getUpdates` con long-polling) — requeriría un bucle propio corriendo de forma indefinida DENTRO del mismo proceso (una tarea de fondo de `asyncio`, o un segundo proceso/worker), con manejo de `offset` para no reprocesar updates, reconexión ante caídas de red, y coordinación con el ciclo de vida de uvicorn (arrancar/parar el bucle junto con el servidor). Ninguna infraestructura de este tipo existe hoy en ZANTIA (ver R-10: ni siquiera el scheduler de recordatorios, mucho más simple, está construido).
2. **Webhook** (elegida) — Telegram nos llama a nosotros, exactamente como ya hace Chatwoot. Cero infraestructura nueva: mismo servidor HTTP, mismo patrón de "handler recibe payload -> traduce -> responde".

**Ventajas de la opción elegida (2, webhook)**:
- Reutiliza EXACTAMENTE el mismo patrón de transporte ya construido, probado y desplegado para Chatwoot (D-5) — un endpoint más en el mismo `service/app.py`, no un componente nuevo de infraestructura.
- No requiere ningún proceso/tarea de fondo adicional — coherente con el resto del proyecto, que explícitamente NO tiene todavía ningún mecanismo de "algo corriendo solo" (R-10).
- Más barato en recursos: sin una conexión HTTP long-polling permanentemente abierta hacia Telegram.

**Desventajas**:
- Requiere una URL pública HTTPS válida (Telegram no acepta webhooks a `http://` ni a IPs privadas/`localhost`) — ya se cumple porque ZANTIA se despliega en EasyPanel con URL pública, mismo requisito que ya satisface `CHATWOOT_URL`.
- El registro del webhook (`setWebhook`) es un paso manual, fuera de este código — mismo criterio ya aceptado para Chatwoot (su webhook también se configura desde su propio panel, ZANTIA nunca se autorregistra).

**Riesgo**: Bajo — mismo patrón, mismo transporte, misma capa (`service/app.py`) ya en producción de facto (probado con Docker real, R-16) para Chatwoot. Riesgo nuevo, no relacionado con esta elección: `POST /webhook/telegram` no autentica el origen de la petición (mismo hueco ya documentado para Chatwoot en R-18) — ver `.ai/RISKS.md` R-23.

**Impacto**: Nuevo archivo `channels/telegram_channel.py`. `service/app.py` (+import, +composición `_canal_telegram`, +endpoint `POST /webhook/telegram`). `domains/health/gateway.py` (+`"telegram"` en `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO`, una sola línea — el resto del gate de identidad de canal, ya construido en 012/014/016, se activa sin ningún cambio adicional). `.env.example` (+`TELEGRAM_BOT_TOKEN`). Sin cambios en `HealthBrain`, `AppointmentService`, `ChatwootChannel`, ni en `core/`.

**Estado**: IMPLEMENTADA (2026-09-05, recado `022`).
