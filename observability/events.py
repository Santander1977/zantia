"""
Observabilidad — componente ausente por completo en Dani (002: "ni un
solo nodo de logging/métricas fue encontrado en la autopsia").

Registro append-only, separado del estado operativo vivo (004, sección
12): el estado puede purgarse, la auditoría no se sobreescribe.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class EventType(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    TOOL_INVOKED = "TOOL_INVOKED"
    GUARDRAIL_DECISION = "GUARDRAIL_DECISION"
    ERROR = "ERROR"


@dataclass
class Event:
    conversation_id: str
    type: EventType
    payload: Dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventLog:
    """Append-only. La lista en memoria basta para el MVP (sección 26);
    un sink a archivo JSONL queda disponible para quien quiera
    persistencia real entre procesos, sin cambiar la interfaz."""

    def __init__(self) -> None:
        self._events: List[Event] = []

    def record(self, conversation_id: str, type: EventType, **payload: Any) -> Event:
        event = Event(conversation_id=conversation_id, type=type, payload=payload)
        self._events.append(event)
        return event

    def for_conversation(self, conversation_id: str) -> List[Event]:
        return [e for e in self._events if e.conversation_id == conversation_id]

    def all(self) -> List[Event]:
        return list(self._events)
