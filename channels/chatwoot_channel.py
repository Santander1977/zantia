"""
ChatwootChannel — implementación real del `Channel` Protocol
(`contract.py`, sin modificarlo) contra la API de Chatwoot, para recibir
y responder mensajes de WhatsApp vía el mecanismo ya usado en este
ecosistema (Chatwoot + webhook — ver decisión D-5,
`docs/decisions/d-5-empaquetado-fastapi-chatwoot.md`).

Deliberadamente agnóstico de dominio: no importa nada de `domains/`.
Quien lo conecta con `domains/health/gateway.py` es `service/app.py`
(la capa de transporte HTTP), no este módulo.

Modelo pull/push: `Channel.receive()` es, por diseño del contrato
existente, un método de "pull" (igual que `MockChannel`, que hace
`popleft()` de una cola interna). Un webhook real es "push" (Chatwoot
nos llama a nosotros) — se concilian los dos modelos con una cola
interna: `handle_webhook_payload()` (llamado por el handler HTTP de
`service/app.py` en cuanto llega el POST) empuja a la cola, y
`receive()` la desencola — mismo patrón exacto que
`MockChannel.enqueue_patient_message`/`receive`, sin inventar un
mecanismo nuevo.

Sin red real usada en NINGÚN test de este módulo — `_post_json` es la
única función que la usaría, y los tests la sustituyen por inyección
(`http_post` en el constructor).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from .contract import InboundMessage, OutboundMessage


class ChatwootChannelError(Exception):
    pass


def _post_json_real(url: str, headers: Dict[str, str], body: Dict[str, Any]) -> None:
    """Única función de este módulo que toca la red real — stdlib
    `urllib`, mismo patrón que `domains/health/hrmm_http.py:RealHttpClient`
    (D-1: sin dependencias HTTP nuevas)."""
    datos = json.dumps(body).encode("utf-8")
    peticion = urllib.request.Request(url, data=datos, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(peticion, timeout=10.0) as respuesta:
            respuesta.read()
    except urllib.error.HTTPError as exc:
        raise ChatwootChannelError(f"Chatwoot respondió {exc.code} al enviar mensaje: {exc.read()!r}") from exc
    except urllib.error.URLError as exc:
        raise ChatwootChannelError(f"No se pudo conectar a Chatwoot: {exc}") from exc


@dataclass
class ChatwootChannel:
    """`account_id`/`inbox_id` identifican el inbox de PRUEBA en
    Chatwoot (nunca el de producción de HRMM/Andrés — ver recado 012,
    límite explícito del usuario). `base_url`/`api_token_env_var` se
    leen de variables de entorno, nunca hardcodeadas (ver .env.example)."""

    base_url: str
    account_id: str
    api_token_env_var: str = "CHATWOOT_API_TOKEN"
    canal: str = "chatwoot"
    http_post: Callable[[str, Dict[str, str], Dict[str, Any]], None] = _post_json_real

    _inbound_queue: Deque[InboundMessage] = field(default_factory=deque, init=False, repr=False)
    sent: List[OutboundMessage] = field(default_factory=list, init=False, repr=False)
    # conversation_id (Chatwoot, int) -> canal_conversation_id (str) usado
    # como InboundMessage.conversation_id, y viceversa para responder.
    _conversaciones_chatwoot: Dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def handle_webhook_payload(self, payload: Dict[str, Any]) -> Optional[InboundMessage]:
        """Traduce el evento `message_created` de Chatwoot a
        `InboundMessage` y lo encola. Devuelve None (y NO encola) si no
        es un mensaje entrante genuino de un paciente — evita procesar
        el eco de nuestras propias respuestas salientes (`message_type
        != "incoming"`), la causa más común de bucles infinitos en
        integraciones de webhook mal filtradas."""
        if payload.get("event") != "message_created":
            return None
        if payload.get("message_type") != "incoming":
            return None

        conversacion = payload.get("conversation") or {}
        chatwoot_conversation_id = conversacion.get("id")
        if chatwoot_conversation_id is None:
            return None

        remitente = (
            (conversacion.get("contact_inbox") or {}).get("source_id")
            or (payload.get("sender") or {}).get("phone_number")
        )
        if not remitente:
            raise ChatwootChannelError(
                "Webhook de Chatwoot sin identificador de remitente "
                "(contact_inbox.source_id ni sender.phone_number) — no se "
                "puede correlacionar la conversación, se rechaza en vez de inventarlo."
            )

        texto = payload.get("content") or ""
        conversation_id = str(remitente)
        self._conversaciones_chatwoot[conversation_id] = chatwoot_conversation_id

        mensaje = InboundMessage(
            conversation_id=conversation_id,
            message_id=str(payload.get("id", f"chatwoot-{chatwoot_conversation_id}")),
            canal=self.canal,
            text=texto,
        )
        self._inbound_queue.append(mensaje)
        return mensaje

    def receive(self) -> InboundMessage:
        return self._inbound_queue.popleft()

    def send(self, message: OutboundMessage) -> None:
        chatwoot_conversation_id = self._conversaciones_chatwoot.get(message.conversation_id)
        if chatwoot_conversation_id is None:
            raise ChatwootChannelError(
                f"No hay conversación de Chatwoot registrada para {message.conversation_id!r} — "
                "solo se puede responder a una conversación que llegó por webhook en este proceso."
            )
        token = os.environ.get(self.api_token_env_var)
        if not token:
            raise ChatwootChannelError(
                f"Variable de entorno {self.api_token_env_var} no configurada (ver .env.example)."
            )
        url = f"{self.base_url.rstrip('/')}/api/v1/accounts/{self.account_id}/conversations/{chatwoot_conversation_id}/messages"
        self.http_post(url, {"api_access_token": token}, {"content": message.text, "message_type": "outgoing"})
        self.sent.append(message)
