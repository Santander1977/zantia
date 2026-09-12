"""
Recado 081 — hallazgo real de producción (documento 72302972, conversación
real vía `WebChannel`, 2026-09-11): `hrmm-backend` puede responder HTTP 200 a
`POST /api/agenda/verificacion/enviar` con `{"enviado": false, "mensaje": "..."}`
— nunca lanza un error HTTP para este caso (confirmado con una llamada real
contra producción: el límite de tasa documentado en `.ai/RISKS.md` R-8, 3
envíos/300s, agotado por el volumen de pruebas del día). Antes de este fix,
los 3 puntos que llaman `send_verification_code` (`_enviar_codigo_y_pausar`,
`_reenviar_codigo`, `_iniciar_verificacion_de_identidad`, todos en
`gateway.py`) ignoraban ese campo y confirmaban SIEMPRE "Listo, te enviamos un
código..." — una promesa falsa que dejaba al paciente creyendo tener un
código en camino cuando `hrmm-backend` nunca lo mandó.

Cubre los 3 puntos con `enviado=False` (mensaje real de `hrmm-backend`, y el
fallback genérico honesto cuando ni siquiera eso viene) y confirma que
`enviado=True` sigue produciendo exactamente el mismo texto que antes de este
fix — sin regresión. Sin red real, mismo patrón `FakeHttpClient` que el resto
de `tests/domains/health/test_hrmm_*.py`.
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

_SESSION_ID = "prueba-recado-081"
_DOCUMENTO_VALIDO = "72302972"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _generador_basico(citas_por_documento=None, extra=None, buscar_paciente=None):
    citas_por_documento = citas_por_documento or {}
    extra = extra or {}
    buscar_paciente = buscar_paciente or {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento in buscar_paciente:
                return HttpResponse(200, buscar_paciente[documento])
            return HttpResponse(404, {"detail": "no encontrado"})
        if (method, path) in extra:
            return extra[(method, path)](params, json_body)
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador


@pytest.fixture
def hrmm_gateway():
    def _build(citas_por_documento=None, extra=None, buscar_paciente=None):
        http = FakeHttpClient(generador=_generador_basico(citas_por_documento, extra, buscar_paciente))
        catalog = CatalogMirror()
        catalog.sync(http)
        service = HrmmAppointmentService(http, catalog)
        gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())
        return gateway, http

    return _build


# ---------------------------------------------------------------------
# Punto 1: _enviar_codigo_y_pausar (cancelar/reprogramar, primer envío)
# ---------------------------------------------------------------------

def test_cancelar_con_envio_fallido_da_mensaje_honesto_no_confirmacion_falsa(hrmm_gateway):
    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200,
                {
                    "enviado": False,
                    "mensaje": "No pudimos enviar el código — intenta de nuevo en un momento.",
                    "correo_parcial": None,
                },
            ),
        },
    )

    respuesta = handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")

    assert "no pudimos enviar el código" in respuesta.lower()
    assert "listo, te enviamos" not in respuesta.lower()
    # El wizard sigue vivo — el paciente puede pedir que se lo reenvíen.
    assert "999" in gateway._pending_verifications


def test_cancelar_con_envio_fallido_sin_mensaje_usa_generico_honesto(hrmm_gateway):
    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(200, {"enviado": False})},
    )

    respuesta = handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")

    assert "no pude enviarte el código en este momento" in respuesta.lower()
    assert "listo, te enviamos" not in respuesta.lower()


def test_cancelar_con_envio_exitoso_sigue_igual_que_antes(hrmm_gateway):
    """Control anti-regresión explícito (recado 081): `enviado=True`
    produce EXACTAMENTE el mismo texto que antes de este fix."""
    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200, {"enviado": True, "correo_parcial": "a***@dominio.com"}
            ),
        },
    )

    respuesta = handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")

    assert (
        "Listo, te enviamos un código a tu correo (a***@dominio.com) para confirmar. "
        "Escríbelo aquí para continuar cuando lo tengas."
    ) in respuesta


# ---------------------------------------------------------------------
# Punto 2: _reenviar_codigo
# ---------------------------------------------------------------------

def test_reenviar_codigo_con_envio_fallido_da_mensaje_honesto(hrmm_gateway):
    intentos_envio = {"n": 0}

    def enviar(p, j):
        intentos_envio["n"] += 1
        if intentos_envio["n"] == 1:
            return HttpResponse(200, {"enviado": True, "correo_parcial": "a***@dominio.com"})
        return HttpResponse(200, {"enviado": False, "mensaje": "Límite de envíos alcanzado, intenta más tarde."})

    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={("POST", "/api/agenda/verificacion/enviar"): enviar},
    )

    handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")
    respuesta = handle_inbound_message(gateway, "999", "demo", "m2", "reenviarme otro")

    assert "límite de envíos alcanzado" in respuesta.lower()
    assert "listo, te reenviamos" not in respuesta.lower()
    assert "999" in gateway._pending_verifications  # no se pierde el estado


def test_reenviar_codigo_con_envio_exitoso_sigue_igual_que_antes(hrmm_gateway):
    gateway, http = hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200, {"enviado": True, "correo_parcial": "a***@dominio.com"}
            ),
        },
    )

    handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")
    respuesta = handle_inbound_message(gateway, "999", "demo", "m2", "reenviarme otro")

    assert respuesta == (
        "Listo, te reenviamos un código nuevo a tu correo (a***@dominio.com). "
        "Escríbelo aquí cuando lo tengas."
    )


# ---------------------------------------------------------------------
# Punto 3: _iniciar_verificacion_de_identidad (gate de identidad de canal)
# ---------------------------------------------------------------------

def test_gate_de_identidad_con_envio_fallido_da_mensaje_honesto(hrmm_gateway):
    gateway, http = hrmm_gateway(
        citas_por_documento={_DOCUMENTO_VALIDO: []},
        buscar_paciente={_DOCUMENTO_VALIDO: {"nombre_paciente": "Paciente de Prueba", "telefono": _SESSION_ID}},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200,
                {
                    "enviado": False,
                    "mensaje": "No pudimos enviar el código — intenta de nuevo en un momento.",
                    "correo_parcial": None,
                },
            ),
        },
    )

    handle_inbound_message(gateway, _SESSION_ID, "web", "m1", "hola quiero una cita")
    respuesta = handle_inbound_message(gateway, _SESSION_ID, "web", "m2", _DOCUMENTO_VALIDO)

    assert "no pudimos enviar el código" in respuesta.lower()
    assert "listo, te enviamos" not in respuesta.lower()
    # El documento ya quedó validado contra buscar-paciente — el paciente no
    # tiene que repetirlo, solo puede reintentar que le manden el código.
    assert _SESSION_ID in gateway._pending_identity


def test_gate_de_identidad_con_envio_exitoso_sigue_igual_que_antes(hrmm_gateway):
    gateway, http = hrmm_gateway(
        citas_por_documento={_DOCUMENTO_VALIDO: []},
        buscar_paciente={_DOCUMENTO_VALIDO: {"nombre_paciente": "Paciente de Prueba", "telefono": _SESSION_ID}},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200, {"enviado": True, "correo_parcial": "p***@dominio.com"}
            ),
        },
    )

    handle_inbound_message(gateway, _SESSION_ID, "web", "m1", "hola quiero una cita")
    respuesta = handle_inbound_message(gateway, _SESSION_ID, "web", "m2", _DOCUMENTO_VALIDO)

    assert respuesta == (
        "Listo, te enviamos un código a tu correo (p***@dominio.com) para confirmar tu identidad. "
        "Escríbelo aquí cuando lo tengas."
    )
