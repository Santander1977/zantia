"""
Gestión "en nombre de otro paciente" (recado 013, extensión de R-15):
el titular del canal (ya identificado/verificado) declara que la
gestión es para un beneficiario distinto. HealthBrain detecta la
intención, valida el documento del beneficiario contra
GET /citas/buscar-paciente (009, sin red real — FakeHttpClient) y pide
confirmación explícita antes de que el resto del flujo use el
documento del BENEFICIARIO (nunca el del titular) contra
AppointmentService. Auditoría separada en EventLog (agent.py).

NO se toca: identidad_canal (`domains/health/gateway.py`) ni el
sub-flujo de verificación por código — ambos sin cambios, sin tests
nuevos aquí.
"""
import pytest

from domains.health import MockActivitySource, MockAppointmentService, MockActivityResultSink, ReminderManager
from domains.health.agent import accept_activity, build_health_agent_context, contact_patient, handle_patient_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.models import Activity
from observability.events import EventType

_TITULAR = "TITULAR-001"
_BENEFICIARIO_VALIDO = "BENEF-002"
_BENEFICIARIO_INVALIDO = "BENEF-999"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _generador(citas_por_documento=None):
    citas_por_documento = citas_por_documento or {}
    llamadas_reserva = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento == _BENEFICIARIO_VALIDO:
                return HttpResponse(200, {"nombre_paciente": "Rosa Pérez", "telefono": "3009999999"})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "POST" and path == "/api/agenda/citas":
            llamadas_reserva.append(json_body)
            return HttpResponse(201, {
                "cita_id": "C1", "slot_id": json_body["slot_id"], "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-10", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""), "telefono": json_body.get("telefono", ""),
                "estado": "reservada", "created_at": "x", "updated_at": "x",
            })
        if method == "GET" and path == "/api/agenda/citas/C1":
            # Releído por agent.py:handle_patient_message tras reservar,
            # para programar recordatorios (sin tocar, comportamiento ya
            # existente desde 007).
            documento = llamadas_reserva[-1]["documento_paciente"] if llamadas_reserva else ""
            return HttpResponse(200, {
                "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-10", "hora_inicio": "09:00", "documento_paciente": documento,
                "nombre_paciente": "", "telefono": "", "estado": "reservada",
                "created_at": "x", "updated_at": "x",
            })
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador, llamadas_reserva


@pytest.fixture
def hrmm_context():
    def _build():
        generador, llamadas_reserva = _generador()
        http = FakeHttpClient(generador=generador)
        catalog = CatalogMirror()
        catalog.sync(http)
        service = HrmmAppointmentService(http, catalog)
        source = MockActivitySource()
        activity = source.create(Activity(
            activity_id="ACT-BENEF-1", source_system="IPS-DEMO", objective="Seguimiento",
            patient_reference=_TITULAR, patient_contact={"nombre": "Juan"}, service="medicina general",
        ))
        context = build_health_agent_context(
            activity, source, service, ReminderManager(), MockActivityResultSink()
        )
        accept_activity(context)
        contact_patient(context)  # siembra "esperando_decision" (agent.py, sin tocar)
        return context, llamadas_reserva

    return _build


def test_titular_gestiona_para_si_mismo_sin_cambios(hrmm_context):
    context, llamadas_reserva = hrmm_context()

    handle_patient_message(context, "m1", "sí")
    respuesta = handle_patient_message(context, "m2", "1")

    assert len(llamadas_reserva) == 1
    assert llamadas_reserva[0]["documento_paciente"] == _TITULAR
    assert "confirmado" in respuesta.lower()

    eventos_beneficiario = [
        e for e in context.orchestrator.events.for_conversation(context.activity.activity_id)
        if e.payload.get("evento") == "GESTION_EN_NOMBRE_DE_BENEFICIARIO"
    ]
    assert eventos_beneficiario == []


def test_titular_declara_beneficiario_valido_reserva_usa_su_documento(hrmm_context):
    context, llamadas_reserva = hrmm_context()

    r1 = handle_patient_message(context, "m1", "es para mi mamá")
    assert "documento" in r1.lower()

    r2 = handle_patient_message(context, "m2", _BENEFICIARIO_VALIDO)
    assert "rosa pérez" in r2.lower()
    assert "correcto" in r2.lower()

    r3 = handle_patient_message(context, "m3", "sí")
    assert "opciones disponibles" in r3.lower()

    r4 = handle_patient_message(context, "m4", "1")
    assert "confirmado" in r4.lower()

    assert len(llamadas_reserva) == 1
    assert llamadas_reserva[0]["documento_paciente"] == _BENEFICIARIO_VALIDO
    assert llamadas_reserva[0]["documento_paciente"] != _TITULAR


def test_documento_beneficiario_invalido_no_continua(hrmm_context):
    context, llamadas_reserva = hrmm_context()

    handle_patient_message(context, "m1", "es para mi mamá")
    respuesta = handle_patient_message(context, "m2", _BENEFICIARIO_INVALIDO)

    assert "no encontré" in respuesta.lower()
    estado = context.orchestrator.store.get(context.activity.activity_id)
    assert estado.datos_recopilados.get("etapa") == "esperando_documento_beneficiario"
    assert llamadas_reserva == []


def test_eventlog_registra_gestor_y_beneficiario_por_separado(hrmm_context):
    context, _ = hrmm_context()

    handle_patient_message(context, "m1", "es para mi mamá")
    handle_patient_message(context, "m2", _BENEFICIARIO_VALIDO)
    handle_patient_message(context, "m3", "sí")
    handle_patient_message(context, "m4", "1")

    eventos = [
        e for e in context.orchestrator.events.for_conversation(context.activity.activity_id)
        if e.payload.get("evento") == "GESTION_EN_NOMBRE_DE_BENEFICIARIO"
    ]
    assert len(eventos) == 1
    payload = eventos[0].payload
    assert payload["gestor_documento"] == _TITULAR
    assert payload["beneficiario_documento"] == _BENEFICIARIO_VALIDO
    assert payload["gestor_documento"] != payload["beneficiario_documento"]
    # Type=STATE_TRANSITION, mismo tipo de evento ya usado en agent.py —
    # no se inventó un EventType nuevo (Core, sin tocar).
    assert eventos[0].type == EventType.STATE_TRANSITION


def test_mock_appointment_service_ignora_la_frase_de_beneficiario(monkeypatch):
    """Control: sin `buscar_paciente` (MockAppointmentService), "es para
    mi mamá" no dispara nada nuevo — cero cambio de comportamiento
    (requisito #5)."""
    activity = Activity(
        activity_id="ACT-MOCK-BENEF", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference="PAC-MOCK", patient_contact={"nombre": "Juan"}, service="medicina general",
    )
    source = MockActivitySource()
    activity = source.create(activity)
    context = build_health_agent_context(
        activity, source, MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    accept_activity(context)
    contact_patient(context)

    respuesta = handle_patient_message(context, "m1", "es para mi mamá")
    estado = context.orchestrator.store.get(context.activity.activity_id)
    assert estado.datos_recopilados.get("etapa") != "esperando_documento_beneficiario"
    # Recado 027: la redacción de este fallback de sí/no se varió a
    # propósito (dejó de repetirse literalmente turno tras turno) — la
    # garantía que importa aquí es que sigue siendo la MISMA pregunta
    # cerrada de sí/no, no el texto exacto.
    assert "sí" in respuesta.lower() and "no" in respuesta.lower()
    assert "agendar" in respuesta.lower() or "programar" in respuesta.lower()
