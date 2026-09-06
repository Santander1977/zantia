"""
Espejo local de catálogos de hrmm-backend (servicios/médicos) — nuevo
componente (recado de esta fase). HealthBrain (protegido, sin tocar)
NUNCA debe inventar especialidades ni médicos; este espejo es la única
fuente que `HrmmAppointmentService` consulta para traducir nombres de
servicio a `servicio_id`, y `medico_id` a nombre/consultorio, ya que
`GET /api/agenda/disponibilidad` (confirmado por investigación de
código real) no acepta un filtro de servicio directamente — solo
`medico_id`/`fecha` — y su respuesta no trae nombre de médico ni
consultorio, únicamente IDs.

Frecuencia de sincronización recomendada: cada 15-30 minutos, o al
arrancar el proceso + manualmente vía `sync()` — NO se construye un
scheduler real en este MVP (mismo criterio ya aplicado a
`ReminderManager`, sección "no sobrediseñar" del prompt 007: primero
flujo completo funcional, después se automatiza la periodicidad).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .hrmm_http import HttpClient


class CatalogSyncError(Exception):
    pass


@dataclass
class ServicioCatalogo:
    servicio_id: str
    nombre: str


@dataclass
class MedicoCatalogo:
    medico_id: str
    nombre_completo: str
    servicio_id: str
    consultorio: Optional[str] = None


class CatalogMirror:
    def __init__(self) -> None:
        self._servicios: Dict[str, ServicioCatalogo] = {}
        self._medicos: Dict[str, MedicoCatalogo] = {}
        self._lock = threading.Lock()

    def sync(self, http_client: HttpClient) -> None:
        """Determinista: reemplaza el espejo completo con lo que
        devuelva hrmm-backend en este momento — nunca combina ni
        "recuerda" catálogo viejo mezclado con el nuevo."""
        respuesta_servicios = http_client.request("GET", "/api/agenda/servicios")
        respuesta_medicos = http_client.request("GET", "/api/agenda/medicos")
        if respuesta_servicios.status != 200 or respuesta_medicos.status != 200:
            raise CatalogSyncError(
                f"fallo al sincronizar catálogo (servicios={respuesta_servicios.status}, "
                f"medicos={respuesta_medicos.status})"
            )

        nuevos_servicios = {
            s["servicio_id"]: ServicioCatalogo(servicio_id=s["servicio_id"], nombre=s["nombre"])
            for s in respuesta_servicios.body
        }
        nuevos_medicos = {
            m["medico_id"]: MedicoCatalogo(
                medico_id=m["medico_id"],
                nombre_completo=m["nombre_completo"],
                servicio_id=m["servicio_id"],
                consultorio=m.get("consultorio"),
            )
            for m in respuesta_medicos.body
        }
        with self._lock:
            self._servicios = nuevos_servicios
            self._medicos = nuevos_medicos

    def servicio_id_por_nombre(self, nombre: str) -> Optional[str]:
        objetivo = nombre.strip().lower()
        for servicio in self._servicios.values():
            if servicio.nombre.strip().lower() == objetivo:
                return servicio.servicio_id
        return None

    def nombre_por_servicio_id(self, servicio_id: str) -> Optional[str]:
        servicio = self._servicios.get(servicio_id)
        return servicio.nombre if servicio else None

    def listar_nombres(self) -> List[str]:
        """Nombres reales de servicio, ordenados — única fuente para
        responder "qué servicios tienen" (recado 027): HealthBrain/
        gateway.py NUNCA deben inventar ni asumir un nombre de servicio,
        solo listar lo que este espejo sincronizó de verdad."""
        return sorted(s.nombre for s in self._servicios.values())

    def medico(self, medico_id: str) -> Optional[MedicoCatalogo]:
        return self._medicos.get(medico_id)

    def is_synced(self) -> bool:
        return bool(self._servicios) or bool(self._medicos)
