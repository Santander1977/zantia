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

# Capturado a nivel de módulo (ANTES de que corra cualquier fixture,
# incluida la autouse `_secreto_de_prueba` de abajo, que sobrescribe
# `HRMM_BACKEND_SECRET` con un valor falso para TODOS los tests de este
# archivo) — únicamente para que el test real gateado más abajo
# (`test_book_appointment_persiste_el_correo_real_contra_hrmm_backend_real`)
# pueda restaurar el secreto REAL del `.env` dentro de su propio scope,
# necesario porque ese test SÍ llama endpoints trusted reales
# (`GET`/`PATCH /api/agenda/citas`) — a diferencia de los otros 2 tests
# reales de este archivo, que solo usan endpoints públicos.
_HRMM_BACKEND_SECRET_REAL = os.environ.get("HRMM_BACKEND_SECRET")

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


# ---------------------------------------------------------------------
# Recado 085/R-21 — el correo real de confirmación NUNCA se disparaba
# para una reserva hecha por chat: `buscar_paciente` (único dato de
# contacto que el wizard de identidad consultaba) no expone `correo`
# (`PacienteBuscado`, confirmado leyendo el schema real de hrmm-backend
# — solo nombre_paciente/telefono, por privacidad). `correo_conocido`
# replica, del lado de ZANTIA, la MISMA técnica que hrmm-backend usa
# internamente para `enviar_codigo_verificacion` (buscar un correo entre
# las citas YA existentes del documento) — sobre el MISMO endpoint
# trusted (`GET /api/agenda/citas`) que `get_patient_appointments` ya
# usa, así que no hace falta ningún cambio del lado de hrmm-backend.
# ---------------------------------------------------------------------
def test_correo_conocido_encuentra_el_correo_de_una_cita_previa(http, service, monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    http.programar("GET", "/api/agenda/citas", HttpResponse(200, [
        {**_CITA_BASE, "cita_id": "C1", "correo": None},
        {**_CITA_BASE, "cita_id": "C2", "correo": "real@example.com"},
    ]))
    assert service.correo_conocido("123456") == "real@example.com"


def test_correo_conocido_devuelve_none_sin_ninguna_cita_previa(http, service, monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    http.programar("GET", "/api/agenda/citas", HttpResponse(200, []))
    assert service.correo_conocido("123456") is None


def test_correo_conocido_devuelve_none_si_hrmm_backend_falla(http, service, monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    http.programar("GET", "/api/agenda/citas", HttpResponse(500, {"detail": "error"}))
    # Best-effort — nunca rompe el flujo de identificación por esto.
    assert service.correo_conocido("123456") is None


def test_book_appointment_incluye_correo_en_el_payload_de_creacion(http, service):
    """El correo real (recado 085) ahora viaja en el body de creación
    (`CitaCreate.correo`, campo real que hrmm-backend SÍ persiste en la
    cita) — antes SIEMPRE se omitía, así que la cita quedaba con
    `correo: null` en la base real incluso cuando la confirmación se
    lograba enviar después."""
    http.programar("GET", "/api/agenda/disponibilidad", HttpResponse(200, [
        {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"}
    ]))
    http.programar("GET", "/api/agenda/citas", HttpResponse(200, []))
    http.programar("POST", "/api/agenda/citas", HttpResponse(201, {**_CITA_BASE, "correo": "real@example.com"}))
    http.programar("POST", "/api/agenda/citas/C1/enviar-confirmacion", HttpResponse(200, {"exito": True, "estado": "enviado", "mensaje": "ok"}))

    service.get_availability("medicina general")
    cita = service.book_appointment("SLOT1", "123456", "idem-correo", correo="real@example.com")

    llamada_creacion = next(c for c in http.llamadas if c["method"] == "POST" and c["path"] == "/api/agenda/citas")
    assert llamada_creacion["json_body"]["correo"] == "real@example.com"
    assert cita.correo_confirmacion_enviado is True


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


def test_book_appointment_en_conversacion_nueva_con_otro_horario_no_reutiliza_la_vieja(monkeypatch):
    """Recado 068 — hallazgo real GRAVE, confirmado leyendo el código:
    la 'idempotencia adicional' de arriba comparaba SOLO servicio+fecha
    (nunca la hora) — un paciente que reservó a las 07:30 en una
    conversación, y minutos después, en una conversación NUEVA (otra
    idempotency_key), pidió genuinamente Urgencias el mismo día pero a
    las 07:00 (una franja DISTINTA, ofrecida y elegida explícitamente),
    recibía en silencio la cita VIEJA (07:30) como si fuera el
    resultado de la nueva selección — nunca se creaba una segunda cita
    (no hay duplicado en la base real), pero el sistema afirmaba haber
    reservado algo que no pasó. Reproduce el escenario completo con un
    servicio HTTP con estado real (citas creadas se reflejan en
    consultas posteriores), como en producción."""
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")

    citas_creadas: list = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "Urgencias"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dr. Prueba", "servicio_id": "S1", "consultorio": "Urgencias"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT-0700", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-14", "hora_inicio": "07:00", "hora_fin": "07:30", "estado": "Libre"},
                {"slot_id": "SLOT-0730", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-14", "hora_inicio": "07:30", "hora_fin": "08:00", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, list(citas_creadas))
        if method == "POST" and path == "/api/agenda/citas":
            nueva = {
                "cita_id": f"C{len(citas_creadas) + 1}",
                "slot_id": json_body["slot_id"],
                "medico_id": "M1",
                "servicio_id": "S1",
                "fecha": "2026-09-14",
                "hora_inicio": {"SLOT-0700": "07:00", "SLOT-0730": "07:30"}[json_body["slot_id"]],
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""),
                "telefono": json_body.get("telefono", ""),
                "estado": "reservada",
                "created_at": "2026-09-11T21:37:00Z",
                "updated_at": "2026-09-11T21:37:00Z",
            }
            citas_creadas.append(nueva)
            return HttpResponse(201, nueva)
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    service.get_availability("Urgencias")

    # Conversación 1 (activity_id distinto -> idempotency_key distinta):
    # el paciente elige la 2da opción (07:30 real, orden cronológico).
    cita1 = service.book_appointment("SLOT-0730", "123456", "ACT-CONV-1:booking")
    assert cita1.time == "07:30"

    # Conversación 2, minutos después: el paciente elige la 1ra opción
    # de una oferta NUEVA (07:00) — un slot genuinamente distinto.
    cita2 = service.book_appointment("SLOT-0700", "123456", "ACT-CONV-2:booking")
    assert cita2.time == "07:00", (
        f"debía reservar el slot realmente elegido (07:00), no reutilizar la cita vieja: {cita2!r}"
    )
    assert cita2.appointment_id != cita1.appointment_id

    llamadas_post = [c for c in http.llamadas if c["method"] == "POST" and c["path"] == "/api/agenda/citas"]
    assert len(llamadas_post) == 2, "la segunda selección SÍ debía intentar reservar de verdad"


def test_book_appointment_en_conversacion_nueva_con_el_mismo_horario_si_se_deduplica(monkeypatch):
    """Control: el mecanismo de idempotencia adicional SIGUE
    funcionando para su propósito original — mismo slot exacto, dos
    idempotency_key distintas (ej. reintento real del sistema IPS)."""
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, [_CITA_BASE])  # ya existe una activa, MISMO slot
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    service.get_availability("medicina general")

    cita = service.book_appointment("SLOT1", "123456", "idempotency-key-distinta-pero-mismo-slot")
    assert cita.appointment_id == "C1"
    llamadas_post = [c for c in http.llamadas if c["method"] == "POST" and c["path"] == "/api/agenda/citas"]
    assert llamadas_post == []


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


def test_send_verification_code_convierte_fallo_de_transporte_en_appointment_service_error(service):
    """Recado 082 — hallazgo real de producción (documento 72302972, tras
    un reinicio de n8n): un timeout esperando la respuesta de
    hrmm-backend se propagaba como `HttpError`, nunca capturado aquí —
    `HttpError` NO es `AppointmentServiceError`, así que escapaba de los
    3 `except AppointmentServiceError` de `gateway.py` y terminaba en el
    `except Exception` genérico de `service/app.py` ("Tuvimos un
    problema procesando tu mensaje" en vez del mensaje honesto que esos
    3 sitios ya saben dar). Ahora se convierte aquí, sin necesitar red
    real para reproducirlo — ver `test_hrmm_http.py` para el mismo
    fallo reproducido con un socket real."""

    def _generador_que_falla_de_transporte(method, path, params, json_body, headers):
        from domains.health.hrmm_http import HttpError

        raise HttpError("timeout esperando la respuesta (simulado)")

    service._http.generador = _generador_que_falla_de_transporte

    with pytest.raises(AppointmentServiceError):
        service.send_verification_code("123456")


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


# ---------------------------------------------------------------------
# Recado 085/R-21 — confirma, contra hrmm-backend REAL, que una cita
# creada vía `book_appointment(..., correo=...)` (el mismo método que
# ahora usa el flujo real de chat, ver `tools.py:BookAppointmentTool`)
# queda con el campo `correo` REALMENTE poblado en la base — a
# diferencia de `CITA-2cb295f690` (reserva real del hallazgo original,
# `correo: null`). A diferencia de `test_enviar_confirmacion_email_
# contra_hrmm_backend_real` (abajo, interactiva — verifica la ENTREGA
# real del correo, que exige un humano revisando un inbox en vivo), este
# test verifica solo el PAYLOAD persistido — totalmente automático, sin
# `input()`: la limpieza usa `PATCH /citas/{id}` (trusted, mismo secreto
# ya usado para crear la cita) para cancelar directamente, sin pasar por
# el sub-flujo de código de verificación que exige `cancel_appointment_
# verified` (ese es para acciones INICIADAS POR EL PACIENTE vía chat —
# una limpieza de datos de prueba propios no lo necesita).
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_HRMM_TESTS") != "1",
    reason="Prueba de red real contra hrmm-backend deshabilitada por defecto — ver recado 085.",
)
def test_book_appointment_persiste_el_correo_real_contra_hrmm_backend_real(monkeypatch):
    import time

    from domains.health.hrmm_http import RealHttpClient

    if not _HRMM_BACKEND_SECRET_REAL:
        pytest.skip("HRMM_BACKEND_SECRET real no disponible en el entorno de este proceso.")
    # Restaura el secreto REAL — la fixture autouse `_secreto_de_prueba`
    # ya lo sobrescribió con un valor falso para este test también.
    monkeypatch.setenv("HRMM_BACKEND_SECRET", _HRMM_BACKEND_SECRET_REAL)

    base_url = os.environ["HRMM_BACKEND_URL"]
    secreto = _HRMM_BACKEND_SECRET_REAL
    http_real = RealHttpClient(base_url)
    catalog_real = CatalogMirror()
    catalog_real.sync(http_real)
    servicio_real = next(iter(catalog_real._servicios.values())).nombre
    service_real = HrmmAppointmentService(http_real, catalog_real)

    documento = f"ZANTIA-TEST-085-{int(time.time())}"
    telefono = f"5730002{int(time.time()) % 10000:04d}"
    correo_prueba = f"zantia-test-085-{int(time.time())}@example.com"

    opciones = service_real.get_availability(servicio_real)
    assert opciones, "Sin disponibilidad real para el servicio elegido — no se puede montar la prueba."
    slot = opciones[0]

    service_real.register_patient_contact(documento, "ZANTIA TEST 085", telefono)
    cita_id = None
    try:
        cita = service_real.book_appointment(slot.slot_id, documento, f"zantia-test-085:{documento}", correo=correo_prueba)
        cita_id = cita.appointment_id

        # Relectura CRUDA (no vía `get_appointment`/`Appointment`, que
        # descarta `correo` — el mismo campo que este test verifica)
        # para confirmar lo que hrmm-backend REALMENTE persistió.
        respuesta_cruda = http_real.request(
            "GET", f"/api/agenda/citas/{cita_id}", headers={"X-Backend-Secret": secreto},
        )
        assert respuesta_cruda.status == 200, respuesta_cruda.body
        assert respuesta_cruda.body.get("correo") == correo_prueba, (
            f"la cita real {cita_id} quedó con correo={respuesta_cruda.body.get('correo')!r} "
            f"en vez de {correo_prueba!r} — mismo síntoma que CITA-2cb295f690"
        )
        # El segundo paso (envío real) también debió intentarse con el
        # mismo correo — best-effort, `True` si hrmm-backend confirmó.
        assert cita.correo_confirmacion_enviado is True, cita
    finally:
        if cita_id is not None:
            respuesta_cancelacion = http_real.request(
                "PATCH", f"/api/agenda/citas/{cita_id}",
                json_body={"estado": "cancelada", "canal": "zantia-test-085-cleanup"},
                headers={"X-Backend-Secret": secreto},
            )
            assert respuesta_cancelacion.status == 200, (
                f"LIMPIEZA FALLIDA — cita de prueba {cita_id} (documento {documento}) "
                f"quedó activa en hrmm-backend real: {respuesta_cancelacion.body!r}"
            )


# ---------------------------------------------------------------------
# Recado 086 — hallazgo real GRAVE, reportado por un paciente real
# (documento 72302972, NUNCA usado en este test — documento sintético
# propio, aislado desde el diseño, mismo criterio que el test de
# arriba): una identidad ya VERIFICADA de ANTES del recado 085 (sin
# `correo` persistido) nunca vuelve a pasar por el wizard completo
# mientras siga vigente — quedaba con `correo: None` PARA SIEMPRE, sin
# importar que el fix del recado 085 estuviera desplegado. Corregido con
# backfill transparente (`gateway.py:_correo_conocido` + nuevo
# `identity_store.actualizar_correo`). Este test verifica AMBAS partes
# del recado 086 juntas, contra hrmm-backend real:
#   1. El backfill encuentra y persiste un correo real para una
#      identidad ya verificada sin correo (simulada localmente en un
#      `identity_store` en memoria — nunca toca la base real).
#   2. El mensaje de confirmación final nombra la gestión real
#      ("reserva"), usando ese correo backfilled, contra un envío REAL.
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_HRMM_TESTS") != "1",
    reason="Prueba de red real contra hrmm-backend deshabilitada por defecto — ver recado 086.",
)
def test_backfill_de_correo_y_mensaje_con_tipo_gestion_contra_hrmm_backend_real(monkeypatch):
    import time

    from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
    from domains.health.gateway import build_health_gateway, _correo_conocido
    from domains.health.hrmm_http import RealHttpClient
    from domains.health.identity_store import SQLiteIdentidadCanalStore
    from domains.health.models import sufijo_confirmacion_correo

    if not _HRMM_BACKEND_SECRET_REAL:
        pytest.skip("HRMM_BACKEND_SECRET real no disponible en el entorno de este proceso.")
    monkeypatch.setenv("HRMM_BACKEND_SECRET", _HRMM_BACKEND_SECRET_REAL)

    base_url = os.environ["HRMM_BACKEND_URL"]
    secreto = _HRMM_BACKEND_SECRET_REAL
    http_real = RealHttpClient(base_url)
    catalog_real = CatalogMirror()
    catalog_real.sync(http_real)
    servicio_real = next(iter(catalog_real._servicios.values())).nombre
    service_real = HrmmAppointmentService(http_real, catalog_real)

    epoch = int(time.time())
    documento = f"ZANTIA-TEST-086-{epoch}"
    telefono_canal = f"5730003{epoch % 10000:04d}"
    correo_real_previo = f"zantia-test-086-{epoch}@example.com"

    opciones = service_real.get_availability(servicio_real)
    assert len(opciones) >= 2, "Se necesitan 2 turnos reales distintos para esta prueba."
    # Recado 086 — bug real de diseño de este test, encontrado en la
    # primera corrida completa (junto a otras pruebas reales del mismo
    # archivo): `opciones[0]`/`opciones[1]` pueden compartir la MISMA
    # (fecha, hora) si son de médicos distintos — dispara el chequeo
    # anti-duplicado LEGÍTIMO del recado 068
    # (`book_appointment`, "ya existe una cita equivalente — no se
    # duplica"), que devuelve la cita YA EXISTENTE (cita_a) en vez de
    # crear una cita_b genuina — esa relectura nunca carga
    # `correo_confirmacion_enviado` (no es un bug del recado 086, es
    # el mismo límite ya documentado para `_reconstruir_appointment`).
    # Se eligen explícitamente 2 slots con (fecha, hora) DISTINTAS para
    # que cita_b sea una reserva genuina y comparable.
    slot_a = opciones[0]
    slot_b = next(
        (o for o in opciones[1:] if (o.date, o.time) != (slot_a.date, slot_a.time)), None
    )
    assert slot_b is not None, "No hay 2 turnos reales con fecha/hora distintas para esta prueba."

    citas_creadas = []
    try:
        # 1) Cita A — establece un correo REAL en archivo para este
        #    documento sintético (igual que las citas previas reales de
        #    un paciente real que sí completó una reserva alguna vez).
        cita_a = service_real.book_appointment(
            slot_a.slot_id, documento, f"zantia-test-086-a:{documento}", correo=correo_real_previo
        )
        citas_creadas.append(cita_a.appointment_id)

        # 2) Identidad "ya verificada de antes del recado 085" — SIN
        #    correo — simulada en un identity_store LOCAL (nunca toca
        #    ningún dato real de producción, la tabla identidad_canal
        #    ni siquiera existe del lado de hrmm-backend).
        store = SQLiteIdentidadCanalStore(":memory:")
        store.marcar_verificado(telefono_canal, documento, "ZANTIA TEST 086")
        assert store.get(telefono_canal).correo is None

        gateway = build_health_gateway(
            MockActivitySource(), service_real, ReminderManager(), MockActivityResultSink(),
            identity_store=store,
        )

        # 3) Backfill — transparente, sin ningún wizard.
        correo_backfilled = _correo_conocido(gateway, telefono_canal)
        assert correo_backfilled == correo_real_previo, (
            f"el backfill no encontró el correo real en archivo: {correo_backfilled!r}"
        )
        assert store.get(telefono_canal).correo == correo_real_previo, (
            "el backfill encontró el correo pero no lo persistió en identity_store"
        )

        # 4) Cita B — reserva real usando el correo backfilled, y el
        #    mensaje final (misma función que usa la conversación real)
        #    nombra la gestión real, contra un envío de confirmación
        #    REAL.
        cita_b = service_real.book_appointment(
            slot_b.slot_id, documento, f"zantia-test-086-b:{documento}", correo=correo_backfilled
        )
        citas_creadas.append(cita_b.appointment_id)
        assert cita_b.correo_confirmacion_enviado is True, cita_b

        mensaje_final = (
            f"¡Listo! Quedó confirmado: {cita_b.service} el {cita_b.date} a las {cita_b.time} en {cita_b.location}."
            + sufijo_confirmacion_correo(cita_b.correo_confirmacion_enviado, "reserva")
        )
        assert "el correo de reserva fue enviado a tu correo" in mensaje_final.lower(), mensaje_final
    finally:
        for cid in citas_creadas:
            respuesta_cancelacion = http_real.request(
                "PATCH", f"/api/agenda/citas/{cid}",
                json_body={"estado": "cancelada", "canal": "zantia-test-086-cleanup"},
                headers={"X-Backend-Secret": secreto},
            )
            assert respuesta_cancelacion.status == 200, (
                f"LIMPIEZA FALLIDA — cita de prueba {cid} (documento {documento}) "
                f"quedó activa en hrmm-backend real: {respuesta_cancelacion.body!r}"
            )


# ---------------------------------------------------------------------
# Recado 054 — `enviar_confirmacion_email` contra hrmm-backend REAL.
# Mismo patrón de gate que el resto de esta sección
# (`ZANTIA_RUN_REAL_HRMM_TESTS=1`), MANUAL e INTERACTIVA a propósito:
# limpiar la cita de prueba exige el mismo sub-flujo de código de
# verificación que cualquier cancelación real (`cancel_appointment_verified`
# — no existe ningún atajo de "cancelación de confianza" sin código en
# el contrato real de hrmm-backend, confirmado leyendo
# `HrmmAppointmentService.cancel_appointment`, que SIEMPRE lanza
# `VerificationRequiredError` — mismo hallazgo que ya documentaba
# `test_identidad_persistente.py`), y ese código se envía por correo
# REAL — ningún agente puede leerlo por sí mismo. Se pide con `input()`,
# a quien corra `pytest -s` a mano.
#
# Variables de entorno requeridas (nunca hardcodeadas):
# - `ZANTIA_RUN_REAL_HRMM_TESTS=1` (gate explícito).
# - `HRMM_BACKEND_URL`, `HRMM_BACKEND_SECRET` (reales).
# - `ZANTIA_TEST_CORREO_REAL`: un correo que la persona que corre el
#   test pueda revisar EN VIVO — recibe la confirmación real (lo que
#   este test verifica) y luego el código de limpieza.
#
# Documento de prueba: `ZANTIA-TEST-CORREO-<epoch>`, claramente
# marcado, nunca un paciente real — misma convención que
# `test_identidad_canal_real_e2e`. La cita se crea con una llamada HTTP
# directa (igual que ese otro test) porque `book_appointment` no
# recibe `correo` en el body salvo que se lo pasemos explícitamente
# (recado 054) — acá SÍ se lo pasamos, para poder verificar el envío
# real de punta a punta.
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_HRMM_TESTS") != "1",
    reason="Prueba de red real contra hrmm-backend deshabilitada por defecto — ver recado 054.",
)
def test_enviar_confirmacion_email_contra_hrmm_backend_real():
    import time

    from domains.health.hrmm_http import RealHttpClient

    correo_real = os.environ.get("ZANTIA_TEST_CORREO_REAL")
    if not correo_real:
        pytest.skip("ZANTIA_TEST_CORREO_REAL no configurado — requerido para recibir la confirmación real.")

    base_url = os.environ["HRMM_BACKEND_URL"]
    http_real = RealHttpClient(base_url)
    catalog_real = CatalogMirror()
    catalog_real.sync(http_real)
    servicio_real = next(iter(catalog_real._servicios.values())).nombre
    service_real = HrmmAppointmentService(http_real, catalog_real)

    documento = f"ZANTIA-TEST-CORREO-{int(time.time())}"
    telefono = f"5730001{int(time.time()) % 10000:04d}"

    opciones = service_real.get_availability(servicio_real)
    assert opciones, "Sin disponibilidad real para el servicio elegido — no se puede montar la prueba."
    slot = opciones[0]
    respuesta_cita = http_real.request(
        "POST", "/api/agenda/citas",
        json_body={
            "slot_id": slot.slot_id, "documento_paciente": documento,
            "nombre_paciente": "ZANTIA TEST CORREO 054", "telefono": telefono,
            "correo": correo_real, "canal": "zantia-test",
        },
    )
    assert respuesta_cita.status == 201, respuesta_cita.body
    cita_id = respuesta_cita.body["cita_id"]

    try:
        resultado = service_real.enviar_confirmacion_email(cita_id, correo_real)
        assert isinstance(resultado, dict) and "exito" in resultado, resultado

        recibido = input(
            f"\n>>> Revisa {correo_real}: ¿llegó un correo de confirmación real para la cita "
            f"{cita_id}? (s/n): "
        ).strip().lower()
        assert recibido == "s", f"hrmm-backend respondió {resultado!r} pero no llegó el correo real"
    finally:
        # Limpieza real: cancela la cita de prueba (mismo rigor que
        # `test_identidad_canal_real_e2e` — requiere OTRO código real).
        service_real.send_verification_code(documento)
        codigo_limpieza = input(
            f"\n>>> LIMPIEZA: revisa {correo_real} de nuevo y escribe el código para "
            f"cancelar la cita de prueba {cita_id}: "
        ).strip()
        cancelada = service_real.cancel_appointment_verified(cita_id, documento, codigo_limpieza)
        from domains.health.models import AppointmentStatus
        assert cancelada.status == AppointmentStatus.CANCELLED, cancelada


def test_mapear_estado_con_vocabulario_real_confirmado():
    """Recado 032 — vocabulario real de `Cita.estado` confirmado con una
    llamada real de solo lectura contra hrmm-backend (documento con
    historial real variado): "agendada", "atendida", "cancelada",
    "reprogramada", "no_show". Cierra R-9 (antes "reservada"/
    "confirmada"/"no_asistio" eran inferencia, no confirmación —
    resultaron ser incorrectas para el estado de una reserva recién
    creada, causa raíz directa del bug del recado 032)."""
    from domains.health.hrmm_appointment_service import _mapear_estado
    from domains.health.models import AppointmentStatus

    assert _mapear_estado("agendada") == AppointmentStatus.CONFIRMED
    assert _mapear_estado("atendida") == AppointmentStatus.ATTENDED
    assert _mapear_estado("cancelada") == AppointmentStatus.CANCELLED
    assert _mapear_estado("reprogramada") == AppointmentStatus.RESCHEDULED
    assert _mapear_estado("no_show") == AppointmentStatus.NO_SHOW
    # Valores no contemplados nunca se inventan como algo distinto de
    # REQUESTED (comportamiento conservador, sin cambios).
    assert _mapear_estado("algo-nuevo-no-visto") == AppointmentStatus.REQUESTED
