"""
Recado 096 — hallazgo real de producción (recado 094; chat web y Telegram,
2026-09-28/30): cuando hrmm-backend responde `enviado=false` con "No tenemos
un correo registrado para verificar tu identidad por este canal." (texto
real de `hrmm/backend/app/api/agenda.py`), el wizard quedaba en
`esperando_codigo`. Lo siguiente que el paciente escribía (en la
conversación real, su correo) viajaba a hrmm-backend COMO el código, y el
bot respondía "Ese código no es válido o ya venció" en bucle, sin salida.
En el gate de identidad esto bloqueaba el flujo desde el primer paso.

Ahora: sin código enviado, ningún wizard espera un código; el mensaje dice
explícitamente que no se envió ninguno y ofrece los canales reales del
hospital (`INFORMACION_HOSPITAL`). Datos ficticios, sin red.
"""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.institutional_info import INFORMACION_HOSPITAL

_MENSAJE_REAL_SIN_CORREO = "No tenemos un correo registrado para verificar tu identidad por este canal."
_CORREO_ESCRITO = "correo.ficticio@ejemplo.com"
_DOCUMENTO = "10000096"
_SESION_WEB = "sesion-web-recado-096"
_CITA = {
    "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
    "fecha": "2026-09-30", "hora_inicio": "07:00", "documento_paciente": _DOCUMENTO,
    "nombre_paciente": "Paciente Ficticio", "telefono": "300", "estado": "reservada",
    "created_at": "x", "updated_at": "x",
}


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _gateway(llamadas):
    def generador(method, path, params, json_body, headers):
        llamadas.append((method, path, dict(params or {})))
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "odontologia"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dr. Ficticio", "servicio_id": "S1", "consultorio": "Consultorio 4"}])
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, [_CITA] if params.get("documento_paciente") == _DOCUMENTO else [])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            if params.get("documento") == _DOCUMENTO:
                return HttpResponse(200, {"nombre_paciente": "Paciente Ficticio", "telefono": _SESION_WEB})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": False, "mensaje": _MENSAJE_REAL_SIN_CORREO})
        if method == "POST":
            return HttpResponse(401, {"detail": "Código de verificación inválido o vencido."})
        raise AssertionError(f"no programado: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    return build_health_gateway(
        MockActivitySource(), HrmmAppointmentService(http, catalog), ReminderManager(), MockActivityResultSink()
    )


def _assert_mensaje_claro(respuesta):
    texto = respuesta.lower()
    assert "no te envié ningún código" in texto
    assert INFORMACION_HOSPITAL.telefono_citas in respuesta
    assert "intentarlo de nuevo" not in texto  # "sin correo" es permanente: nunca se sugiere reintentar


def test_cancelar_sin_correo_registrado_no_trata_el_siguiente_mensaje_como_codigo():
    llamadas = []
    gateway = _gateway(llamadas)

    r1 = handle_inbound_message(gateway, _DOCUMENTO, "demo", "m1", "cancelar mi cita")
    _assert_mensaje_claro(r1)
    assert _DOCUMENTO not in gateway._pending_verifications

    r2 = handle_inbound_message(gateway, _DOCUMENTO, "demo", "m2", _CORREO_ESCRITO)
    assert "código no es válido" not in r2.lower()
    assert not any(_CORREO_ESCRITO in str(p) for _, _, p in llamadas), "el correo viajó a hrmm como código"


def test_gate_de_identidad_web_sin_correo_registrado_no_queda_en_bucle():
    llamadas = []
    gateway = _gateway(llamadas)

    handle_inbound_message(gateway, _SESION_WEB, "web", "m1", "hola quiero una cita")
    r2 = handle_inbound_message(gateway, _SESION_WEB, "web", "m2", _DOCUMENTO)
    _assert_mensaje_claro(r2)
    assert _SESION_WEB not in gateway._pending_identity

    r3 = handle_inbound_message(gateway, _SESION_WEB, "web", "m3", _CORREO_ESCRITO)
    assert "código no es válido" not in r3.lower()
    assert not any(_CORREO_ESCRITO in str(p) for _, _, p in llamadas), "el correo viajó a hrmm como código"
