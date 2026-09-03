"""
IdentidadCanalStore — persistencia de la identidad del CANAL (qué
documento real está asociado a un identificador de canal, ej. un
número de WhatsApp) MÁS ALLÁ de una sola conversación (recado 014,
extensión de R-15).

Hasta esta extensión, `HealthGateway._identidad_resuelta` (012) solo
vivía en memoria del PROCESO — un paciente ya identificado tenía que
volver a dar su documento en cada conversación nueva si el proceso se
reiniciaba entretanto (y en el diseño actual, siempre que se levante un
nuevo proceso). La tabla `identidad_canal` es la fuente de verdad de
"este teléfono ya demostró ser dueño de este documento", independiente
de cualquier `ConversationState`/Activity puntual.

Deliberadamente en un store PROPIO, no reutilizando `state/store.py`:
cada `HealthAgentContext` (uno por Activity/conversación,
`domains/health/agent.py:build_health_agent_context`) construye, vía
`core/agent_contract.py:build_orchestrator`, su PROPIO
`SQLiteStateStore(":memory:")` — nace y muere con esa conversación
puntual, sin conectar `ZANTIA_DB_PATH` (brecha de wiring preexistente,
no resuelta aquí — ver `.ai/RISKS.md`). Un dato que debe sobrevivir a
todas las conversaciones de un mismo teléfono, incluyendo reinicios del
proceso, necesita vivir a un nivel distinto: `HealthGateway` (compartido
por todo el proceso, ver `service/app.py`), respaldado por su propio
archivo/tabla SQLite.

Retención: sin política de vencimiento en esta fase — decisión
explícita del usuario (2026-09-02, requisito #4 del pedido). Ver
`.ai/DATA_MODEL.md` (política de retención) y `.ai/RISKS.md` (riesgo
abierto mientras no se defina).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EstadoIdentidadCanal(str, Enum):
    """Los dos únicos estados pedidos explícitamente (requisito #1) —
    nunca se agrega un tercero sin volver a confirmar con el usuario."""

    PENDIENTE_VERIFICACION = "PENDIENTE_VERIFICACION"
    VERIFICADO = "VERIFICADO"


@dataclass(frozen=True)
class IdentidadCanal:
    telefono: str
    documento: str
    estado: EstadoIdentidadCanal
    verificado_en: Optional[datetime]


class IdentidadCanalStore(Protocol):
    def get(self, telefono: str) -> Optional[IdentidadCanal]: ...

    def guardar_pendiente(self, telefono: str, documento: str) -> IdentidadCanal:
        """Registra (o reemplaza) la asociación candidata mientras se
        espera el código de verificación — NUNCA se trata como
        confiable todavía (ver `marcar_verificado`)."""
        ...

    def marcar_verificado(self, telefono: str, documento: str) -> IdentidadCanal:
        """Único punto que escribe estado=VERIFICADO — se llama
        exclusivamente tras un código de verificación válido
        (`domains/health/gateway.py:_procesar_codigo_de_identificacion`)."""
        ...


class SQLiteIdentidadCanalStore:
    """Implementación real — mismo criterio de minimalismo que
    `state/store.py:SQLiteStateStore` (sqlite3 stdlib, sin ORM, sin
    dependencias nuevas). Usa `:memory:` por defecto (tests/demo) y un
    archivo real (`ZANTIA_IDENTIDAD_DB_PATH`, ver `.env.example` y
    `build_identity_store`) fuera de tests."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identidad_canal (
                telefono TEXT PRIMARY KEY,
                documento TEXT NOT NULL,
                estado TEXT NOT NULL,
                verificado_en TEXT
            )
            """
        )
        self._conn.commit()

    def get(self, telefono: str) -> Optional[IdentidadCanal]:
        cur = self._conn.execute(
            "SELECT telefono, documento, estado, verificado_en FROM identidad_canal WHERE telefono = ?",
            (telefono,),
        )
        fila = cur.fetchone()
        if fila is None:
            return None
        return self._fila_a_identidad(fila)

    def guardar_pendiente(self, telefono: str, documento: str) -> IdentidadCanal:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO identidad_canal (telefono, documento, estado, verificado_en)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(telefono) DO UPDATE SET
                    documento = excluded.documento,
                    estado = excluded.estado,
                    verificado_en = NULL
                """,
                (telefono, documento, EstadoIdentidadCanal.PENDIENTE_VERIFICACION.value),
            )
            self._conn.commit()
        return IdentidadCanal(telefono, documento, EstadoIdentidadCanal.PENDIENTE_VERIFICACION, None)

    def marcar_verificado(self, telefono: str, documento: str) -> IdentidadCanal:
        verificado_en = _utcnow()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO identidad_canal (telefono, documento, estado, verificado_en)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telefono) DO UPDATE SET
                    documento = excluded.documento,
                    estado = excluded.estado,
                    verificado_en = excluded.verificado_en
                """,
                (telefono, documento, EstadoIdentidadCanal.VERIFICADO.value, verificado_en.isoformat()),
            )
            self._conn.commit()
        return IdentidadCanal(telefono, documento, EstadoIdentidadCanal.VERIFICADO, verificado_en)

    @staticmethod
    def _fila_a_identidad(fila) -> IdentidadCanal:
        telefono, documento, estado, verificado_en = fila
        return IdentidadCanal(
            telefono=telefono,
            documento=documento,
            estado=EstadoIdentidadCanal(estado),
            verificado_en=datetime.fromisoformat(verificado_en) if verificado_en else None,
        )

    def close(self) -> None:
        self._conn.close()


def build_identity_store(db_path_env_var: str = "ZANTIA_IDENTIDAD_DB_PATH") -> SQLiteIdentidadCanalStore:
    """Único punto que lee `ZANTIA_IDENTIDAD_DB_PATH` — mismo criterio
    que `domains/health/config.py:build_appointment_service` (una sola
    lectura de variable de entorno, al arrancar el proceso, nunca en
    medio de una conversación). Default seguro `:memory:` si no está
    definida — sin persistencia entre reinicios, igual que el default
    ya documentado para `ZANTIA_DB_PATH` en `.env.example`."""
    ruta = os.environ.get(db_path_env_var) or ":memory:"
    return SQLiteIdentidadCanalStore(ruta)
