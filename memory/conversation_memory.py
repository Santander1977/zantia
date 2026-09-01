"""
Memoria de conversación — Capa B de 004 sección 3.

Insumo de redacción para el Brain (continuidad natural), NUNCA fuente
de una decisión de flujo — esa autoridad es exclusiva del
ConversationState (state/). Ventana corta acotada, igual patrón que
Dani (Postgres/sessionKey — 002), aquí en memoria de proceso.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, List


@dataclass
class Turn:
    role: str  # "user" | "agent"
    text: str
    timestamp: datetime


class ConversationMemory:
    def __init__(self, window_size: int = 8) -> None:
        self._window_size = window_size
        self._turns: Dict[str, Deque[Turn]] = defaultdict(lambda: deque(maxlen=window_size))

    def add_turn(self, conversation_id: str, role: str, text: str) -> None:
        self._turns[conversation_id].append(
            Turn(role=role, text=text, timestamp=datetime.now(timezone.utc))
        )

    def get_recent(self, conversation_id: str) -> List[Turn]:
        return list(self._turns.get(conversation_id, ()))
