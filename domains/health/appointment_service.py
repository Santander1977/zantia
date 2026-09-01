"""
AppointmentService — abstracción de agenda (prompt 007, secciones 11-12).

ZANTIA se comunica solo con esta interfaz; nunca se acopla a una
implementación concreta (prompt 007, sección 39: Mock -> Real API sin
tocar el Brain). La agenda real es el sistema maestro de la cita — este
servicio, incluso el Mock, NUNCA debe convertirse en el dueño de la
verdad de una cita real (prompt 007, sección 2).

`hold_slot()` se omite deliberadamente en este MVP (el propio prompt la
marca como opcional — "si se considera necesario"); `book_appointment`
reserva y `confirm_appointment` confirma como dos pasos explícitos, así
un fallo entre ambos es observable y nunca se declara una cita
confirmada sin que el segundo paso responda con éxito (sección 14).
"""
from __future__ import annotations

import threading
import uuid
from typing import Dict, List, Optional, Protocol

from .models import AppointmentStatus, AvailabilitySlot, Appointment


class AppointmentServiceError(Exception):
    pass


class SlotNotAvailableError(AppointmentServiceError):
    pass


class AppointmentNotFoundError(AppointmentServiceError):
    pass


class AppointmentService(Protocol):
    def get_availability(
        self,
        service: str,
        specialty: Optional[str] = None,
        location: Optional[str] = None,
    ) -> List[AvailabilitySlot]: ...

    def book_appointment(
        self, slot_id: str, patient_reference: str, idempotency_key: str
    ) -> Appointment: ...

    def confirm_appointment(self, appointment_id: str) -> Appointment: ...

    def cancel_appointment(self, appointment_id: str) -> Appointment: ...

    def reschedule_appointment(
        self, appointment_id: str, new_slot_id: str, idempotency_key: str
    ) -> Appointment: ...

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]: ...

    def get_patient_appointments(self, patient_reference: str) -> List[Appointment]:
        """Extensión (agente bidireccional): necesaria para CONSULTAR_CITA
        y para localizar la cita vigente de un paciente que inicia una
        reprogramación/cancelación sin partir de una Activity conocida."""
        ...


class MockAppointmentService:
    """Disponibilidad ficticia pero DINÁMICA (prompt 007, sección 12):
    una estructura de datos real que se consulta y se modifica al
    reservar/cancelar — nunca una respuesta fija del LLM."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: Dict[str, AvailabilitySlot] = {}
        self._appointments: Dict[str, Appointment] = {}
        self._idempotency: Dict[str, str] = {}  # idempotency_key -> appointment_id
        self._seed_fictional_data()

    def _seed_fictional_data(self) -> None:
        datos = [
            ("medicina general", "Profesional A", "Sede Norte", "2026-09-05", "09:00"),
            ("medicina general", "Profesional A", "Sede Norte", "2026-09-05", "10:00"),
            ("medicina general", "Profesional B", "Sede Centro", "2026-09-06", "14:00"),
            ("medicina general", "Profesional B", "Sede Centro", "2026-09-07", "11:00"),
        ]
        for servicio, profesional, sede, fecha, hora in datos:
            slot = AvailabilitySlot(
                slot_id=str(uuid.uuid4()),
                service=servicio,
                professional=profesional,
                location=sede,
                date=fecha,
                time=hora,
            )
            self._slots[slot.slot_id] = slot

    def get_availability(
        self,
        service: str,
        specialty: Optional[str] = None,
        location: Optional[str] = None,
    ) -> List[AvailabilitySlot]:
        return [
            s
            for s in self._slots.values()
            if s.service.lower() == service.lower()
            and (location is None or s.location.lower() == location.lower())
        ]

    def book_appointment(
        self, slot_id: str, patient_reference: str, idempotency_key: str
    ) -> Appointment:
        with self._lock:
            if idempotency_key in self._idempotency:
                return self._appointments[self._idempotency[idempotency_key]]

            slot = self._slots.get(slot_id)
            if slot is None:
                raise SlotNotAvailableError(slot_id)

            appointment = Appointment(
                appointment_id=str(uuid.uuid4()),
                patient_reference=patient_reference,
                service=slot.service,
                professional=slot.professional,
                location=slot.location,
                date=slot.date,
                time=slot.time,
                status=AppointmentStatus.REQUESTED,
            )
            del self._slots[slot_id]  # dinámico: el turno ya no está disponible
            self._appointments[appointment.appointment_id] = appointment
            self._idempotency[idempotency_key] = appointment.appointment_id
            return appointment

    def confirm_appointment(self, appointment_id: str) -> Appointment:
        with self._lock:
            appointment = self._appointments.get(appointment_id)
            if appointment is None:
                raise AppointmentNotFoundError(appointment_id)
            confirmada = appointment.model_copy(update={"status": AppointmentStatus.CONFIRMED})
            self._appointments[appointment_id] = confirmada
            return confirmada

    def cancel_appointment(self, appointment_id: str) -> Appointment:
        with self._lock:
            appointment = self._appointments.get(appointment_id)
            if appointment is None:
                raise AppointmentNotFoundError(appointment_id)
            cancelada = appointment.model_copy(update={"status": AppointmentStatus.CANCELLED})
            self._appointments[appointment_id] = cancelada
            # libera el turno de vuelta a disponibilidad (dinámico)
            slot = AvailabilitySlot(
                slot_id=str(uuid.uuid4()),
                service=appointment.service,
                professional=appointment.professional or "",
                location=appointment.location,
                date=appointment.date,
                time=appointment.time,
            )
            self._slots[slot.slot_id] = slot
            return cancelada

    def reschedule_appointment(
        self, appointment_id: str, new_slot_id: str, idempotency_key: str
    ) -> Appointment:
        with self._lock:
            if idempotency_key in self._idempotency:
                return self._appointments[self._idempotency[idempotency_key]]

            anterior = self._appointments.get(appointment_id)
            if anterior is None:
                raise AppointmentNotFoundError(appointment_id)

        self.cancel_appointment(appointment_id)
        nueva = self.book_appointment(new_slot_id, anterior.patient_reference, idempotency_key)
        confirmada = self.confirm_appointment(nueva.appointment_id)
        with self._lock:
            reprogramada = confirmada.model_copy(update={"status": AppointmentStatus.RESCHEDULED})
            self._appointments[confirmada.appointment_id] = reprogramada
            return reprogramada

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        return self._appointments.get(appointment_id)

    def mark_no_show(self, appointment_id: str) -> Appointment:
        """No forma parte del contrato mínimo del prompt, pero es necesaria
        para simular la señal 'el sistema de agenda informa NO_SHOW'
        (sección 24) sin inventar un mecanismo nuevo."""
        with self._lock:
            appointment = self._appointments.get(appointment_id)
            if appointment is None:
                raise AppointmentNotFoundError(appointment_id)
            actualizada = appointment.model_copy(update={"status": AppointmentStatus.NO_SHOW})
            self._appointments[appointment_id] = actualizada
            return actualizada

    def mark_attended(self, appointment_id: str) -> Appointment:
        with self._lock:
            appointment = self._appointments.get(appointment_id)
            if appointment is None:
                raise AppointmentNotFoundError(appointment_id)
            actualizada = appointment.model_copy(update={"status": AppointmentStatus.ATTENDED})
            self._appointments[appointment_id] = actualizada
            return actualizada

    def get_patient_appointments(self, patient_reference: str) -> List[Appointment]:
        """Extensión aditiva (agente bidireccional) — no cambia el
        comportamiento de ningún método existente."""
        return [a for a in self._appointments.values() if a.patient_reference == patient_reference]
