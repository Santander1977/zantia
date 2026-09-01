"""
ReminderManager (prompt 007, secciones 17-21).

Programación DETERMINISTA — nunca depende de que el Brain "se acuerde"
de generar un recordatorio. `schedule_for_appointment` calcula los 3
horarios (T-72h, T-24h, T-8h) a partir de la fecha/hora real de la cita
con aritmética de fechas, no con texto generado por un LLM.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .models import Reminder, ReminderStatus, ReminderType

_OFFSETS = {
    ReminderType.REMINDER_72H: timedelta(hours=72),
    ReminderType.REMINDER_24H: timedelta(hours=24),
    ReminderType.REMINDER_8H: timedelta(hours=8),
}

# Plantillas deterministas — no generadas por el Brain (sección 17).
_TEMPLATES = {
    ReminderType.REMINDER_72H: (
        "Te recordamos tu cita de {service} el {date} a las {time} en {location}. "
        "¿La confirmas o necesitas reprogramar?"
    ),
    ReminderType.REMINDER_24H: (
        "Mañana tienes tu cita de {service} a las {time} en {location}. "
        "¿Confirmas tu asistencia?"
    ),
    ReminderType.REMINDER_8H: (
        "Recordatorio: hoy a las {time} tienes tu cita de {service} en {location}."
    ),
}


class ReminderManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: Dict[str, Reminder] = {}
        self._by_appointment: Dict[str, List[str]] = {}

    def schedule_for_appointment(
        self, activity_id: str, appointment_id: str, appointment_datetime: datetime
    ) -> List[Reminder]:
        creados = []
        with self._lock:
            for tipo, offset in _OFFSETS.items():
                reminder = Reminder(
                    reminder_id=str(uuid.uuid4()),
                    appointment_id=appointment_id,
                    activity_id=activity_id,
                    type=tipo,
                    scheduled_at=appointment_datetime - offset,
                )
                self._by_id[reminder.reminder_id] = reminder
                self._by_appointment.setdefault(appointment_id, []).append(reminder.reminder_id)
                creados.append(reminder)
        return creados

    def cancel_for_appointment(self, appointment_id: str) -> int:
        """Sección 22: ningún recordatorio de la cita anterior debe
        quedar activo tras una reprogramación o cancelación."""
        cancelados = 0
        with self._lock:
            for reminder_id in self._by_appointment.get(appointment_id, []):
                reminder = self._by_id[reminder_id]
                if reminder.status in (ReminderStatus.SCHEDULED, ReminderStatus.READY):
                    self._by_id[reminder_id] = reminder.model_copy(
                        update={"status": ReminderStatus.CANCELLED}
                    )
                    cancelados += 1
        return cancelados

    def render_message(self, reminder: Reminder, appointment) -> str:
        plantilla = _TEMPLATES[reminder.type]
        return plantilla.format(
            service=appointment.service,
            date=appointment.date,
            time=appointment.time,
            location=appointment.location,
        )

    def mark_sent(self, reminder_id: str) -> Reminder:
        with self._lock:
            reminder = self._by_id[reminder_id]
            if reminder.status == ReminderStatus.SENT:
                return reminder  # idempotente: no se reenvía dos veces (sección 28)
            actualizado = reminder.model_copy(
                update={
                    "status": ReminderStatus.SENT,
                    "sent_at": datetime.now(reminder.scheduled_at.tzinfo),
                    "attempt": reminder.attempt + 1,
                }
            )
            self._by_id[reminder_id] = actualizado
            return actualizado

    def mark_responded(self, reminder_id: str, response: str) -> Reminder:
        with self._lock:
            reminder = self._by_id[reminder_id]
            actualizado = reminder.model_copy(
                update={"status": ReminderStatus.RESPONDED, "response": response}
            )
            self._by_id[reminder_id] = actualizado
            return actualizado

    def get(self, reminder_id: str) -> Optional[Reminder]:
        return self._by_id.get(reminder_id)

    def for_appointment(self, appointment_id: str) -> List[Reminder]:
        return [self._by_id[rid] for rid in self._by_appointment.get(appointment_id, [])]

    def by_type(self, appointment_id: str, tipo: ReminderType) -> Optional[Reminder]:
        for reminder in self.for_appointment(appointment_id):
            if reminder.type == tipo:
                return reminder
        return None
