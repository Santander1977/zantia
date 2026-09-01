import uuid

import pytest

from domains.health import (
    Activity,
    MockActivitySource,
    MockAppointmentService,
    MockActivityResultSink,
    ReminderManager,
    build_health_agent_context,
    build_health_gateway,
)


def _nuevo_id() -> str:
    return str(uuid.uuid4())[:8]


def nueva_activity(activity_id: str = None, **overrides) -> Activity:
    datos = {
        "activity_id": activity_id or f"ACT-{_nuevo_id()}",
        "source_system": "IPS-DEMO",
        "correlation_id": f"corr-{_nuevo_id()}",
        "objective": "Facilitar programación de atención",
        "patient_reference": f"PAC-{_nuevo_id()}",
        "patient_contact": {"nombre": "Paciente Ficticio"},
        "program": "Programa de seguimiento cardiovascular",
        "reason": "Atención de seguimiento pendiente",
        "service": "medicina general",
    }
    datos.update(overrides)
    return Activity(**datos)


@pytest.fixture
def activity_factory():
    """Evita el import relativo `from .conftest import nueva_activity`
    (colisionaba con el paquete real `domains.health` — ver recado 007).
    Los tests reciben esta fábrica como fixture normal de pytest."""
    return nueva_activity


@pytest.fixture
def services():
    return {
        "source": MockActivitySource(),
        "appointment_service": MockAppointmentService(),
        "result_sink": MockActivityResultSink(),
        "reminder_manager": ReminderManager(),
    }


@pytest.fixture
def context(services):
    activity = services["source"].create(nueva_activity())
    return build_health_agent_context(
        activity,
        services["source"],
        services["appointment_service"],
        services["reminder_manager"],
        services["result_sink"],
    )


@pytest.fixture
def gateway(services):
    """Extensión aditiva (agente bidireccional) — no modifica los
    fixtures `services`/`context`/`activity_factory` de arriba, ya
    usados por la suite de la fase de demanda inducida (recado 007)."""
    return build_health_gateway(
        services["source"],
        services["appointment_service"],
        services["reminder_manager"],
        services["result_sink"],
    )
