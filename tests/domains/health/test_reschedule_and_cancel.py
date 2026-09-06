"""Reprogramación, cancelación, y cancelación de recordatorios tras
reprogramar (sección 36, secciones 22-23 del prompt)."""
from domains.health import (
    AppointmentStatus,
    ManagementStatus,
    ActivityStatus,
    accept_activity,
    contact_patient,
    handle_patient_message,
)


def _reservar_cita(context):
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    handle_patient_message(context, "m1b", "1")  # elige fecha (recado 035)
    handle_patient_message(context, "m2", "la primera")
    return context.activity.appointment_id


def test_reschedule_flow(context, services):
    appointment_id_original = _reservar_cita(context)
    handle_patient_message(context, "m3", "no puedo asistir ese día, quiero reprogramar")
    respuesta = handle_patient_message(context, "m4", "la segunda opción")

    assert "reprogramado" in respuesta.lower()
    assert context.activity.management_status == ManagementStatus.RESCHEDULED
    assert context.activity.appointment_id != appointment_id_original

    cita_original = services["appointment_service"].get_appointment(appointment_id_original)
    assert cita_original.status == AppointmentStatus.CANCELLED


def test_reminders_cancelled_after_reschedule(context, services):
    appointment_id_original = _reservar_cita(context)
    handle_patient_message(context, "m3", "quiero reprogramar")
    handle_patient_message(context, "m4", "la segunda opción")

    recordatorios_originales = services["reminder_manager"].for_appointment(appointment_id_original)
    assert all(r.status.value == "CANCELLED" for r in recordatorios_originales)

    recordatorios_nuevos = services["reminder_manager"].for_appointment(context.activity.appointment_id)
    assert all(r.status.value == "SCHEDULED" for r in recordatorios_nuevos)
    assert len(recordatorios_nuevos) == 3


def test_cancellation_flow(context, services):
    appointment_id = _reservar_cita(context)
    handle_patient_message(context, "m3", "cancela mi cita por favor")

    assert context.activity.status == ActivityStatus.CANCELLED
    cita = services["appointment_service"].get_appointment(appointment_id)
    assert cita.status == AppointmentStatus.CANCELLED
    recordatorios = services["reminder_manager"].for_appointment(appointment_id)
    assert all(r.status.value == "CANCELLED" for r in recordatorios)
