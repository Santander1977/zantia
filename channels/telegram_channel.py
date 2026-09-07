"""
TelegramChannel — implementación real del `Channel` Protocol
(`contract.py`, sin modificarlo) contra la Bot API pública de Telegram
(recado 022), con webhook (no polling) — ver
`docs/decisions/d-7-telegram-webhook-vs-polling.md` para la
justificación completa de esa elección.

Deliberadamente agnóstico de dominio: no importa nada de `domains/`.
Quien lo conecta con `domains/health/gateway.py` es `service/app.py`
(la capa de transporte HTTP), no este módulo — mismo principio ya
aplicado en `chatwoot_channel.py`.

Mismo modelo pull/push que `ChatwootChannel`: `handle_webhook_payload()`
(llamado por el handler HTTP de `service/app.py`) traduce el "Update"
de Telegram y lo encola; `receive()` la desencola.

Diferencia deliberada frente a `ChatwootChannel`: NO existe una tabla
`_conversaciones_*` interna. En Chatwoot, `conversation_id` (el
identificador de canal, ej. el teléfono) y el ID de conversación que
exige su API de envío son DOS números distintos, así que hace falta
recordar la relación. En Telegram, el `chat.id` del Update ES,
literalmente, el mismo valor que `sendMessage` necesita para responder
— `conversation_id` (`InboundMessage`/`OutboundMessage`, siempre `str`
en este contrato) es `str(chat_id)`, y `send()` simplemente hace
`int(message.conversation_id)` de vuelta. Ninguna tabla nueva que
mantener sincronizada.

Sin red real usada en NINGÚN test de este módulo — `http_post` es la
única función que la tocaría, sustituida por inyección en los tests
(mismo patrón que `ChatwootChannel.http_post`).

Verificación del origen del webhook (recado 023, cierra R-23): a
diferencia de Chatwoot (que no ofrece ningún mecanismo de firma),
Telegram SÍ soporta un `secret_token` al registrar el webhook
(`setWebhook`), que reenvía en cada petición como header
`X-Telegram-Bot-Api-Secret-Token` — confirmado, es parte de la Bot API
pública y estable de Telegram, no requiere investigar código de
terceros. `verificar_secreto_webhook()` valida ese header ANTES de que
`service/app.py` llegue a llamar `handle_webhook_payload` — se
implementa como un método propio de `TelegramChannel` (no en
`service/app.py`, que solo debe traducir HTTP, mismo principio de capas
de todo este archivo) usando `hmac.compare_digest` (mismo criterio que
`hrmm-backend/app/trusted_auth.py:verificar_secreto_confianza`, ya
verificado en recado 015 — comparación en tiempo constante, no `==`).
"""
from __future__ import annotations

import hmac
import json
import os
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from .contract import InboundMessage, OutboundMessage


class TelegramChannelError(Exception):
    pass


def _post_json_real(url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Única función de este módulo que toca la red real — stdlib
    `urllib`, mismo patrón que `chatwoot_channel.py:_post_json_real` y
    `domains/health/hrmm_http.py:RealHttpClient` (D-1: sin dependencias
    HTTP nuevas). A diferencia de Chatwoot (auth por header), la Bot API
    de Telegram exige el token EN LA RUTA (`/bot<token>/<metodo>`) — así
    lo documenta la API pública de Telegram, no es una elección de este
    proyecto — por eso esta función no recibe `headers`."""
    datos = json.dumps(body).encode("utf-8")
    peticion = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10.0) as respuesta:
            return json.loads(respuesta.read())
    except urllib.error.HTTPError as exc:
        raise TelegramChannelError(f"Telegram respondió {exc.code} al enviar mensaje: {exc.read()!r}") from exc
    except urllib.error.URLError as exc:
        raise TelegramChannelError(f"No se pudo conectar a Telegram: {exc}") from exc


@dataclass
class TelegramChannel:
    """`bot_token_env_var` se lee de una variable de entorno, nunca
    hardcodeada (ver `.env.example`) — mismo criterio que
    `ChatwootChannel.api_token_env_var`. El token se valida de forma
    PEREZOSA, en `send()`, no al construir el canal — mismo patrón
    exacto ya usado (y probado) por `ChatwootChannel` para su propio
    secreto: el proceso puede arrancar y RECIBIR mensajes sin el token
    configurado, solo falla al intentar responder, con un error
    explícito (nunca silencioso)."""

    bot_token_env_var: str = "TELEGRAM_BOT_TOKEN"
    webhook_secret_env_var: str = "TELEGRAM_WEBHOOK_SECRET"
    canal: str = "telegram"
    base_url: str = "https://api.telegram.org"
    http_post: Callable[[str, Dict[str, Any]], Dict[str, Any]] = _post_json_real

    _inbound_queue: Deque[InboundMessage] = field(default_factory=deque, init=False, repr=False)
    sent: List[OutboundMessage] = field(default_factory=list, init=False, repr=False)

    def verificar_secreto_webhook(self, secreto_recibido: Optional[str]) -> bool:
        """`True` solo si `secreto_recibido` (el header
        `X-Telegram-Bot-Api-Secret-Token` de la petición) coincide,
        byte a byte en tiempo constante, con `TELEGRAM_WEBHOOK_SECRET`.
        A diferencia de `bot_token_env_var` (perezoso, solo se necesita
        para ENVIAR), esta variable es OBLIGATORIA para poder RECIBIR
        con seguridad — si no está configurada, lanza en vez de
        devolver `True`/`False` en silencio: sin ella, no hay nada
        contra qué comparar, y aceptar cualquier petición sin secreto
        configurado sería degradar la protección en silencio (lo que
        este proyecto nunca hace, `.claude/rules/`)."""
        secreto_esperado = os.environ.get(self.webhook_secret_env_var)
        if not secreto_esperado:
            raise TelegramChannelError(
                f"Variable de entorno {self.webhook_secret_env_var} no configurada (ver .env.example) — "
                "no se puede validar el origen del webhook de Telegram."
            )
        return hmac.compare_digest(secreto_recibido or "", secreto_esperado)

    def handle_webhook_payload(self, payload: Dict[str, Any]) -> Optional[InboundMessage]:
        """Traduce un "Update" de Telegram a `InboundMessage` y lo
        encola. Devuelve `None` (sin encolar, sin error) para cualquier
        Update que no sea un mensaje de texto entrante genuino:
        `edited_message`/`channel_post`/`callback_query`/etc. (otros
        tipos de Update que Telegram puede mandar) y mensajes SIN texto
        (foto, sticker, audio — nada que este dominio conversacional
        pueda interpretar todavía) — mismo criterio que
        `ChatwootChannel` ignorando el eco de sus propios mensajes
        salientes: silencioso porque es el comportamiento ESPERADO, no
        un error.

        Si HAY un `message` con texto pero le falta `chat.id`, eso SÍ
        es un payload malformado (nunca debería pasar según el contrato
        público de Telegram) — se rechaza explícitamente, igual que
        `ChatwootChannel` rechaza un webhook sin remitente, en vez de
        inventar una correlación."""
        mensaje = payload.get("message")
        if mensaje is None:
            return None
        texto = mensaje.get("text")
        if not texto:
            return None

        chat = mensaje.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            raise TelegramChannelError(
                "Update de Telegram con mensaje de texto pero sin chat.id — "
                "no se puede correlacionar la conversación, se rechaza en vez de inventarlo."
            )

        conversation_id = str(chat_id)
        inbound = InboundMessage(
            conversation_id=conversation_id,
            message_id=str(mensaje.get("message_id", payload.get("update_id", ""))),
            canal=self.canal,
            text=texto,
        )
        self._inbound_queue.append(inbound)
        return inbound

    def receive(self) -> InboundMessage:
        return self._inbound_queue.popleft()

    def send(self, message: OutboundMessage) -> None:
        token = os.environ.get(self.bot_token_env_var)
        if not token:
            raise TelegramChannelError(
                f"Variable de entorno {self.bot_token_env_var} no configurada (ver .env.example)."
            )
        url = f"{self.base_url.rstrip('/')}/bot{token}/sendMessage"
        respuesta = self.http_post(url, {"chat_id": int(message.conversation_id), "text": message.text})
        if not respuesta.get("ok", False):
            raise TelegramChannelError(f"Telegram respondió sin éxito al enviar el mensaje: {respuesta!r}")
        self.sent.append(message)

    def send_typing_action(self, conversation_id: str) -> None:
        """Recado 056, Punto 4 — `sendChatAction` (acción "typing") de la
        Bot API pública de Telegram: le muestra al paciente el indicador
        nativo "escribiendo..." mientras el sistema procesa su mensaje
        (incluida la latencia real de una llamada a un LLM, con
        `HEALTH_BRAIN_TYPE=llm` activo). Telegram apaga este indicador
        solo (~5 segundos) o en cuanto llega el siguiente `sendMessage`
        real — quien llame a este método y necesite mantenerlo visible
        durante un procesamiento más largo debe volver a llamarlo
        periódicamente (ver `service/app.py`, que lo repite cada 4
        segundos en una tarea de fondo mientras dura el procesamiento
        real). Mismo criterio de error que `send()` — lanza
        `TelegramChannelError` explícito, nunca falla en silencio; es
        responsabilidad de quien llama decidir si un fallo aquí (best
        effort, cosmético) debe o no interrumpir el procesamiento real
        del mensaje (nunca debería)."""
        token = os.environ.get(self.bot_token_env_var)
        if not token:
            raise TelegramChannelError(
                f"Variable de entorno {self.bot_token_env_var} no configurada (ver .env.example)."
            )
        url = f"{self.base_url.rstrip('/')}/bot{token}/sendChatAction"
        respuesta = self.http_post(url, {"chat_id": int(conversation_id), "action": "typing"})
        if not respuesta.get("ok", False):
            raise TelegramChannelError(f"Telegram respondió sin éxito al enviar sendChatAction: {respuesta!r}")
