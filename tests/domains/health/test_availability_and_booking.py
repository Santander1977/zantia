"""Conversación con el paciente, disponibilidad, selección, reserva,
confirmación, fallo de reserva e idempotencia (sección 36)."""
from domains.health import ManagementStatus, accept_activity, contact_patient, handle_patient_message
from domains.health.tools import BookAppointmentTool, GetAvailabilityTool


def _iniciar_y_aceptar(context):
    accept_activity(context)
    saludo = contact_patient(context)
    assert "te escribimos" in saludo.lower()
    return handle_patient_message(context, "m1", "hola, sí me interesa")


def test_patient_conversation_starts_with_deterministic_contact(context):
    accept_activity(context)
    mensaje = contact_patient(context)
    assert context.activity.patient_contact["nombre"] in mensaje
    assert context.activity.management_status == ManagementStatus.CONTACTED


def test_availability_query_returns_structured_result(context, services):
    r1 = _iniciar_y_aceptar(context)
    assert "opciones disponibles" in r1.lower()
    estado = context.orchestrator.store.get(context.activity.activity_id)
    slots = estado.resultado_de_herramientas["get_availability"]["slots"]
    assert len(slots) >= 1
    assert all("slot_id" in s and "date" in s and "time" in s for s in slots)


def test_get_availability_tool_read_directly(services):
    tool = GetAvailabilityTool(services["appointment_service"])
    resultado = tool.run({"service": "medicina general"})
    assert resultado.success
    assert len(resultado.data["slots"]) >= 1


def test_appointment_selection_and_booking_confirmation(context):
    _iniciar_y_aceptar(context)
    r2 = handle_patient_message(context, "m2", "la primera opción por favor")
    assert "confirmado" in r2.lower()
    assert context.activity.management_status == ManagementStatus.APPOINTMENT_CONFIRMED
    assert context.activity.appointment_id is not None


def test_booking_tool_fails_for_unknown_slot(services):
    tool = BookAppointmentTool(services["appointment_service"])
    resultado = tool.run(
        {"slot_id": "no-existe", "patient_reference": "PAC-X", "idempotency_key": "k1"}
    )
    assert not resultado.success


def test_booking_is_idempotent(services):
    tool = BookAppointmentTool(services["appointment_service"])
    slot = services["appointment_service"].get_availability("medicina general")[0]
    r1 = tool.run({"slot_id": slot.slot_id, "patient_reference": "PAC-X", "idempotency_key": "misma-clave"})
    r2 = tool.run({"slot_id": slot.slot_id, "patient_reference": "PAC-X", "idempotency_key": "misma-clave"})
    assert r1.data == r2.data


def test_booking_does_not_declare_confirmed_without_appointment_service_success(context):
    """Sección 14: si la tool de reserva falla, la respuesta NO debe
    afirmar que la cita quedó confirmada — corrección del Core hecha
    al construir este dominio (ver core/orchestrator.py y recado 007)."""
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    # Manipulamos el estado para forzar una selección hacia un slot_id inválido:
    estado = context.orchestrator.store.get(context.activity.activity_id)
    datos = dict(estado.datos_recopilados)
    datos["opciones_ofrecidas"] = ["slot-inexistente"]
    context.orchestrator.store.save(
        estado.model_copy(update={"datos_recopilados": datos}), expected_version=estado.version
    )
    respuesta = handle_patient_message(context, "m2", "la primera")
    assert "confirmad" not in respuesta.lower()
    assert context.activity.management_status != ManagementStatus.APPOINTMENT_CONFIRMED
