"""Casos 3, 4 y 5 del prompt 007 (secciones 33-35): declina, solicita
humano, pide información no autorizada — y no-show (sección 24)."""
from domains.health import (
    ManagementStatus,
    accept_activity,
    contact_patient,
    handle_no_show,
    handle_patient_message,
)


def _iniciar(context):
    accept_activity(context)
    contact_patient(context)


def test_patient_declines(context, services):
    _iniciar(context)
    respuesta = handle_patient_message(context, "m1", "no me interesa, gracias")
    assert "entiendo" in respuesta.lower()
    assert context.activity.management_status == ManagementStatus.DECLINED
    assert context.activity.status.value != "CANCELLED"  # declinar no es lo mismo que cancelar una cita


def test_patient_requests_human_escalates(context):
    _iniciar(context)
    respuesta = handle_patient_message(context, "m1", "quiero hablar con un asesor")
    assert "contactamos" not in respuesta.lower()  # nunca promete contacto (lección de Dani, 002)
    assert "te llaman" not in respuesta.lower()
    assert context.activity.management_status == ManagementStatus.ESCALATED


def test_unauthorized_info_request_is_not_invented(context):
    _iniciar(context)
    respuesta = handle_patient_message(context, "m1", "cuál es mi diagnóstico?")
    assert "no puedo darte información" in respuesta.lower() or "no lo tengo disponible" in respuesta.lower()
    # No se inventa ni se escala automáticamente sin que el paciente insista:
    assert context.activity.management_status not in (ManagementStatus.DECLINED, ManagementStatus.ESCALATED)


def test_no_show_registered_without_creating_new_appointment(context, services):
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    handle_patient_message(context, "m2", "la primera")
    appointment_id = context.activity.appointment_id

    handle_no_show(context)

    assert context.activity.management_status == ManagementStatus.NO_SHOW
    assert services["appointment_service"].get_appointment(appointment_id).status.value == "NO_SHOW"
    # sección 24: no se crea automáticamente una cita nueva
    assert context.activity.appointment_id == appointment_id
