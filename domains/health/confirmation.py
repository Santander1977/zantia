"""
ConfirmationTracker — guarda `patient_confirmation_status` por
`appointment_id`, SEPARADO de `AppointmentStatus` (que vive en
`AppointmentService`/`Appointment` y sigue siendo la única fuente de
verdad del estado real de la cita — ni este tracker lo lee ni lo
escribe, ni al revés).
"""
from __future__ import annotations

import threading
from typing import Dict

from .models import PatientConfirmationStatus


class ConfirmationTracker:
    def __init__(self) -> None:
        self._by_appointment: Dict[str, PatientConfirmationStatus] = {}
        self._lock = threading.Lock()

    def get(self, appointment_id: str) -> PatientConfirmationStatus:
        return self._by_appointment.get(appointment_id, PatientConfirmationStatus.SIN_CONFIRMAR)

    def set_confirmed(self, appointment_id: str) -> None:
        with self._lock:
            self._by_appointment[appointment_id] = PatientConfirmationStatus.CONFIRMADO

    def set_declined(self, appointment_id: str) -> None:
        with self._lock:
            self._by_appointment[appointment_id] = PatientConfirmationStatus.RECHAZADO
