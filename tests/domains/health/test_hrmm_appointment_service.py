"""
HrmmAppointmentService — tests contra una capa HTTP FALSA
(`FakeHttpClient`), sin red real ni secretos (petición explícita del
usuario para esta fase: "todavía no ejecutar pruebas de red real").
Contrato de endpoints verificado leyendo el código real de
hrmm-backend (ver docstring de `hrmm_appointment_service.py`).
"""
import os

import pytest

from domains.health.appointment_service import AppointmentServiceError
from domains.health.hrmm_appointment_service import HrmmAppointmentService, VerificationRequiredError
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse

_CITA_BASE = {
    "cita_id": "C1",
    "slot_id": "SLOT1",
    "medico_id": "M1",
    "servicio_id": "S1",
    "fecha": "2026-09-10",
    "hora_inicio": "09:00",
    "documento_paciente": "123456",
    "nombre_paciente": "Juan",
    "telefono": "3000000000",
    "estado": "reservada",
    "created_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-01T00:00:00Z",
}


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


@pytest.fixture
def http():
    cliente = FakeHttpClient()
    cliente.programar("GET", "/api/agenda/servicios", HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}]))
    cliente.programar(
        "GET", "/api/agenda/medicos",
        HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}]),
    )
    return cliente


@pytest.fixture
def catalog(http):
    mirror = CatalogMirror()
    mirror.sync(http)
    return mirror


@pytest.fixture
def service(http, catalog):
    return HrmmAppointmentService(http, catalog)


def test_catalog_sync_puebla_el_espejo(catalog):
    assert catalog.is_synced()
    assert catalog.servicio_id_por_nombre("medicina general") == "S1"
    assert catalog.nombre_por_servicio_id("S1") == "medicina general"
    assert catalog.medico("M1").consultorio == "Consultorio 3"


def test_list_services_devuelve_catalogo_real_sincronizado(service):
    """Recado 027 — `list_services()` (duck-typed, mismo criterio que
    `buscar_paciente`) nunca inventa nombres: solo lo que `CatalogMirror`
    ya sincronizó de `GET /api/agenda/servicios`."""
    assert service.list_services() == ["medicina general"]


def test_list_services_vacio_si_el_catalogo_no_sincronizo():
    catalog_sin_sincronizar = CatalogMirror()
    http = FakeHttpClient()
    service_sin_sync = HrmmAppointmentService(http, catalog_sin_sincronizar)
    assert service_sin_sync.list_services() == []


def test_get_availability_traduce_ids_del_catalogo(http, service):
    http.programar(
        "GET", "/api/agenda/disponibilidad",
        HttpResponse(200, [
            {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"}
        ]),
    )
    slots = service.get_availability("medicina general")
    assert len(slots) == 1
    assert slots[0].professional == "Dra. Ana Pérez"
    assert slots[0].location == "Consultorio 3"


def test_get_availability_servicio_desconocido_no_inventa_nada(service):
    """HealthBrain no debe inventar catálogos — si el nombre no está en
    el espejo sincronizado, no hay disponibilidad que ofrecer."""
    assert service.get_availability("servicio que no existe") == []


def test_get_availability_excluye_bloques_ocupados(http, service):
    http.programar(
        "GET", "/api/agenda/disponibilidad",
        HttpResponse(200, [
            {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Reservado"},
            {"slot_id": "SLOT2", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "10:00", "hora_fin": "10:30", "estado": "Libre"},
        ]),
    )
    slots = service.get_availability("medicina general")
    assert [s.slot_id for s in slots] == ["SLOT2"]


def test_get_availability_excluye_estado_no_contemplado(http, service):
    """Allowlist explícito (recado 010): un valor de `estado` que no es
    "Libre" se excluye por defecto, conservador, aunque no coincida con
    ningún valor conocido — nunca se ofrece un slot por error."""
    http.programar(
        "GET", "/api/agenda/disponibilidad",
        HttpResponse(200, [
            {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Bloqueado"},
            {"slot_id": "SLOT2", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "10:00", "hora_fin": "10:30", "estado": "Libre"},
        ]),
    )
    slots = service.get_availability("medicina general")
    assert [s.slot_id for s in slots] == ["SLOT2"]


def test_book_appointment_exitoso(http, service):
    http.programar("GET", "/api/agenda/disponibilidad", HttpResponse(200, [
        {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"}
    ]))
    http.programar("GET", "/api/agenda/citas", HttpResponse(200, []))
    http.programar("POST", "/api/agenda/citas", HttpResponse(201, _CITA_BASE))

    service.get_availability("medicina general")  # puebla el cache de slots crudos
    service.register_patient_contact("123456", "Juan", "3000000000")
    cita = service.book_appointment("SLOT1", "123456", "idem-1")

    assert cita.appointment_id == "C1"
    assert cita.service == "medicina general"  # nombre legible, no el servicio_id crudo


def test_book_appointment_idempotente_por_clave(http, service):
    http.programar("GET", "/api/agenda/disponibilidad", HttpResponse(200, [
        {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"}
    ]))
    http.programar("GET", "/api/agenda/citas", HttpResponse(200, []))
    http.programar("POST", "/api/agenda/citas", HttpResponse(201, _CITA_BASE))
    http.programar("GET", "/api/agenda/citas/C1", HttpResponse(200, _CITA_BASE))

    service.get_availability("medicina general")
    service.register_patient_contact("123456", "Juan", "3000000000")
    r1 = service.book_appointment("SLOT1", "123456", "misma-clave")
    r2 = service.book_appointment("SLOT1", "123456", "misma-clave")

    assert r1.appointment_id == r2.appointment_id
    llamadas_post = [c for c in http.llamadas if c["method"] == "POST" and c["path"] == "/api/agenda/citas"]
    assert len(llamadas_post) == 1  # nunca se llamó a crear la cita dos veces


def test_book_appointment_no_duplica_cita_activa_equivalente(http, service):
    """Idempotencia adicional: aunque llegue una idempotency_key
    DISTINTA (p. ej. reintento del sistema IPS con una nueva Activity),
    si ya existe una cita activa del mismo paciente/servicio/fecha, no
    se crea una nueva."""
    http.programar("GET", "/api/agenda/disponibilidad", HttpResponse(200, [
        {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"}
    ]))
    http.programar("GET", "/api/agenda/citas", HttpResponse(200, [_CITA_BASE]))  # ya existe una activa

    service.get_availability("medicina general")
    cita = service.book_appointment("SLOT1", "123456", "idempotency-key-distinta")

    assert cita.appointment_id == "C1"
    llamadas_post = [c for c in http.llamadas if c["method"] == "POST" and c["path"] == "/api/agenda/citas"]
    assert llamadas_post == []  # nunca se intentó crear una cita nueva


def test_cancel_appointment_directo_exige_verificacion(service):
    """El Protocol estándar `cancel_appointment(appointment_id)` no
    lleva documento/codigo — nunca ejecuta una cancelación real sin
    verificación, señaliza con VerificationRequiredError."""
    with pytest.raises(VerificationRequiredError):
        service.cancel_appointment("C1")


def test_reschedule_appointment_directo_exige_verificacion(service):
    with pytest.raises(VerificationRequiredError):
        service.reschedule_appointment("C1", "SLOT2", "idem-1")


def test_send_verification_code(http, service):
    http.programar(
        "POST", "/api/agenda/verificacion/enviar",
        HttpResponse(200, {"enviado": True, "mensaje": "ok", "correo_parcial": "j***@dominio.com"}),
    )
    resultado = service.send_verification_code("123456")
    assert resultado["correo_parcial"] == "j***@dominio.com"
    cabeceras = http.llamadas[-1]["headers"]
    assert cabeceras["X-Backend-Secret"] == "secreto-de-prueba-no-real"


def test_confirm_verification_code_valido(http, service):
    """Recado 014 — contrato PROPUESTO (ver docstring del módulo), no
    confirmado todavía contra hrmm-backend real."""
    http.programar("POST", "/api/agenda/verificacion/confirmar", HttpResponse(200, {"valido": True}))
    assert service.confirm_verification_code("123456", "654321") is True
    llamada = http.llamadas[-1]
    assert llamada["json_body"] == {"documento_paciente": "123456", "codigo": "654321"}
    assert llamada["headers"]["X-Backend-Secret"] == "secreto-de-prueba-no-real"


def test_confirm_verification_code_invalido(http, service):
    http.programar("POST", "/api/agenda/verificacion/confirmar", HttpResponse(401, {"detail": "codigo invalido o vencido"}))
    assert service.confirm_verification_code("123456", "000000") is False


def test_confirm_verification_code_error_inesperado(http, service):
    http.programar("POST", "/api/agenda/verificacion/confirmar", HttpResponse(500, {"detail": "error"}))
    with pytest.raises(AppointmentServiceError):
        service.confirm_verification_code("123456", "654321")


def test_cancel_appointment_verified_con_codigo_invalido(http, service):
    http.programar("POST", "/api/agenda/citas/C1/cancelar", HttpResponse(401, {"detail": "codigo invalido"}))
    with pytest.raises(AppointmentServiceError):
        service.cancel_appointment_verified("C1", "123456", "000000")


def test_cancel_appointment_verified_exitoso(http, service):
    cancelada = dict(_CITA_BASE, estado="cancelada")
    http.programar("POST", "/api/agenda/citas/C1/cancelar", HttpResponse(200, cancelada))
    resultado = service.cancel_appointment_verified("C1", "123456", "654321")
    from domains.health.models import AppointmentStatus

    assert resultado.status == AppointmentStatus.CANCELLED


def test_sin_secreto_configurado_falla_de_forma_clara(http, service, monkeypatch):
    monkeypatch.delenv("HRMM_BACKEND_SECRET", raising=False)
    with pytest.raises(AppointmentServiceError):
        service.get_patient_appointments("123456")


def test_buscar_paciente_publico_sin_secreto(http, service, monkeypatch):
    monkeypatch.delenv("HRMM_BACKEND_SECRET", raising=False)  # debe funcionar SIN secreto — es público
    http.programar(
        "GET", "/api/agenda/citas/buscar-paciente",
        HttpResponse(200, {"nombre_paciente": "Juan", "telefono": "3000000000"}),
    )
    resultado = service.buscar_paciente("123456")
    assert resultado == {"nombre_paciente": "Juan", "telefono": "3000000000"}


def test_buscar_paciente_no_encontrado(http, service):
    http.programar("GET", "/api/agenda/citas/buscar-paciente", HttpResponse(404, {"detail": "no encontrado"}))
    assert service.buscar_paciente("000000000") is None


# ---------------------------------------------------------------------
# Test de integración con red real — DESHABILITADO por defecto.
# El usuario indicó explícitamente ("todavía no ejecutar pruebas de red
# real") que esta fase no ejecuta contra hrmm-backend real. Este test
# existe como andamiaje para cuando se confirme entorno/credenciales,
# gateado por una variable de entorno que nunca se activa por defecto.
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_HRMM_TESTS") != "1",
    reason="Pruebas de red real contra hrmm-backend deshabilitadas por defecto — ver recado de esta fase.",
)
def test_get_availability_contra_hrmm_backend_real():
    from domains.health.hrmm_http import RealHttpClient

    base_url = os.environ["HRMM_BACKEND_URL"]
    http_real = RealHttpClient(base_url)
    catalog_real = CatalogMirror()
    catalog_real.sync(http_real)
    servicio_real = next(iter(catalog_real._servicios.values())).nombre
    service_real = HrmmAppointmentService(http_real, catalog_real)
    slots = service_real.get_availability(servicio_real)
    for slot in slots:
        assert slot.slot_id and slot.date and slot.time
