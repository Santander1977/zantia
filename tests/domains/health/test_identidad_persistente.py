"""
Persistencia de identidad de canal ENTRE conversaciones (recado 014,
extensión de R-15): `domains/health/identity_store.py` +
requisito #3 del pedido — un teléfono ya VERIFICADO se reconoce de
inmediato en un contacto siguiente, sin repetir el wizard de
documento/código. El wizard en sí (pedir documento -> validar ->
verificar código) está cubierto en `test_identity_gate_chatwoot.py`;
este archivo cubre específicamente el store nuevo y la hidratación
entre "conversaciones"/"procesos" distintos.

Sin red real — mismo patrón de FakeHttpClient que el resto de
`tests/domains/health/test_hrmm_*.py`.
"""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import (
    EstadoIdentidadCanal,
    SQLiteIdentidadCanalStore,
    build_identity_store,
)

_TELEFONO = "573001112233"
_DOCUMENTO_VALIDO = "123456789"


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
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "ok", "correo_parcial": "p***@dominio.com"})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            if json_body.get("codigo") == "654321":
                return HttpResponse(200, {"valido": True})
            return HttpResponse(401, {"detail": "codigo invalido o vencido"})
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador


def _build_gateway(identity_store, citas_por_documento=None):
    http = FakeHttpClient(generador=_generador(citas_por_documento))
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    return build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )


# ---------------------------------------------------------------------
# Smoke test del store en sí (regla obligatoria de testing.md: todo
# componente nuevo nace con al menos un smoke test).
# ---------------------------------------------------------------------
def test_sqlite_identidad_canal_store_smoke():
    store = SQLiteIdentidadCanalStore(":memory:")
    assert store.get(_TELEFONO) is None

    pendiente = store.guardar_pendiente(_TELEFONO, _DOCUMENTO_VALIDO)
    assert pendiente.estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION
    assert pendiente.verificado_en is None
    assert store.get(_TELEFONO).estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION

    verificado = store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
    assert verificado.estado == EstadoIdentidadCanal.VERIFICADO
    assert verificado.verificado_en is not None
    registro = store.get(_TELEFONO)
    assert registro.estado == EstadoIdentidadCanal.VERIFICADO
    assert registro.documento == _DOCUMENTO_VALIDO
    assert registro.verificado_en is not None


def test_build_identity_store_usa_env_var_o_cae_a_memoria(monkeypatch, tmp_path):
    monkeypatch.delenv("ZANTIA_IDENTIDAD_DB_PATH", raising=False)
    store_memoria = build_identity_store()
    assert store_memoria._db_path == ":memory:"

    ruta = str(tmp_path / "identidad.db")
    monkeypatch.setenv("ZANTIA_IDENTIDAD_DB_PATH", ruta)
    store_archivo = build_identity_store()
    assert store_archivo._db_path == ruta
    # Sobrevive un "reinicio" real: nueva instancia, mismo archivo.
    store_archivo.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
    store_archivo.close()
    reabierto = build_identity_store()
    assert reabierto.get(_TELEFONO).estado == EstadoIdentidadCanal.VERIFICADO


# ---------------------------------------------------------------------
# Hidratación en handle_inbound_message (requisito #3 del pedido).
# ---------------------------------------------------------------------
def test_contacto_siguiente_con_identidad_verificada_no_pide_nada():
    store = SQLiteIdentidadCanalStore(":memory:")
    store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)

    # Gateway "nuevo" (simula un proceso recién levantado) que solo
    # comparte el store persistente, nunca el estado en memoria.
    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    assert _TELEFONO not in gateway._identidad_resuelta  # nada en memoria todavía

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "quiero consultar mi cita")

    assert "documento" not in respuesta.lower()
    assert "código" not in respuesta.lower()
    assert "no tienes ninguna cita" in respuesta.lower()
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO
    assert _TELEFONO not in gateway._pending_identity


def test_dos_gateways_distintos_comparten_identidad_via_store(tmp_path, monkeypatch):
    """Simula dos "procesos" (dos instancias de HealthGateway) contra el
    MISMO archivo SQLite — la identidad verificada en el primero debe
    reconocerse en el segundo sin repetir el wizard."""
    ruta = str(tmp_path / "identidad.db")
    monkeypatch.setenv("ZANTIA_IDENTIDAD_DB_PATH", ruta)

    proceso_1 = _build_gateway(build_identity_store(), citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(proceso_1, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")
    handle_inbound_message(proceso_1, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    respuesta_codigo = handle_inbound_message(proceso_1, _TELEFONO, "chatwoot", "m3", "654321")
    assert "confirmé tu identidad" in respuesta_codigo.lower()

    # "Reinicio del proceso": store nuevo apuntando al mismo archivo,
    # gateway nuevo, CERO estado en memoria compartido con proceso_1.
    proceso_2 = _build_gateway(build_identity_store(), citas_por_documento={_DOCUMENTO_VALIDO: []})
    respuesta_final = handle_inbound_message(proceso_2, _TELEFONO, "chatwoot", "m4", "quiero consultar mi cita")

    assert "documento" not in respuesta_final.lower()
    assert "no tienes ninguna cita" in respuesta_final.lower()
    assert proceso_2._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO


def test_identidad_pendiente_no_verificada_no_se_reconoce():
    """Una fila PENDIENTE_VERIFICACION (wizard interrumpido antes del
    código) nunca se trata como confiable — solo VERIFICADO hidrata
    `_identidad_resuelta`."""
    store = SQLiteIdentidadCanalStore(":memory:")
    store.guardar_pendiente(_TELEFONO, _DOCUMENTO_VALIDO)

    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")

    assert "documento" in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta
