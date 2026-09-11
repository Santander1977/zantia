"""
WebChannel — implementación real del `Channel` Protocol (`contract.py`,
sin modificarlo) para el widget de chat.semcolombia.com (`eis-chat-hrmm`,
ver `/Users/enzoalfonso/recado/077-protocolo-webchat-hrmm-vs-n8n.md` y
`078-plan-webchannel-para-webchat-hrmm.md`) — el canal MÁS SIMPLE de los
tres que existen en este proyecto.

Diferencia estructural frente a `TelegramChannel`/`ChatwootChannel`
(recado 078, análisis previo): aquellos dos son "push" en dos pasos —
el webhook ENTREGA un mensaje y el envío de la respuesta es una llamada
HTTP SALIENTE separada, desacoplada en el tiempo (por eso necesitan una
cola interna real, `receive()` desencola algo que llegó en una petición
anterior). Este canal es un ciclo request/response SÍNCRONO de un solo
paso: el navegador (vía el Express de `eis-chat-hrmm`) espera la
respuesta en la MISMA petición HTTP que mandó el mensaje. `send()` nunca
toca la red — solo dejar constancia en `sent` (mismo criterio de
auditoría que `MockChannel.sent`/`TelegramChannel.sent`); el handler HTTP
de `service/app.py` ya tiene el texto de la respuesta en una variable
local (el valor de retorno de `handle_inbound_message`) y lo devuelve
directamente, sin necesitar leerlo de vuelta de este canal.

Sin `secret_token`/verificación de origen — a diferencia de
`TELEGRAM_WEBHOOK_SECRET` (obligatoria, fail-fast). Decisión EXPLÍCITA
del usuario para esta primera versión (recado 079): el Express de
`eis-chat-hrmm` no envía ningún secreto hoy, y nada del lado de ZANTIA
podría validar un secreto que el otro extremo nunca manda. Riesgo
conocido y documentado (`.ai/RISKS.md` R-26, `.ai/API_CONTRACTS.md`,
`.ai/SECURITY.md`) — no bloquea el despliegue de hoy, sí es mejora
pendiente.

`sessionId` (persistente en `localStorage` del navegador desde el commit
`c83d3d9` de `eis-chat-hrmm`, expiración deslizante de 24h) es el
`conversation_id` — mismo patrón que `chat_id` de Telegram: autosuficiente,
sin ninguna tabla `_conversaciones_*` que mantener (mismo motivo exacto
que Telegram, no Chatwoot — el identificador que llega ES el mismo que
se necesita para "responder"; acá ni siquiera hace falta guardar nada
más allá de esta única petición).

Sin red real usada en NINGÚN test de este módulo (no hay ninguna función
que la use — este canal, a diferencia de los otros dos, no tiene ningún
`http_post` que inyectar)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List

from .contract import InboundMessage, OutboundMessage


class WebChannelError(Exception):
    pass


@dataclass
class WebChannel:
    canal: str = "web"

    _inbound_queue: Deque[InboundMessage] = field(default_factory=deque, init=False, repr=False)
    _contador: int = field(default=0, init=False, repr=False)
    sent: List[OutboundMessage] = field(default_factory=list, init=False, repr=False)

    def handle_request(self, message: str, session_id: str) -> InboundMessage:
        """Traduce el body ya deserializado del POST de `eis-chat-hrmm`
        (`{message, sessionId}`, ver recado 077) a `InboundMessage` y lo
        encola — mismo patrón que `handle_webhook_payload` de los otros
        2 canales, adaptado a un payload que ya llega estructurado (no un
        webhook de terceros con forma propia que traducir campo por
        campo). A diferencia de esos dos, nunca devuelve `None` en
        silencio: un `message`/`session_id` vacíos son un payload
        malformado (nunca debería pasar si `eis-chat-hrmm` sigue su
        propio contrato — valida longitud y no-vacío antes de reenviar,
        ver recado 077) — se rechaza explícito con `WebChannelError`,
        igual que `TelegramChannel` rechaza un Update con `message` pero
        sin `chat.id`, en vez de inventar un `session_id`."""
        if not session_id:
            raise WebChannelError("sessionId vacío o ausente — no se puede identificar la conversación.")
        if not message:
            raise WebChannelError("message vacío o ausente.")

        self._contador += 1
        mensaje = InboundMessage(
            conversation_id=session_id,
            message_id=f"{session_id}-web-{self._contador}",
            canal=self.canal,
            text=message,
        )
        self._inbound_queue.append(mensaje)
        return mensaje

    def receive(self) -> InboundMessage:
        return self._inbound_queue.popleft()

    def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)
