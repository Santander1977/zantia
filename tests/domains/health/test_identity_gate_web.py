"""
Confirma que el mecanismo de identidad de canal persistente (012/014/016)
se activa IGUAL para el canal "web" (WebChannel, recado 078/079) que para
"telegram"/"chatwoot" — mismo mecanismo exacto, el único cambio real fue
agregar "web" a `domains/health/gateway.py:_CANALES_SIN_IDENTIFICADOR_DOCUMENTO`.
Mirror casi literal de `test_identity_gate_telegram.py`, con `sessionId`
en vez de `chat_id` como identificador de canal — la cobertura completa
del wizard en sí ya vive en `test_identity_gate_chatwoot.py`/
`test_identidad_persistente.py`/`test_identidad_olvido.py`, este archivo
NO la repite.

Sin red real — mismo patrón de `FakeHttpClient` que el resto de
`tests/domains/health/test_hrmm_*.py`."""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import EstadoIdentidadCanal, SQLiteIdentidadCanalStore

_SESSION_ID = "1789169744021"
_DOCUMENTO_VALIDO = "123456789"
_CODIGO_VALIDO = "654321"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _generador(citas_por_documento=None):
    citas_por_documento = citas_por_documento or {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento == _DOCUMENTO_VALIDO:
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _SESSION_ID})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "ok", "correo_parcial": "p***@dominio.com"})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            if json_body.get("codigo") == _CODIGO_VALIDO:
                return HttpResponse(200, {"valido": True})
            return HttpResponse(401, {"detail": "codigo invalido o vencido"})
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador


@pytest.fixture
def web_gateway():
    store = SQLiteIdentidadCanalStore(":memory:")
    http = FakeHttpClient(generador=_generador(citas_por_documento={_DOCUMENTO_VALIDO: []}))
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=store,
    )
    return gateway, store


def test_session_id_nuevo_por_web_dispara_el_wizard_completo(web_gateway):
    gateway, store = web_gateway

    r1 = handle_inbound_message(gateway, _SESSION_ID, "web", "m1", "hola quiero una cita")
    assert "documento" in r1.lower()
    assert _SESSION_ID not in gateway._identidad_resuelta

    r2 = handle_inbound_message(gateway, _SESSION_ID, "web", "m2", _DOCUMENTO_VALIDO)
    assert "código" in r2.lower()
    assert store.get(_SESSION_ID).estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION

    r3 = handle_inbound_message(gateway, _SESSION_ID, "web", "m3", _CODIGO_VALIDO)
    assert "confirmé tu identidad" in r3.lower()
    assert gateway._identidad_resuelta[_SESSION_ID] == _DOCUMENTO_VALIDO

    registro = store.get(_SESSION_ID)
    assert registro.estado == EstadoIdentidadCanal.VERIFICADO
    assert registro.documento == _DOCUMENTO_VALIDO


def test_session_id_ya_verificado_no_repite_el_wizard(web_gateway):
    gateway, store = web_gateway
    store.marcar_verificado(_SESSION_ID, _DOCUMENTO_VALIDO)

    respuesta = handle_inbound_message(gateway, _SESSION_ID, "web", "m1", "quiero consultar mi cita")

    assert "documento" not in respuesta.lower()
    assert "no tienes ninguna cita" in respuesta.lower()
    assert gateway._identidad_resuelta[_SESSION_ID] == _DOCUMENTO_VALIDO


def test_dos_session_id_distintos_son_identidades_de_canal_distintas(web_gateway):
    """Mismo criterio documentado en `service/app.py` (comparten UN solo
    `_gateway`/`identity_store` entre canales): dos `sessionId` distintos
    del mismo widget (ej. dos pestañas/dispositivos del mismo paciente,
    o dos pacientes reales) son dos identidades de CANAL independientes
    — cada una con su propio wizard, ninguna se cuela en la otra."""
    gateway, store = web_gateway
    otro_session_id = "1789169799840"

    handle_inbound_message(gateway, _SESSION_ID, "web", "m1", "hola")
    handle_inbound_message(gateway, _SESSION_ID, "web", "m2", _DOCUMENTO_VALIDO)
    handle_inbound_message(gateway, _SESSION_ID, "web", "m3", _CODIGO_VALIDO)
    assert gateway._identidad_resuelta[_SESSION_ID] == _DOCUMENTO_VALIDO

    assert otro_session_id not in gateway._identidad_resuelta
    r1_otro = handle_inbound_message(gateway, otro_session_id, "web", "m4", "hola quiero una cita")
    assert "documento" in r1_otro.lower()
    assert store.get(otro_session_id) is None
