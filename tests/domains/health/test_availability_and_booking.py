"""Conversación con el paciente, disponibilidad, selección, reserva,
confirmación, fallo de reserva e idempotencia (sección 36).

Actualizado (recado 035): el flujo de selección pasó de un solo bloque
combinado (fecha+hora+consultorio) a 3 etapas separadas —
servicio (ya resuelto en el camino outbound) -> fecha -> horario. Los
tests de este archivo ahora recorren esas etapas explícitamente."""
from domains.health import ManagementStatus, accept_activity, contact_patient, handle_patient_message
from domains.health.tools import BookAppointmentTool, GetAvailabilityTool


def _iniciar_y_aceptar(context):
    accept_activity(context)
    saludo = contact_patient(context)
    assert "te escribimos" in saludo.lower()
    return handle_patient_message(context, "m1", "hola, sí me interesa")


def _hasta_horarios(context):
    """Avanza desde 'sí me interesa' (fechas) hasta que se ofrecen
    HORARIOS reales de la primera fecha — deja la conversación lista
    para elegir un horario y reservar."""
    _iniciar_y_aceptar(context)
    return handle_patient_message(context, "m2", "1")


def test_patient_conversation_starts_with_deterministic_contact(context):
    accept_activity(context)
    mensaje = contact_patient(context)
    assert context.activity.patient_contact["nombre"] in mensaje
    assert context.activity.management_status == ManagementStatus.CONTACTED


def test_availability_query_returns_structured_result(context, services):
    r1 = _iniciar_y_aceptar(context)
    assert "fechas disponibles" in r1.lower()
    estado = context.orchestrator.store.get(context.activity.activity_id)
    slots = estado.resultado_de_herramientas["get_availability"]["slots"]
    assert len(slots) >= 1
    assert all("slot_id" in s and "date" in s and "time" in s for s in slots)


def test_get_availability_tool_read_directly(services):
    tool = GetAvailabilityTool(services["appointment_service"])
    resultado = tool.run({"service": "medicina general"})
    assert resultado.success
    assert len(resultado.data["slots"]) >= 1


def test_paso_de_fecha_lista_solo_fechas_sin_horarios_todavia(context):
    r1 = _iniciar_y_aceptar(context)
    assert "07:00" not in r1 and "09:00" not in r1 and "10:00" not in r1, (
        "el Paso 1 (fechas) no debe mostrar horarios todavía (recado 035)"
    )


def test_paso_de_horario_muestra_horarios_reales_de_la_fecha_elegida(context):
    r2 = _hasta_horarios(context)
    assert "horarios disponibles" in r2.lower()


def test_appointment_selection_and_booking_confirmation(context):
    _hasta_horarios(context)
    r3 = handle_patient_message(context, "m3", "la primera opción por favor")
    assert "confirmado" in r3.lower()
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
    _hasta_horarios(context)
    # Manipulamos el estado para forzar una selección hacia un slot_id
    # inválido (clave `opciones_horario`, recado 035 — antes
    # `opciones_ofrecidas`):
    estado = context.orchestrator.store.get(context.activity.activity_id)
    datos = dict(estado.datos_recopilados)
    datos["opciones_horario"] = ["slot-inexistente"]
    context.orchestrator.store.save(
        estado.model_copy(update={"datos_recopilados": datos}), expected_version=estado.version
    )
    respuesta = handle_patient_message(context, "m3", "la primera")
    assert "confirmad" not in respuesta.lower()
    assert context.activity.management_status != ManagementStatus.APPOINTMENT_CONFIRMED
