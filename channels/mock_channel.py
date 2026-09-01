"""
MockChannel (prompt 007, sección 30) — implementa el `Channel` genérico
del Core (`channels/contract.py`), sin WhatsApp ni telefonía real, para
poder demostrar `patient message -> ZANTIA -> agent response` end to
end. El contrato ya está listo para sustituirse por un canal real
(WhatsApp/Web/Voz/SMS) sin tocar el Core ni el dominio (sección 39).
"""
from __future__ import annotations

from collections import deque
from typing import Deque, List

from .contract import InboundMessage, OutboundMessage


class MockChannel:
    def __init__(self, canal: str = "mock") -> None:
        self._canal = canal
        self._inbound_queue: Deque[InboundMessage] = deque()
        self.sent: List[OutboundMessage] = []
        self._contador = 0

    def enqueue_patient_message(self, conversation_id: str, text: str) -> InboundMessage:
        self._contador += 1
        mensaje = InboundMessage(
            conversation_id=conversation_id,
            message_id=f"{conversation_id}-msg-{self._contador}",
            canal=self._canal,
            text=text,
        )
        self._inbound_queue.append(mensaje)
        return mensaje

    def receive(self) -> InboundMessage:
        return self._inbound_queue.popleft()

    def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)

    def last_sent_to(self, conversation_id: str) -> str:
        for mensaje in reversed(self.sent):
            if mensaje.conversation_id == conversation_id:
                return mensaje.text
        return ""
