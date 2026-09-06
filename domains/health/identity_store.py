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
`domains/health/agent.py:build_health_agent_context`) tiene su propio
ciclo de vida ligado a esa conversación puntual — nace y muere con
ella. Un dato que debe sobrevivir a TODAS las conversaciones de un
mismo teléfono, incluyendo reinicios del proceso, necesita vivir a un
nivel distinto: `HealthGateway` (compartido por todo el proceso, ver
`service/app.py`), respaldado por su propio archivo/tabla SQLite.
(Nota de corrección, recado 029: este párrafo decía que
`core/agent_contract.py:build_orchestrator` no conectaba
`ZANTIA_DB_PATH` — eso era cierto cuando se escribió, pero quedó
RESUELTO en el recado 021/R-22; `build_orchestrator` ya lee
`ZANTIA_DB_PATH` de verdad. La separación de stores entre este archivo
y `state/store.py` se sostiene por la razón de ciclo de vida/clave
primaria de arriba, no por esa brecha ya cerrada — ver recado 021 para
el detalle completo de esa decisión.)

Retención (recado 016, extensión de R-20 — decisiones de producto YA
TOMADAS por el usuario, 2026-09-03, resolviendo lo que el recado 014
había dejado explícitamente PENDIENTE):
- **Vencimiento automático**: una identidad VERIFICADO deja de
  considerarse vigente a los `RETENCION_IDENTIDAD_DIAS` (180) días de
  `verificado_en` — ver `IdentidadCanal.vigente()`. Vencida, se trata
  como si la fila no existiera (nunca se hidrata `_identidad_resuelta`
  en `gateway.py`) — sin mensaje especial, el wizard de 3 pasos (012/014)
  se dispara de nuevo exactamente igual que con un teléfono nuevo.
- **Eliminación a pedido del paciente**: `eliminar()` — borrado REAL de
  la fila (no un cambio de estado), disparado desde
  `domains/health/gateway.py` cuando `HealthBrain` detecta y confirma
  la intención ("olvida mi información" y equivalentes, ver
  `domains/health/brain.py:_OLVIDAR`) — nunca automático, siempre tras
  confirmación explícita del titular.

Ver `.ai/DATA_MODEL.md` (política de retención completa) y
`.ai/RISKS.md` R-20 (MITIGADO desde recado 016).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol

# Ventana de retención de una identidad VERIFICADA (recado 016, requisito
# #1.3: "constante nombrada y fácil de encontrar/cambiar — no un número
# mágico repetido en varios lugares"). Único lugar del proyecto que define
# este valor — `gateway.py` y los tests lo importan de acá, nunca lo
# repiten.
RETENCION_IDENTIDAD_DIAS = 180


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
    # Nombre real del paciente (recado 034) — capturado UNA SOLA VEZ, en
    # el momento de `marcar_verificado` (viene de `buscar_paciente`, ya
    # consultado de todas formas durante el wizard de identidad — nunca
    # se vuelve a pedir a hrmm-backend después). `Optional` a propósito:
    # filas persistidas ANTES de este recado no lo tienen (migración
    # defensiva en `SQLiteIdentidadCanalStore._init_schema`), y
    # `buscar_paciente` podría no traer nombre para algún paciente real.
    nombre: Optional[str] = None

    def vigente(self, ahora: Optional[datetime] = None) -> bool:
        """VERIFICADO y dentro de la ventana de retención
        (`RETENCION_IDENTIDAD_DIAS`) — `False` para `PENDIENTE_VERIFICACION`
        (nunca se hidrata, sin cambios de recado 014) o para una fila
        `VERIFICADO` ya vencida (recado 016, requisito #1.2: se trata
        como si no existiera, sin ningún mensaje especial de "tu
        identidad venció" — más simple, sin UX dedicada para este caso)."""
        if self.estado != EstadoIdentidadCanal.VERIFICADO or self.verificado_en is None:
            return False
        ahora = ahora or _utcnow()
        return (ahora - self.verificado_en) <= timedelta(days=RETENCION_IDENTIDAD_DIAS)


class IdentidadCanalStore(Protocol):
    def get(self, telefono: str) -> Optional[IdentidadCanal]: ...

    def guardar_pendiente(self, telefono: str, documento: str) -> IdentidadCanal:
        """Registra (o reemplaza) la asociación candidata mientras se
        espera el código de verificación — NUNCA se trata como
        confiable todavía (ver `marcar_verificado`)."""
        ...

    def marcar_verificado(self, telefono: str, documento: str, nombre: Optional[str] = None) -> IdentidadCanal:
        """Único punto que escribe estado=VERIFICADO — se llama tras un
        código de verificación válido, tanto en el primer registro
        (`domains/health/gateway.py:_procesar_codigo_de_identificacion`)
        como al re-verificar después de un vencimiento (recado 016,
        requisito #1.4: UPSERT — actualiza `verificado_en`, nunca crea
        una fila duplicada, la `telefono` sigue siendo la llave primaria).
        `nombre` (recado 034) se guarda aquí, una sola vez — nunca se
        vuelve a consultar `buscar_paciente` solo para saludar."""
        ...

    def eliminar(self, telefono: str) -> None:
        """Borrado REAL de la fila (recado 016, requisito #2.4) —
        nunca un cambio de estado. Idempotente: no falla si la fila ya
        no existe (mismo criterio que un DELETE SQL normal)."""
        ...


class SQLiteIdentidadCanalStore:
    """Implementación real — mismo criterio de minimalismo que
    `state/store.py:SQLiteStateStore` (sqlite3 stdlib, sin ORM, sin
    dependencias nuevas). Usa `:memory:` por defecto (tests/demo) y un
    archivo real (`ZANTIA_IDENTIDAD_DB_PATH`, ver `.env.example` y
    `build_identity_store`) fuera de tests."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            # Mismo criterio que `state/store.py:SQLiteStateStore`
            # (recado 021, R-22): `sqlite3.connect` NO crea directorios
            # intermedios — sin esto, apuntar `ZANTIA_IDENTIDAD_DB_PATH`
            # a una carpeta nueva (ej. un volumen recién montado en
            # EasyPanel) revienta con un error críptico en el primer
            # arranque real, en vez de crear el archivo sin más (recado
            # 029, preparación para volumen persistente).
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
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
                verificado_en TEXT,
                nombre TEXT
            )
            """
        )
        self._conn.commit()
        self._migrar_columna_nombre_si_falta()

    def _migrar_columna_nombre_si_falta(self) -> None:
        """Migración defensiva (recado 034): una tabla `identidad_canal`
        creada ANTES de este recado no tiene la columna `nombre` —
        `CREATE TABLE IF NOT EXISTS` no altera una tabla que ya existe.
        `ALTER TABLE ADD COLUMN` falla con "duplicate column" cuando la
        tabla es nueva (ya la trae del CREATE de arriba) — se ignora
        SOLO ese error puntual, cualquier otro se propaga."""
        try:
            self._conn.execute("ALTER TABLE identidad_canal ADD COLUMN nombre TEXT")
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

    def get(self, telefono: str) -> Optional[IdentidadCanal]:
        cur = self._conn.execute(
            "SELECT telefono, documento, estado, verificado_en, nombre FROM identidad_canal WHERE telefono = ?",
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

    def marcar_verificado(self, telefono: str, documento: str, nombre: Optional[str] = None) -> IdentidadCanal:
        verificado_en = _utcnow()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO identidad_canal (telefono, documento, estado, verificado_en, nombre)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telefono) DO UPDATE SET
                    documento = excluded.documento,
                    estado = excluded.estado,
                    verificado_en = excluded.verificado_en,
                    nombre = excluded.nombre
                """,
                (telefono, documento, EstadoIdentidadCanal.VERIFICADO.value, verificado_en.isoformat(), nombre),
            )
            self._conn.commit()
        return IdentidadCanal(telefono, documento, EstadoIdentidadCanal.VERIFICADO, verificado_en, nombre)

    def eliminar(self, telefono: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM identidad_canal WHERE telefono = ?", (telefono,))
            self._conn.commit()

    @staticmethod
    def _fila_a_identidad(fila) -> IdentidadCanal:
        telefono, documento, estado, verificado_en, nombre = fila
        return IdentidadCanal(
            telefono=telefono,
            documento=documento,
            estado=EstadoIdentidadCanal(estado),
            verificado_en=datetime.fromisoformat(verificado_en) if verificado_en else None,
            nombre=nombre,
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
