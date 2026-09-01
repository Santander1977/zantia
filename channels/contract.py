"""
Contrato de canal — el canal exacto sigue PENDIENTE de decisión
(004, sección 22; 005, sección 19). Este archivo define solo la
interfaz que cualquier adaptador de canal (WhatsApp, Telegram, web...)
deberá implementar, para que el Orchestrator nunca dependa del canal
concreto.

NO hay ninguna implementación real todavía — a propósito.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InboundMessage:
    conversation_id: str
    message_id: str
    canal: str
    text: str


@dataclass(frozen=True)
class OutboundMessage:
    conversation_id: str
    text: str


class Channel(Protocol):
    """Todo adaptador de canal real deberá poder recibir un mensaje
    normalizado y enviar una respuesta — nada más. La lógica de
    conversación nunca vive aquí."""

    def receive(self) -> InboundMessage: ...

    def send(self, message: OutboundMessage) -> None: ...
