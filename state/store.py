"""
StateStore — persistencia del ConversationState (004, secciones 11-12).

Decisión de stack documentada en
/Users/enzoalfonso/recado/006-construccion-zantia.md: SQLite (vía el
módulo estándar `sqlite3`, sin ORM) como motor real de persistencia del
MVP — cero dependencias externas, cero servidor que levantar, con
semántica de fila+versión que demuestra concurrencia optimista real.
`InMemoryStateStore` existe aparte para pruebas unitarias puras sin E/S.

Ambas implementaciones cumplen el mismo protocolo `StateStore`, así que
migrar a Postgres en el futuro es agregar una tercera implementación,
no reescribir el Orchestrator (004, sección 11: "el principio conceptual
es independiente de la tecnología elegida").
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Protocol

from .models import ConversationState


class ConcurrencyConflictError(Exception):
    """La versión que se intentó guardar ya no es la vigente (004, sección 11:
    concurrencia optimista como red de seguridad)."""

    def __init__(self, conversation_id: str, version_esperada: int):
        self.conversation_id = conversation_id
        self.version_esperada = version_esperada
        super().__init__(
            f"Conflicto de concurrencia en '{conversation_id}': "
            f"la versión {version_esperada} ya no es la vigente."
        )


class StateStore(Protocol):
    def get(self, conversation_id: str) -> Optional[ConversationState]: ...

    def create(self, conversation_id: str, canal: str) -> ConversationState: ...

    def save(self, state: ConversationState, expected_version: int) -> ConversationState:
        """Persiste `state`, exigiendo que la versión vigente en el store
        sea exactamente `expected_version`. Si no lo es, lanza
        ConcurrencyConflictError (004, sección 11)."""
        ...


class InMemoryStateStore:
    """Implementación de referencia, sin E/S — usada en pruebas unitarias
    puras del resto de componentes (no del propio store)."""

    def __init__(self) -> None:
        self._data: dict[str, ConversationState] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> Optional[ConversationState]:
        return self._data.get(conversation_id)

    def create(self, conversation_id: str, canal: str) -> ConversationState:
        with self._lock:
            if conversation_id in self._data:
                return self._data[conversation_id]
            state = ConversationState(conversation_id=conversation_id, canal=canal)
            self._data[conversation_id] = state
            return state

    def save(self, state: ConversationState, expected_version: int) -> ConversationState:
        with self._lock:
            actual = self._data.get(state.conversation_id)
            actual_version = actual.version if actual else 0
            if actual_version != expected_version:
                raise ConcurrencyConflictError(state.conversation_id, expected_version)
            nuevo = state.model_copy(update={"version": expected_version + 1})
            self._data[state.conversation_id] = nuevo
            return nuevo


class SQLiteStateStore:
    """StateStore real, respaldado por SQLite (stdlib, sin dependencias).

    Usa `sqlite3.connect(":memory:")` en tests para tener semántica de
    base de datos real sin tocar el filesystem, y un archivo real
    (`ZANTIA_DB_PATH`, ver .env.example) fuera de tests.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            # sqlite3.connect no crea directorios intermedios — sin esto,
            # una ZANTIA_DB_PATH apuntando a una carpeta que todavía no
            # existe (ej. primer deploy) rompe con un error críptico en
            # el primer mensaje real en vez de al arrancar el proceso.
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: el MVP es de un solo proceso/hilo por
        # conversación en la práctica; se documenta como simplificación.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_state (
                conversation_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, conversation_id: str) -> Optional[ConversationState]:
        cur = self._conn.execute(
            "SELECT data FROM conversation_state WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ConversationState.model_validate_json(row[0])

    def create(self, conversation_id: str, canal: str) -> ConversationState:
        with self._lock:
            existing = self.get(conversation_id)
            if existing is not None:
                return existing
            state = ConversationState(conversation_id=conversation_id, canal=canal)
            self._conn.execute(
                "INSERT INTO conversation_state (conversation_id, version, data) "
                "VALUES (?, ?, ?)",
                (conversation_id, state.version, state.model_dump_json()),
            )
            self._conn.commit()
            return state

    def save(self, state: ConversationState, expected_version: int) -> ConversationState:
        with self._lock:
            nuevo = state.model_copy(update={"version": expected_version + 1})
            cur = self._conn.execute(
                "UPDATE conversation_state SET version = ?, data = ? "
                "WHERE conversation_id = ? AND version = ?",
                (
                    nuevo.version,
                    nuevo.model_dump_json(),
                    state.conversation_id,
                    expected_version,
                ),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                raise ConcurrencyConflictError(state.conversation_id, expected_version)
            return nuevo

    def close(self) -> None:
        self._conn.close()
