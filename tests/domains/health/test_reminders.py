"""ReminderManager: 72h/24h/8h, envío determinista, respuesta del
paciente (sección 36)."""
from domains.health import ReminderType, accept_activity, contact_patient, fire_reminder, handle_patient_message


def _reservar_cita(context):
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    handle_patient_message(context, "m1b", "1")  # elige fecha (recado 035)
    handle_patient_message(context, "m2", "la primera")
    return context.activity.appointment_id


def test_reminders_scheduled_at_72_24_8_hours(context, services):
    appointment_id = _reservar_cita(context)
    recordatorios = services["reminder_manager"].for_appointment(appointment_id)
    tipos = {r.type for r in recordatorios}
    assert tipos == {ReminderType.REMINDER_72H, ReminderType.REMINDER_24H, ReminderType.REMINDER_8H}
    r72 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_72H)
    r24 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_24H)
    r8 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_8H)
    assert r72.scheduled_at < r24.scheduled_at < r8.scheduled_at


def test_reminder_72h_sent_deterministically(context, services):
    appointment_id = _reservar_cita(context)
    r72 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_72H)
    mensaje = fire_reminder(context, r72)
    assert "recordamos" in mensaje.lower()
    assert services["reminder_manager"].get(r72.reminder_id).status.value == "SENT"


def test_reminder_24h_and_8h_sent(context, services):
    appointment_id = _reservar_cita(context)
    r24 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_24H)
    r8 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_8H)
    assert "mañana" in fire_reminder(context, r24).lower()
    assert "hoy" in fire_reminder(context, r8).lower()


def test_reminder_not_resent_twice(context, services):
    appointment_id = _reservar_cita(context)
    r72 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_72H)
    services["reminder_manager"].mark_sent(r72.reminder_id)
    primero = services["reminder_manager"].get(r72.reminder_id)
    services["reminder_manager"].mark_sent(r72.reminder_id)  # reintento
    segundo = services["reminder_manager"].get(r72.reminder_id)
    assert primero.attempt == segundo.attempt == 1  # no se incrementa dos veces


def test_reminder_response_confirms_attendance(context, services):
    from domains.health.agent import handle_reminder_response

    appointment_id = _reservar_cita(context)
    r72 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_72H)
    fire_reminder(context, r72)
    respuesta = handle_reminder_response(context, r72, "m-reminder-1", "sí, confirmo")
    assert "esperamos" in respuesta.lower()
    assert services["reminder_manager"].get(r72.reminder_id).response == "sí, confirmo"
