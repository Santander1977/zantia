"""
domains/health/config.py — único punto de composición que decide,
según HRMM_BACKEND_ENV, si domains/health/ usa MockAppointmentService o
HrmmAppointmentService (recado 009 pendiente #1, recado 011).

Ninguna llamada de red real en estos tests — el caso `production` se
verifica inyectando un FakeHttpClient (punto de inyección solo-test de
build_appointment_service), nunca RealHttpClient.
"""
import pytest

from domains.health.appointment_service import MockAppointmentService
from domains.health.config import HealthConfigError, build_appointment_service
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_http import FakeHttpClient, HttpResponse


def _http_fake_con_catalogo() -> FakeHttpClient:
    cliente = FakeHttpClient()
    cliente.programar(
        "GET", "/api/agenda/servicios",
        HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}]),
    )
    cliente.programar(
        "GET", "/api/agenda/medicos",
        HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}]),
    )
    return cliente


def test_sin_hrmm_backend_env_usa_mock_por_defecto(monkeypatch):
    monkeypatch.delenv("HRMM_BACKEND_ENV", raising=False)
    servicio = build_appointment_service()
    assert isinstance(servicio, MockAppointmentService)


def test_hrmm_backend_env_mock_explicito_usa_mock(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_ENV", "mock")
    servicio = build_appointment_service()
    assert isinstance(servicio, MockAppointmentService)


def test_hrmm_backend_env_production_con_variables_completas_instancia_hrmm(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_ENV", "production")
    monkeypatch.setenv("HRMM_BACKEND_URL", "https://curson8n-hrmm-backend.byrp3l.easypanel.host")
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")

    http_fake = _http_fake_con_catalogo()
    servicio = build_appointment_service(http_client=http_fake)

    assert isinstance(servicio, HrmmAppointmentService)
    # Confirma que SOLO se llamó al catálogo (servicios/medicos) para
    # componer — cero llamadas a disponibilidad/citas/reservas, cero red real.
    llamadas = [(l["method"], l["path"]) for l in http_fake.llamadas]
    assert set(llamadas) == {("GET", "/api/agenda/servicios"), ("GET", "/api/agenda/medicos")}


def test_hrmm_backend_env_production_sin_url_falla_al_arrancar(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_ENV", "production")
    monkeypatch.delenv("HRMM_BACKEND_URL", raising=False)
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")

    with pytest.raises(HealthConfigError, match="HRMM_BACKEND_URL"):
        build_appointment_service()


def test_hrmm_backend_env_production_sin_secreto_falla_al_arrancar(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_ENV", "production")
    monkeypatch.setenv("HRMM_BACKEND_URL", "https://curson8n-hrmm-backend.byrp3l.easypanel.host")
    monkeypatch.delenv("HRMM_BACKEND_SECRET", raising=False)

    with pytest.raises(HealthConfigError, match="HRMM_BACKEND_SECRET"):
        build_appointment_service()


def test_hrmm_backend_env_staging_falla_explicitamente(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_ENV", "staging")

    with pytest.raises(HealthConfigError, match="staging"):
        build_appointment_service()


def test_hrmm_backend_env_valor_desconocido_falla_explicitamente(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_ENV", "qa-interno")

    with pytest.raises(HealthConfigError, match="qa-interno"):
        build_appointment_service()
