"""
Observabilidad — componente ausente por completo en Dani (002: "ni un
solo nodo de logging/métricas fue encontrado en la autopsia").

Registro append-only, separado del estado operativo vivo (004, sección
12): el estado puede purgarse, la auditoría no se sobreescribe.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Protocol


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


class EventLogProtocol(Protocol):
    """Contrato duck-typed de EventLog — mismo criterio que
    `state.store.StateStore` (Protocol explícito): `EventLog`
    (memoria de proceso) y `SQLiteEventLog` (recado 037, persistencia
    real) lo implementan ambas, sin heredar de una base común."""

    def record(self, conversation_id: str, type: EventType, **payload: Any) -> Event: ...

    def for_conversation(self, conversation_id: str) -> List[Event]: ...

    def all(self) -> List[Event]: ...


class EventLog:
    """Append-only, 100% en memoria de proceso — implementación de
    referencia sin E/S, útil para pruebas unitarias puras. Para
    persistencia real entre procesos/reinicios, ver `SQLiteEventLog`
    (recado 037, R-11)."""

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


class SQLiteEventLog:
    """EventLog real, respaldado por SQLite (stdlib, sin dependencias) —
    mismo patrón exacto que `state.store.SQLiteStateStore` (recado 021)
    aplicado a la auditoría append-only (recado 037, Parte 1, cierra
    R-11 para EventLog). Usa `sqlite3.connect(":memory:")` en tests/sin
    configurar `ZANTIA_EVENTS_DB_PATH` (rápido, sin tocar el
    filesystem, pero YA usando SQL real en vez de una lista de Python
    — mismo motor y esquema en ambos casos, la única diferencia es si
    hay un archivo real detrás), y un archivo real fuera de tests."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_conversation_id ON events (conversation_id)"
        )
        self._conn.commit()

    def record(self, conversation_id: str, type: EventType, **payload: Any) -> Event:
        event = Event(conversation_id=conversation_id, type=type, payload=payload)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (event_id, conversation_id, type, payload, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.conversation_id,
                    event.type.value,
                    json.dumps(event.payload),
                    event.timestamp.isoformat(),
                ),
            )
            self._conn.commit()
        return event

    def for_conversation(self, conversation_id: str) -> List[Event]:
        cur = self._conn.execute(
            "SELECT event_id, conversation_id, type, payload, timestamp FROM events "
            "WHERE conversation_id = ? ORDER BY seq ASC",
            (conversation_id,),
        )
        return [self._fila_a_event(fila) for fila in cur.fetchall()]

    def all(self) -> List[Event]:
        cur = self._conn.execute(
            "SELECT event_id, conversation_id, type, payload, timestamp FROM events ORDER BY seq ASC"
        )
        return [self._fila_a_event(fila) for fila in cur.fetchall()]

    def _fila_a_event(self, fila) -> Event:
        event_id, conversation_id, type_, payload, timestamp = fila
        return Event(
            event_id=event_id,
            conversation_id=conversation_id,
            type=EventType(type_),
            payload=json.loads(payload),
            timestamp=datetime.fromisoformat(timestamp),
        )

    def close(self) -> None:
        self._conn.close()
