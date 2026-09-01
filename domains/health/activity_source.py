"""
Entrada de actividades (prompt 007, sección 7).

Contrato pensado para poder exponerse después como `POST /activities`
sin cambiar el resto del dominio — para el MVP, `MockActivitySource`
simula la API del sistema IPS en memoria.

El agente NUNCA modifica arbitrariamente la Activity original: `update`
solo debe usarse desde la capa de orquestación de dominio, no desde el
Brain.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Protocol

from .models import Activity, ActivityStatus


class ActivityNotFoundError(Exception):
    pass


class ActivitySource(Protocol):
    def create(self, activity: Activity) -> Activity: ...

    def get(self, activity_id: str) -> Optional[Activity]: ...

    def update(self, activity: Activity) -> Activity: ...

    def cancel(self, activity_id: str) -> Activity: ...


class MockActivitySource:
    """Simula la API del sistema IPS. `create` es idempotente por
    `activity_id` (prompt 007, sección 28)."""

    def __init__(self) -> None:
        self._activities: Dict[str, Activity] = {}
        self._lock = threading.Lock()

    def create(self, activity: Activity) -> Activity:
        with self._lock:
            existente = self._activities.get(activity.activity_id)
            if existente is not None:
                return existente  # idempotente: no se duplica
            self._activities[activity.activity_id] = activity
            return activity

    def get(self, activity_id: str) -> Optional[Activity]:
        return self._activities.get(activity_id)

    def update(self, activity: Activity) -> Activity:
        with self._lock:
            if activity.activity_id not in self._activities:
                raise ActivityNotFoundError(activity.activity_id)
            self._activities[activity.activity_id] = activity
            return activity

    def cancel(self, activity_id: str) -> Activity:
        with self._lock:
            actividad = self._activities.get(activity_id)
            if actividad is None:
                raise ActivityNotFoundError(activity_id)
            cancelada = actividad.model_copy(update={"status": ActivityStatus.CANCELLED})
            self._activities[activity_id] = cancelada
            return cancelada

    def list_all(self) -> List[Activity]:
        return list(self._activities.values())
