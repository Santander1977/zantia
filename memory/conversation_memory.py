"""
Memoria de conversación — Capa B de 004 sección 3.

Insumo de redacción para el Brain (continuidad natural), NUNCA fuente
de una decisión de flujo — esa autoridad es exclusiva del
ConversationState (state/). Ventana corta acotada, igual patrón que
Dani (Postgres/sessionKey — 002), aquí en memoria de proceso.
"""
from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Protocol


@dataclass
class Turn:
    role: str  # "user" | "agent"
    text: str
    timestamp: datetime


class ConversationMemoryProtocol(Protocol):
    """Contrato duck-typed — mismo criterio que `state.store.StateStore`
    (recado 037): `ConversationMemory` (proceso) y
    `SQLiteConversationMemory` (persistencia real) lo implementan
    ambas."""

    def add_turn(self, conversation_id: str, role: str, text: str) -> None: ...

    def get_recent(self, conversation_id: str) -> List[Turn]: ...


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


class SQLiteConversationMemory:
    """ConversationMemory real, respaldada por SQLite — mismo patrón
    que `state.store.SQLiteStateStore`/`observability.events.SQLiteEventLog`
    (recado 037, Parte 1, cierra R-11 para ConversationMemory).

    A diferencia de `ConversationState` (una fila por conversación,
    versionada) y de `EventLog` (append-only sin ventana), esta clase
    sigue respetando el MISMO contrato que la versión en memoria: sigue
    siendo la Capa B de 004 sección 3 — insumo de redacción, NUNCA
    fuente de una decisión de flujo — así que `get_recent()` sigue
    devolviendo como máximo `window_size` turnos, igual que el `deque`
    original. La TABLA en sí conserva el historial completo sin
    truncar (no se borra al superar la ventana): la ventana se aplica
    solo en la lectura. Esto es deliberado, no un descuido — es lo que
    permite auditar más adelante qué dijo realmente un LLM en un turno
    viejo, aunque ya haya salido de la ventana reciente del Brain. La
    política de retención de esta tabla queda con el mismo estado
    "PENDIENTE" ya documentado para `ConversationState` en
    `.ai/DATA_MODEL.md` — no se resuelve aquí, no se inventa una nueva."""

    def __init__(self, window_size: int = 8, db_path: str = ":memory:") -> None:
        self._window_size = window_size
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_conversation_id ON conversation_turns (conversation_id)"
        )
        self._conn.commit()

    def add_turn(self, conversation_id: str, role: str, text: str) -> None:
        turno = Turn(role=role, text=text, timestamp=datetime.now(timezone.utc))
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversation_turns (conversation_id, role, text, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (conversation_id, turno.role, turno.text, turno.timestamp.isoformat()),
            )
            self._conn.commit()

    def get_recent(self, conversation_id: str) -> List[Turn]:
        cur = self._conn.execute(
            "SELECT role, text, timestamp FROM conversation_turns WHERE conversation_id = ? "
            "ORDER BY seq DESC LIMIT ?",
            (conversation_id, self._window_size),
        )
        filas = cur.fetchall()
        return [
            Turn(role=role, text=text, timestamp=datetime.fromisoformat(timestamp))
            for role, text, timestamp in reversed(filas)
        ]

    def close(self) -> None:
        self._conn.close()
