"""
Evolución bidireccional del dominio salud — HealthGateway (correlación
+ PatientRequest). Extiende la suite de demanda inducida (007) sin
tocar sus 29 tests ni sus fixtures existentes.
"""
from unittest.mock import patch

from domains.health import (
    Activity,
    AppointmentStatus,
    PatientConfirmationStatus,
    ReminderType,
    RequestIntent,
    accept_activity,
    contact_patient,
    fire_reminder,
    handle_inbound_message,
    start_activity_and_register,
)
from domains.health.agent import build_health_agent_context, handle_patient_message, handle_reminder_response
from domains.health.brain import HealthBrain
from domains.health.gateway import build_health_gateway, find_open_context


# ---------------------------------------------------------------------
# 1. Correlación: mensaje inbound de un identificador con Activity
#    outbound ya en curso -> se enruta ahí, NUNCA crea PatientRequest.
# ---------------------------------------------------------------------
def test_correlacion_enruta_a_activity_outbound_existente(gateway, activity_factory):
    activity = activity_factory("ACT-CORR-1", patient_reference="PAC-CORR-1")
    start_activity_and_register(gateway, activity)

    assert find_open_context(gateway, "PAC-CORR-1") is not None

    respuesta = handle_inbound_message(gateway, "PAC-CORR-1", "demo", "m1", "sí, me interesa")

    assert "fechas disponibles" in respuesta.lower()
    # NUNCA se crea una PatientRequest para esto (sección de correlación):
    assert gateway.patient_request_source.list_for_patient("PAC-CORR-1") == []


# ---------------------------------------------------------------------
# 2. PatientRequest genuina: identificador sin conversación previa ->
#    se crea una PatientRequest nueva, correctamente clasificada.
# ---------------------------------------------------------------------
def test_patient_request_genuina_se_crea_y_clasifica(gateway):
    handle_inbound_message(gateway, "PAC-CORR-2", "demo", "m1", "hola, quiero agendar una cita")

    requests = gateway.patient_request_source.list_for_patient("PAC-CORR-2")
    assert len(requests) == 1
    assert requests[0].intent == RequestIntent.PROGRAMAR_CITA
    assert requests[0].patient_reference == "PAC-CORR-2"


# ---------------------------------------------------------------------
# 3. Flujo completo PROGRAMAR_CITA 100% iniciado por el paciente.
# ---------------------------------------------------------------------
def test_programar_cita_completa_iniciada_por_el_paciente(gateway, services):
    r1 = handle_inbound_message(gateway, "PAC-CORR-3", "demo", "m1", "quiero agendar una cita")
    assert "fechas disponibles" in r1.lower()

    r1b = handle_inbound_message(gateway, "PAC-CORR-3", "demo", "m1b", "1")  # elige fecha (recado 035)
    assert "horarios disponibles" in r1b.lower()

    r2 = handle_inbound_message(gateway, "PAC-CORR-3", "demo", "m2", "la primera opción")
    assert "confirmado" in r2.lower()

    citas = services["appointment_service"].get_patient_appointments("PAC-CORR-3")
    assert len(citas) == 1
    assert citas[0].status == AppointmentStatus.CONFIRMED

    # ReminderPlan creado (reutiliza ReminderManager ya existente, sin tocar):
    recordatorios = services["reminder_manager"].for_appointment(citas[0].appointment_id)
    assert {r.type for r in recordatorios} == {
        ReminderType.REMINDER_72H, ReminderType.REMINDER_24H, ReminderType.REMINDER_8H
    }


# ---------------------------------------------------------------------
# 4. CONSULTAR_CITA: la información viene de AppointmentService, nunca
#    de una agenda paralela inventada.
# ---------------------------------------------------------------------
def test_consultar_cita_usa_appointment_service_como_fuente_real(gateway, services):
    handle_inbound_message(gateway, "PAC-CORR-4", "demo", "m1", "quiero agendar una cita")
    handle_inbound_message(gateway, "PAC-CORR-4", "demo", "m1b", "1")  # elige fecha (recado 035)
    handle_inbound_message(gateway, "PAC-CORR-4", "demo", "m2", "la primera")

    cita_real = services["appointment_service"].get_patient_appointments("PAC-CORR-4")[0]

    respuesta = handle_inbound_message(gateway, "PAC-CORR-4", "demo", "m3", "cuándo es mi cita?")

    assert cita_real.date in respuesta
    assert cita_real.time in respuesta
    assert cita_real.location in respuesta


def test_consultar_cita_sin_citas_no_inventa_nada(gateway):
    respuesta = handle_inbound_message(gateway, "PAC-CORR-4B", "demo", "m1", "cuándo es mi cita?")
    assert "no tienes ninguna cita" in respuesta.lower()


# ---------------------------------------------------------------------
# 5. Reutilización explícita: reprogramar desde una respuesta a
#    recordatorio y reprogramar desde una PatientRequest inbound nueva
#    deben pasar por la MISMA función (HealthBrain._iniciar_reprogramacion),
#    no por una copia.
# ---------------------------------------------------------------------
def test_reprogramacion_inbound_fresca_dispara_iniciar_reprogramacion(gateway):
    """Confirma, de forma aislada, que el camino de reprogramación 100%
    inbound (sin conversación previa) sí llega al método real de
    HealthBrain — antes de compararlo contra el camino del recordatorio
    en el siguiente test."""
    original = HealthBrain._iniciar_reprogramacion
    with patch.object(HealthBrain, "_iniciar_reprogramacion", autospec=True, side_effect=original) as espia:
        handle_inbound_message(gateway, "PAC-CORR-5B", "demo", "m1", "quiero agendar una cita")
        handle_inbound_message(gateway, "PAC-CORR-5B", "demo", "m1b", "1")  # elige fecha (recado 035)
        handle_inbound_message(gateway, "PAC-CORR-5B", "demo", "m2", "la primera")
        respuesta = handle_inbound_message(gateway, "PAC-CORR-5B", "demo", "m3", "quiero reprogramar mi cita")

    assert espia.call_count == 1
    assert "opciones" in respuesta.lower()


def test_reprogramacion_via_recordatorio_y_via_inbound_llaman_al_mismo_metodo(services):
    """Prueba directa y explícita de la regla de no-duplicación (sección
    'Reutilización explícita'): se cuentan las invocaciones de
    `HealthBrain._iniciar_reprogramacion` en AMBOS caminos —
    `handle_reminder_response` (007, sin tocar) y
    `gateway.handle_inbound_message` (nuevo) — sobre el mismo método,
    no sobre una reimplementación paralela."""
    original = HealthBrain._iniciar_reprogramacion
    with patch.object(HealthBrain, "_iniciar_reprogramacion", autospec=True, side_effect=original) as espia:
        # Camino A: reminder -> reprogramación (idéntico al de 007)
        activity = services["source"].create(
            Activity(
                activity_id="ACT-REM-A",
                source_system="IPS-DEMO",
                objective="x",
                patient_reference="PAC-REM-A",
                patient_contact={"nombre": "Demo"},
                service="medicina general",
            )
        )
        contexto = build_health_agent_context(
            activity, services["source"], services["appointment_service"],
            services["reminder_manager"], services["result_sink"],
        )
        accept_activity(contexto)
        contact_patient(contexto)

        handle_patient_message(contexto, "m1", "sí, me interesa")
        handle_patient_message(contexto, "m1b", "1")  # elige fecha (recado 035)
        handle_patient_message(contexto, "m2", "la primera")
        appointment_id = contexto.activity.appointment_id
        recordatorio = services["reminder_manager"].for_appointment(appointment_id)[0]
        fire_reminder(contexto, recordatorio)
        handle_reminder_response(contexto, recordatorio, "m3", "no puedo asistir, quiero reprogramar")

        llamadas_tras_camino_a = espia.call_count
        assert llamadas_tras_camino_a == 1

        # Camino B: PatientRequest inbound -> reprogramación (nuevo, vía gateway)
        gw = build_health_gateway(
            services["source"], services["appointment_service"],
            services["reminder_manager"], services["result_sink"],
        )
        handle_inbound_message(gw, "PAC-REM-B", "demo", "m1", "quiero agendar una cita")
        handle_inbound_message(gw, "PAC-REM-B", "demo", "m1b", "1")  # elige fecha (recado 035)
        handle_inbound_message(gw, "PAC-REM-B", "demo", "m2", "la primera")
        handle_inbound_message(gw, "PAC-REM-B", "demo", "m3", "quiero reprogramar mi cita")

        assert espia.call_count == llamadas_tras_camino_a + 1  # el MISMO método, una vez más


# ---------------------------------------------------------------------
# 6. CONFIRMAR_CITA: patient_confirmation_status y appointment_status
#    quedan separados, ninguno sobreescribe al otro.
# ---------------------------------------------------------------------
def test_confirmar_cita_no_pisa_el_estado_de_la_agenda(gateway, services):
    handle_inbound_message(gateway, "PAC-CORR-6", "demo", "m1", "quiero agendar una cita")
    handle_inbound_message(gateway, "PAC-CORR-6", "demo", "m1b", "1")  # elige fecha (recado 035)
    handle_inbound_message(gateway, "PAC-CORR-6", "demo", "m2", "la primera")
    appointment_id = services["appointment_service"].get_patient_appointments("PAC-CORR-6")[0].appointment_id

    estado_agenda_antes = services["appointment_service"].get_appointment(appointment_id).status
    assert gateway.confirmation_tracker.get(appointment_id) == PatientConfirmationStatus.SIN_CONFIRMAR

    handle_inbound_message(gateway, "PAC-CORR-6", "demo", "m3", "confirmo mi cita")

    estado_agenda_despues = services["appointment_service"].get_appointment(appointment_id).status
    assert estado_agenda_despues == estado_agenda_antes  # la agenda es la única fuente de verdad, no cambió
    assert gateway.confirmation_tracker.get(appointment_id) == PatientConfirmationStatus.CONFIRMADO
