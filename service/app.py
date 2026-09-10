"""
service/app.py — capa de transporte HTTP del proceso ZANTIA (decisión
D-5, `docs/decisions/d-5-empaquetado-fastapi-chatwoot.md`). Sin lógica
de dominio: solo traduce HTTP <-> `domains/health/gateway.py` (ya
construido, sin tocar) a través de `ChatwootChannel`
(`channels/chatwoot_channel.py`, sin tocar) y, desde recado 022,
`TelegramChannel` (`channels/telegram_channel.py`) — por webhook, ver
`docs/decisions/d-7-telegram-webhook-vs-polling.md`. Ambos canales
comparten el MISMO `_gateway` (una sola instancia, un solo
`identity_store`) — un paciente que escribe primero por WhatsApp y
luego por Telegram con el mismo documento sigue siendo dos identidades
de CANAL distintas (números/chat_id distintos), cada una con su propio
wizard — eso es correcto y esperado, no un error: `identidad_canal` es
por identificador de canal, no por persona.

Chatwoot es OPCIONAL al arrancar desde recado 024 (decisión D-8,
`docs/decisions/d-8-chatwoot-opcional.md`) — a diferencia de Telegram
(`TELEGRAM_WEBHOOK_SECRET` sigue siendo fail-fast, recado 023: ese
webhook SIN verificación de origen sería un hueco de seguridad activo).
Sin `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID`, `_canal` queda en `None` y el
proceso arranca igual — `POST /webhook/chatwoot` responde `503`
explícito si alguien lo invoca sin que Chatwoot esté configurado, nunca
falla en silencio ni bloquea el resto del servicio (Telegram incluido).

Composición en tiempo de arranque (una sola vez, nunca en medio de una
conversación): `domains.health.config.build_appointment_service()`
decide Mock vs. Hrmm real según `HRMM_BACKEND_ENV` (recado 011) — este
archivo NO lee esa variable directamente, solo usa el resultado.

Brecha teléfono->documento (recado 012, `.ai/RISKS.md` R-15): cuando
`HRMM_BACKEND_ENV=production` Y el canal es `ChatwootChannel`
(identificador = número de WhatsApp), `handle_inbound_message` recibe
ese número como `patient_reference` — pero `HrmmAppointmentService`
espera que `patient_reference` SEA el documento de identidad real
(convención D-4). RESUELTA A NIVEL DE DISEÑO desde recado 012
(`HealthGateway._identidad_resuelta` + el gate de
`domains/health/gateway.py:_gestionar_identificacion`) y extendida en
recado 014 con verificación por código + persistencia entre
conversaciones (`identity_store=build_identity_store()` abajo, lee
`ZANTIA_IDENTIDAD_DB_PATH`, ver `.env.example`). Sigue sin probarse
contra la red real de hrmm-backend ni con `HRMM_BACKEND_ENV=production`
de verdad — por eso el canal de prueba de este despliegue corre con
`HRMM_BACKEND_ENV=mock` (default seguro) hasta confirmar eso con
evidencia real.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from channels.chatwoot_channel import ChatwootChannel, ChatwootChannelError
from channels.contract import OutboundMessage
from channels.telegram_channel import TelegramChannel, TelegramChannelError
from domains.health.activity_source import MockActivitySource
from domains.health.config import HealthConfigError, build_appointment_service
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.identity_store import build_identity_store
from domains.health.reminder_manager import ReminderManager
from domains.health.result_sink import MockActivityResultSink

logger = logging.getLogger("zantia.service")

app = FastAPI(title="ZANTIA")


def _construir_canal_chatwoot() -> Optional[ChatwootChannel]:
    """`None` si `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID` no están
    configuradas (recado 024, decisión D-8) — Chatwoot es OPCIONAL: un
    despliegue que solo use Telegram no debe verse obligado a configurar
    un canal que no piensa usar. Se registra un `warning` explícito (
    nunca silencio) y `POST /webhook/chatwoot` responde `503` si alguien
    lo invoca de todas formas — ver ese endpoint."""
    import os

    base_url = os.environ.get("CHATWOOT_URL")
    account_id = os.environ.get("CHATWOOT_ACCOUNT_ID")
    if not base_url or not account_id:
        logger.warning(
            "CHATWOOT_URL/CHATWOOT_ACCOUNT_ID no configuradas — canal de Chatwoot "
            "deshabilitado (POST /webhook/chatwoot responderá 503 si se invoca). "
            "Ver .env.example y .ai/RISKS.md R-4."
        )
        return None
    return ChatwootChannel(base_url=base_url, account_id=account_id)


# Composición única, al importar el módulo (arranque del proceso) — si
# algo falta, el proceso NO arranca, nunca falla a medias en una
# conversación real (requisito explícito de domains/health/config.py).
_appointment_service = build_appointment_service()
_gateway = build_health_gateway(
    activity_source=MockActivitySource(),
    appointment_service=_appointment_service,
    reminder_manager=ReminderManager(),
    result_sink=MockActivityResultSink(),
    # Identidad de canal persistente entre conversaciones (recado 014) —
    # lee ZANTIA_IDENTIDAD_DB_PATH (ver .env.example); sin ella, cae al
    # default seguro ":memory:" (sin persistencia entre reinicios).
    identity_store=build_identity_store(),
)
_canal = _construir_canal_chatwoot()


def _construir_canal_telegram() -> TelegramChannel:
    """`TELEGRAM_BOT_TOKEN` sigue validándose de forma perezosa, en
    `send()` (mismo patrón que `CHATWOOT_API_TOKEN`) — pero
    `TELEGRAM_WEBHOOK_SECRET` (recado 023, cierra R-23) se exige AL
    ARRANCAR, fail-fast, igual que `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID`
    arriba: sin él, cualquier petición a `/webhook/telegram` fallaría
    igual en cada request (503, ver el endpoint) — mejor que el proceso
    ni siquiera arranque con una superficie insegura o inútil expuesta."""
    import os

    if not os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        raise HealthConfigError(
            "TELEGRAM_WEBHOOK_SECRET es obligatoria para arrancar el webhook de "
            "Telegram (ver .env.example) — no configurada."
        )
    return TelegramChannel()


_canal_telegram = _construir_canal_telegram()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/chatwoot")
async def webhook_chatwoot(request: Request):
    if _canal is None:
        # Chatwoot opcional (recado 024, D-8): nunca un 500 ni un
        # silencio — el llamador se entera explícitamente de que este
        # canal no está configurado en este despliegue.
        return JSONResponse(
            status_code=503,
            content={"procesado": False, "motivo": "Canal de Chatwoot no configurado (CHATWOOT_URL/CHATWOOT_ACCOUNT_ID)."},
        )
    payload = await request.json()
    try:
        mensaje = _canal.handle_webhook_payload(payload)
    except ChatwootChannelError as exc:
        logger.warning("Webhook de Chatwoot rechazado: %s", exc)
        return {"procesado": False, "motivo": str(exc)}

    if mensaje is None:
        # Eco de un mensaje saliente, o evento que no es message_created
        # entrante — se ignora silenciosamente, es el comportamiento
        # esperado (ver docstring de ChatwootChannel.handle_webhook_payload).
        return {"procesado": False}

    mensaje = _canal.receive()
    respuesta_texto = handle_inbound_message(
        _gateway,
        patient_reference=mensaje.conversation_id,
        channel=_canal.canal,
        message_id=mensaje.message_id,
        text=mensaje.text,
    )
    try:
        _canal.send(OutboundMessage(conversation_id=mensaje.conversation_id, text=respuesta_texto))
    except ChatwootChannelError as exc:
        # Encontrado con una prueba real end-to-end (recado 012): sin
        # este try/except, un fallo al RESPONDER (ej. Chatwoot caído)
        # tumbaba el request con un 500 sin registro claro, después de
        # que la lógica de dominio ya se ejecutó correctamente — el
        # mensaje del paciente ya fue procesado, solo la respuesta no
        # llegó. Se registra y se devuelve un error explícito, nunca un
        # 500 silencioso.
        logger.error("No se pudo enviar la respuesta a Chatwoot: %s", exc)
        return {"procesado": True, "respondido": False, "motivo": str(exc)}
    return {"procesado": True, "respondido": True}


_INTERVALO_INDICADOR_ESCRITURA_SEGUNDOS = 4.0


async def _mantener_indicador_de_escritura(conversation_id: str) -> None:
    """Recado 056, Punto 4 — repite `sendChatAction` cada
    `_INTERVALO_INDICADOR_ESCRITURA_SEGUNDOS` (menor a los ~5 segundos
    que Telegram mantiene el indicador nativo visible por sí solo) hasta
    que la tarea se cancele — decisión explícita para el caso "la
    respuesta tarda más de lo que dura la señal" (ej. una llamada real a
    Anthropic con latencia variable): sin este refresco periódico, el
    indicador desaparecería a mitad de un procesamiento largo, dando la
    falsa impresión de que el bot dejó de responder. Best-effort: un
    fallo puntual de red aquí (cosmético, nunca crítico) se registra y
    se sigue intentando en el siguiente ciclo, nunca interrumpe el
    procesamiento real del mensaje (que corre en paralelo, ver
    `_procesar_con_indicador_de_escritura`)."""
    while True:
        try:
            _canal_telegram.send_typing_action(conversation_id)
        except TelegramChannelError as exc:
            logger.warning("No se pudo enviar el indicador de escritura a Telegram: %s", exc)
        await asyncio.sleep(_INTERVALO_INDICADOR_ESCRITURA_SEGUNDOS)


async def _procesar_con_indicador_de_escritura(mensaje) -> str:
    """Muestra el indicador nativo "escribiendo..." de Telegram mientras
    se procesa el mensaje real — `handle_inbound_message` corre en un
    hilo aparte (`asyncio.to_thread`, nunca bloquea el event loop) para
    que la tarea de fondo que refresca el indicador (arriba) sí tenga
    oportunidad real de ejecutarse durante esa espera (incluida la
    latencia real de una llamada a un LLM, con `HEALTH_BRAIN_TYPE=llm`
    activo) — antes de este cambio, `handle_inbound_message` corría
    síncrono en el mismo hilo del event loop, así que cualquier tarea
    de fondo programada durante esa llamada nunca llegaba a correr."""
    tarea_indicador = asyncio.create_task(_mantener_indicador_de_escritura(mensaje.conversation_id))
    try:
        return await asyncio.to_thread(
            handle_inbound_message,
            _gateway,
            patient_reference=mensaje.conversation_id,
            channel=_canal_telegram.canal,
            message_id=mensaje.message_id,
            text=mensaje.text,
        )
    finally:
        tarea_indicador.cancel()


@app.post("/webhook/telegram")
async def webhook_telegram(request: Request):
    """Registrar esta URL como webhook de Telegram (`setWebhook`, ver
    `docs/decisions/d-7-telegram-webhook-vs-polling.md`) es un paso
    manual fuera de este código — mismo criterio que Chatwoot, cuyo
    webhook también se configura desde SU panel, nunca auto-registrado
    por ZANTIA. Al registrar el webhook hay que pasar el MISMO valor de
    `TELEGRAM_WEBHOOK_SECRET` como parámetro `secret_token` de
    `setWebhook` — si no coinciden, Telegram nunca deja de mandar el
    header, pero acá siempre lo va a rechazar.

    Verificación del secreto (recado 023, cierra R-23) ANTES que
    cualquier otra cosa — ni siquiera se lee el body como JSON todavía:
    una petición sin el secreto correcto no debe poder disparar NINGÚN
    procesamiento, ni de forma o de contenido."""
    secreto_recibido = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    try:
        secreto_valido = _canal_telegram.verificar_secreto_webhook(secreto_recibido)
    except TelegramChannelError as exc:
        logger.error("No se pudo validar el webhook de Telegram: %s", exc)
        return JSONResponse(status_code=503, content={"procesado": False, "motivo": str(exc)})
    if not secreto_valido:
        logger.warning("Webhook de Telegram rechazado: secret_token inválido o ausente")
        return JSONResponse(status_code=401, content={"procesado": False, "motivo": "secret_token inválido"})

    payload = await request.json()
    try:
        mensaje = _canal_telegram.handle_webhook_payload(payload)
    except TelegramChannelError as exc:
        logger.warning("Webhook de Telegram rechazado: %s", exc)
        return {"procesado": False, "motivo": str(exc)}

    if mensaje is None:
        # Update que no es un mensaje de texto entrante (edited_message,
        # callback_query, foto/sticker sin texto, etc.) — se ignora
        # silenciosamente, comportamiento esperado (ver docstring de
        # TelegramChannel.handle_webhook_payload).
        return {"procesado": False}

    mensaje = _canal_telegram.receive()
    respuesta_texto = await _procesar_con_indicador_de_escritura(mensaje)
    try:
        _canal_telegram.send(OutboundMessage(conversation_id=mensaje.conversation_id, text=respuesta_texto))
    except TelegramChannelError as exc:
        # Mismo criterio que webhook_chatwoot (recado 012): un fallo al
        # RESPONDER no debe tumbar el request con un 500 — el mensaje
        # del paciente ya fue procesado por el dominio, solo la
        # respuesta no llegó.
        logger.error("No se pudo enviar la respuesta a Telegram: %s", exc)
        return {"procesado": True, "respondido": False, "motivo": str(exc)}
    return {"procesado": True, "respondido": True}
