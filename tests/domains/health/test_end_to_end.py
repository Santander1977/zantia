"""
Pruebas end-to-end principales (prompt 007, secciones 31, 32 y 37).

test_happy_path_end_to_end reproduce exactamente el flujo pedido en la
sección 37:

  IPS -> CREATE ACTIVITY -> ZANTIA -> CONTACT -> PATIENT ACCEPTS ->
  QUERY AVAILABILITY -> PATIENT SELECTS -> BOOK -> CONFIRM ->
  SCHEDULE 72h -> SCHEDULE 24h -> SCHEDULE 8h -> PATIENT CONFIRMS ->
  RESULT -> IPS
"""
from domains.health import (
    ActivityResultType,
    ActivityStatus,
    ManagementStatus,
    ReminderType,
    accept_activity,
    contact_patient,
    finalize_and_report,
    fire_reminder,
    handle_patient_message,
)
from domains.health.agent import handle_reminder_response


def test_happy_path_end_to_end(services, activity_factory):
    # IPS -> CREATE ACTIVITY
    activity = services["source"].create(activity_factory("ACT-E2E-1", patient_reference="PAC-MARIA"))
    assert activity.status.value == "PENDING"

    # -> ZANTIA (acepta la Activity)
    from domains.health import build_health_agent_context

    context = build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )
    accept_activity(context)
    assert context.activity.status == ActivityStatus.IN_PROGRESS

    # -> CONTACT
    contact_patient(context)
    assert context.activity.management_status == ManagementStatus.CONTACTED

    # -> PATIENT ACCEPTS -> QUERY AVAILABILITY (fechas, recado 035, PASO 2)
    r1 = handle_patient_message(context, "m1", "hola, sí me interesa")
    assert "fechas disponibles" in r1.lower()
    assert context.activity.management_status == ManagementStatus.ENGAGED

    # -> elige fecha -> horarios reales (recado 035, PASO 3)
    r1b = handle_patient_message(context, "m1b", "1")
    assert "horarios disponibles" in r1b.lower()

    # -> PATIENT SELECTS -> BOOK -> CONFIRM
    r2 = handle_patient_message(context, "m2", "la primera opción")
    assert "confirmado" in r2.lower()
    assert context.activity.management_status == ManagementStatus.APPOINTMENT_CONFIRMED
    appointment_id = context.activity.appointment_id
    assert appointment_id is not None

    # -> SCHEDULE 72h / 24h / 8h (deterministas, no generados por el Brain)
    recordatorios = services["reminder_manager"].for_appointment(appointment_id)
    assert {r.type for r in recordatorios} == {
        ReminderType.REMINDER_72H, ReminderType.REMINDER_24H, ReminderType.REMINDER_8H
    }

    r72 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_72H)
    fire_reminder(context, r72)
    r24 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_24H)
    fire_reminder(context, r24)
    r8 = services["reminder_manager"].by_type(appointment_id, ReminderType.REMINDER_8H)
    fire_reminder(context, r8)
    assert all(
        services["reminder_manager"].get(r.reminder_id).status.value == "SENT"
        for r in (r72, r24, r8)
    )

    # -> PATIENT CONFIRMS
    confirmacion = handle_reminder_response(context, r8, "m3", "sí, confirmo")
    assert "esperamos" in confirmacion.lower()

    # -> RESULT -> IPS
    finalize_and_report(context)
    resultados = services["result_sink"].results_for("ACT-E2E-1")
    assert len(resultados) == 1
    assert resultados[0].result == ActivityResultType.APPOINTMENT_CONFIRMED
    assert resultados[0].appointment_id == appointment_id
    assert context.activity.status == ActivityStatus.COMPLETED


def test_rescheduling_path_end_to_end(services, activity_factory):
    from domains.health import build_health_agent_context

    activity = services["source"].create(activity_factory("ACT-E2E-2"))
    context = build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    handle_patient_message(context, "m1b", "1")  # elige fecha (recado 035)
    handle_patient_message(context, "m2", "la primera opción")
    appointment_id_original = context.activity.appointment_id

    respuesta = handle_patient_message(context, "m3", "no puedo asistir ese día, quiero reprogramar")
    assert "opciones" in respuesta.lower()
    respuesta_final = handle_patient_message(context, "m4", "la segunda opción")
    assert "reprogramado" in respuesta_final.lower()

    assert context.activity.management_status == ManagementStatus.RESCHEDULED
    assert context.activity.appointment_id != appointment_id_original
    assert all(
        r.status.value == "CANCELLED"
        for r in services["reminder_manager"].for_appointment(appointment_id_original)
    )
    assert len(services["reminder_manager"].for_appointment(context.activity.appointment_id)) == 3

    finalize_and_report(context)
    resultados = services["result_sink"].results_for("ACT-E2E-2")
    assert resultados[0].result == ActivityResultType.RESCHEDULED
