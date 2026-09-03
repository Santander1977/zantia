"""
service/app.py — capa de transporte HTTP del proceso ZANTIA (decisión
D-5, `docs/decisions/d-5-empaquetado-fastapi-chatwoot.md`). Sin lógica
de dominio: solo traduce HTTP <-> `domains/health/gateway.py` (ya
construido, sin tocar) a través de `ChatwootChannel`
(`channels/chatwoot_channel.py`, sin tocar).

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

import logging

from fastapi import FastAPI, Request

from channels.chatwoot_channel import ChatwootChannel, ChatwootChannelError
from channels.contract import OutboundMessage
from domains.health.activity_source import MockActivitySource
from domains.health.config import HealthConfigError, build_appointment_service
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.identity_store import build_identity_store
from domains.health.reminder_manager import ReminderManager
from domains.health.result_sink import MockActivityResultSink

logger = logging.getLogger("zantia.service")

app = FastAPI(title="ZANTIA")


def _construir_canal_chatwoot() -> ChatwootChannel:
    import os

    base_url = os.environ.get("CHATWOOT_URL")
    account_id = os.environ.get("CHATWOOT_ACCOUNT_ID")
    if not base_url or not account_id:
        raise HealthConfigError(
            "CHATWOOT_URL y CHATWOOT_ACCOUNT_ID son obligatorias para arrancar el "
            "webhook de Chatwoot (ver .env.example) — no configuradas."
        )
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/chatwoot")
async def webhook_chatwoot(request: Request) -> dict:
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
