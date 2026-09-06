"""
Confirma el requisito #3 de recado 022: un usuario de Telegram nuevo
pasa por el MISMO wizard de identificación de canal (012/014/016) que
ya existe para ChatwootChannel — sin duplicar ningún mecanismo, el
único cambio real fue agregar "telegram" a
`domains/health/gateway.py:_CANALES_SIN_IDENTIFICADOR_DOCUMENTO`. La
cobertura completa del wizard en sí (documento -> código ->
persistencia -> vencimiento -> olvido) ya vive en
`test_identity_gate_chatwoot.py`/`test_identidad_persistente.py`/
`test_identidad_olvido.py` — este archivo NO la repite, solo prueba
que el mismo mecanismo se activa igual para el canal "telegram".

Sin red real — mismo patrón de FakeHttpClient que el resto de
`tests/domains/health/test_hrmm_*.py`.
"""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import EstadoIdentidadCanal, SQLiteIdentidadCanalStore

_CHAT_ID = "987654321"
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
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _CHAT_ID})
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
def telegram_gateway():
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


def test_chat_id_nuevo_por_telegram_dispara_el_wizard_completo(telegram_gateway):
    gateway, store = telegram_gateway

    r1 = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m1", "hola quiero una cita")
    assert "documento" in r1.lower()
    assert _CHAT_ID not in gateway._identidad_resuelta

    r2 = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m2", _DOCUMENTO_VALIDO)
    assert "código" in r2.lower()
    assert store.get(_CHAT_ID).estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION

    r3 = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m3", _CODIGO_VALIDO)
    assert "confirmé tu identidad" in r3.lower()
    assert gateway._identidad_resuelta[_CHAT_ID] == _DOCUMENTO_VALIDO

    registro = store.get(_CHAT_ID)
    assert registro.estado == EstadoIdentidadCanal.VERIFICADO
    assert registro.documento == _DOCUMENTO_VALIDO


def test_chat_id_ya_verificado_no_repite_el_wizard(telegram_gateway):
    gateway, store = telegram_gateway
    store.marcar_verificado(_CHAT_ID, _DOCUMENTO_VALIDO)

    respuesta = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m1", "quiero consultar mi cita")

    assert "documento" not in respuesta.lower()
    assert "no tienes ninguna cita" in respuesta.lower()
    assert gateway._identidad_resuelta[_CHAT_ID] == _DOCUMENTO_VALIDO
