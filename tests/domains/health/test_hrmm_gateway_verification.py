"""
Sub-flujo de verificación por código en `HealthGateway` — contra
`HrmmAppointmentService` con una capa HTTP FALSA (sin red real, sin
secretos reales). Verifica que:
- MockAppointmentService (008) sigue exactamente igual (no declara
  `requires_verification_code`, así que nunca entra a este sub-flujo).
- Cancelar/reprogramar con HrmmAppointmentService SIEMPRE pasan por
  código, nunca ejecutan la acción real sin uno válido.
"""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse

_CITA_BASE = {
    "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
    "fecha": "2026-09-10", "hora_inicio": "09:00", "documento_paciente": "999",
    "nombre_paciente": "Ana", "telefono": "300", "estado": "reservada",
    "created_at": "x", "updated_at": "x",
}


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _generador_basico(citas_por_documento=None, extra=None):
    citas_por_documento = citas_por_documento or {}
    extra = extra or {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "disponible"},
                {"slot_id": "SLOT2", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-11", "hora_inicio": "10:00", "hora_fin": "10:30", "estado": "disponible"},
            ])
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if (method, path) in extra:
            return extra[(method, path)](params, json_body)
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador


@pytest.fixture
def hrmm_gateway():
    def _build(citas_por_documento=None, extra=None):
        http = FakeHttpClient(generador=_generador_basico(citas_por_documento, extra))
        catalog = CatalogMirror()
        catalog.sync(http)
        service = HrmmAppointmentService(http, catalog)
        gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())
        return gateway, http

    return _build


def test_mock_appointment_service_no_entra_al_subflujo_de_codigo(context):
    """Control: con MockAppointmentService (008, sin tocar), cancelar
    sigue funcionando exactamente igual que antes — sin código."""
    from domains.health import accept_activity, contact_patient, handle_patient_message

    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    respuesta = handle_patient_message(context, "m2", "la primera")
    assert "confirmado" in respuesta.lower()

    respuesta_cancelar = handle_patient_message(context, "m3", "cancela mi cita")
    assert "cancel" in respuesta_cancelar.lower()  # se ejecuta directo, sin pedir código


def test_cancelar_con_hrmm_exige_codigo_antes_de_ejecutar(hrmm_gateway):
    def cancelar_ok(params, json_body):
        assert params["documento_paciente"] == "999"
        assert params["codigo"] == "654321"
        return HttpResponse(200, dict(_CITA_BASE, estado="cancelada"))

    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200, {"enviado": True, "correo_parcial": "a***@dominio.com"}
            ),
            ("POST", "/api/agenda/citas/C1/cancelar"): cancelar_ok,
        },
    )

    r1 = handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita por favor")
    assert "código" in r1.lower()
    assert not any(c["method"] == "POST" and c["path"] == "/api/agenda/citas/C1/cancelar" for c in http.llamadas)

    r2 = handle_inbound_message(gateway, "999", "demo", "m2", "654321")
    assert "cancelada" in r2.lower()
    assert any(c["method"] == "POST" and c["path"] == "/api/agenda/citas/C1/cancelar" for c in http.llamadas)
    assert "999" not in gateway._pending_verifications


def test_codigo_invalido_no_ejecuta_la_cancelacion_y_permite_reintentar(hrmm_gateway):
    intentos = {"n": 0}

    def cancelar(params, json_body):
        intentos["n"] += 1
        if params["codigo"] != "654321":
            return HttpResponse(401, {"detail": "codigo invalido"})
        return HttpResponse(200, dict(_CITA_BASE, estado="cancelada"))

    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(200, {"enviado": True}),
            ("POST", "/api/agenda/citas/C1/cancelar"): cancelar,
        },
    )

    handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")
    r_incorrecto = handle_inbound_message(gateway, "999", "demo", "m2", "000000")
    assert "no es válido" in r_incorrecto.lower() or "no válido" in r_incorrecto.lower()
    assert "999" in gateway._pending_verifications  # sigue pendiente, no se perdió el estado

    r_correcto = handle_inbound_message(gateway, "999", "demo", "m3", "654321")
    assert "cancelada" in r_correcto.lower()
    assert intentos["n"] == 2  # un intento fallido + uno exitoso, nunca canceló con el código malo


def test_reprogramar_con_hrmm_ofrece_opciones_antes_del_codigo(hrmm_gateway):
    def reprogramar_ok(params, json_body):
        assert params["nuevo_slot_id"] == "SLOT2"
        assert params["codigo"] == "111222"
        return HttpResponse(200, dict(_CITA_BASE, slot_id="SLOT2", fecha="2026-09-11", hora_inicio="10:00", estado="reprogramada"))

    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(200, {"enviado": True, "correo_parcial": "a***@dominio.com"}),
            ("POST", "/api/agenda/citas/C1/reprogramar"): reprogramar_ok,
        },
    )

    r1 = handle_inbound_message(gateway, "999", "demo", "m1", "quiero reprogramar mi cita")
    assert "opciones" in r1.lower() or "2026-09" in r1

    r2 = handle_inbound_message(gateway, "999", "demo", "m2", "la segunda")
    assert "código" in r2.lower()

    r3 = handle_inbound_message(gateway, "999", "demo", "m3", "111222")
    assert "reprogramada" in r3.lower()


def test_sin_cita_activa_no_ofrece_ni_pide_codigo(hrmm_gateway):
    gateway, http = hrmm_gateway(citas_por_documento={"999": []})
    respuesta = handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")
    assert "no encuentro" in respuesta.lower()
    assert "999" not in gateway._pending_verifications
