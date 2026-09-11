"""
Recado 056, Punto 3 — pedido explícito del usuario: si el paciente
escribe de nuevo poco tiempo después de que su interacción anterior
cerró efectivamente (reserva confirmada/reprogramada/declinada), el
saludo debe ser corto ("¡Buenos días/tardes/noches, señor/señora
{nombre}! ¿Puedo ayudarlo en algo más?"), sin repetir la presentación
institucional completa ni el menú extenso.

Mecanismo elegido de forma autónoma (mismo criterio de "más simple
posible" ya usado en el resto de `gateway.py`): un nuevo campo
`HealthGateway._cierre_reciente` (patient_reference -> (momento real
del cierre, nombre conocido)), poblado en `_cerrar_si_definitivo` —
independiente de la ventana de gracia del recado 050
(`_recien_cerrada`, de UN solo turno, para reevaluar interrupciones de
contexto) porque resuelve un problema distinto: no "¿este mensaje es
sobre lo que se acaba de cerrar?", sino "¿ya lo saludé hace un
momento?". Umbral decidido de forma autónoma: 30 minutos.
"""
from datetime import datetime, timedelta, timezone

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import MockAppointmentService
from domains.health.gateway import find_open_context


def _completar_reserva(gateway, paciente):
    handle_inbound_message(gateway, paciente, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, paciente, "demo", "m2", "1")
    r3 = handle_inbound_message(gateway, paciente, "demo", "m3", "la primera")
    assert "confirmado" in r3.lower()
    assert find_open_context(gateway, paciente) is None  # cerrada de verdad


def test_regreso_poco_despues_de_cierre_recibe_saludo_corto():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    _completar_reserva(gateway, "PAC-CORTO-1")

    r4 = handle_inbound_message(gateway, "PAC-CORTO-1", "demo", "m4", "hola")

    assert "hospital regional" not in r4.lower(), f"no debía repetir la presentación institucional: {r4!r}"
    assert "1. reservar" not in r4.lower(), f"no debía repetir el menú extenso: {r4!r}"
    assert "puedo ayudarte en algo mas" in r4.lower() or "puedo ayudarte en algo más" in r4.lower()


def test_regreso_pasado_el_umbral_recibe_saludo_completo_de_nuevo():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    _completar_reserva(gateway, "PAC-CORTO-2")

    # Simula que ya pasó más del umbral (31 minutos) — retrocede el
    # timestamp real guardado en el cierre, sin tocar ningún reloj global.
    patient_ref = "PAC-CORTO-2"
    payload = gateway._cierre_reciente.obtener_payload(patient_ref)
    momento = gateway._cierre_reciente.momento_de(patient_ref)
    gateway._cierre_reciente.registrar(patient_ref, payload=payload, ahora=momento - timedelta(minutes=31))

    r4 = handle_inbound_message(gateway, patient_ref, "demo", "m4", "hola")
    assert "hospital regional" in r4.lower(), f"pasado el umbral, debía ver el saludo completo: {r4!r}"
    assert "1. reservar" in r4.lower()


def test_regreso_corto_con_intencion_clara_avanza_en_el_mismo_turno():
    """Diseño no bloqueante (recado 046) preservado: si el primer
    mensaje del regreso YA trae una intención clara, se procesa de
    inmediato — solo cambia el saludo antepuesto (corto en vez de
    completo), nunca el comportamiento de enrutamiento."""
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    _completar_reserva(gateway, "PAC-CORTO-3")

    r4 = handle_inbound_message(gateway, "PAC-CORTO-3", "demo", "m4", "necesito otra cita")
    assert "puedo ayudarte en algo mas" in r4.lower() or "puedo ayudarte en algo más" in r4.lower()
    assert "fechas disponibles" in r4.lower()


def test_nombre_conocido_del_cierre_se_usa_en_el_saludo_corto():
    from domains.health.models import Activity

    source = MockActivitySource()
    servicio = MockAppointmentService()
    from domains.health.agent import accept_activity, build_health_agent_context, contact_patient, handle_patient_message

    activity = source.create(Activity(
        activity_id="ACT-CORTO-NOMBRE", source_system="PATIENT_INITIATED", objective="o",
        patient_reference="PAC-CORTO-4", patient_contact={"nombre": "Carlos"}, service="medicina general",
    ))
    context = build_health_agent_context(activity, source, servicio, ReminderManager(), MockActivityResultSink())
    accept_activity(context)
    contact_patient(context)
    from domains.health.gateway import build_health_gateway as _bhg, register_context

    gateway = _bhg(source, servicio, ReminderManager(), MockActivityResultSink())
    register_context(gateway, "PAC-CORTO-4", context)
    handle_patient_message(context, "m1", "sí")
    handle_patient_message(context, "m2", "1")
    r3 = handle_patient_message(context, "m3", "la primera")
    assert "confirmado" in r3.lower()

    from domains.health.gateway import _cerrar_si_definitivo

    _cerrar_si_definitivo(gateway, "PAC-CORTO-4", context)
    assert gateway._cierre_reciente.obtener_payload("PAC-CORTO-4")[0] == "Carlos"  # nombre

    r4 = handle_inbound_message(gateway, "PAC-CORTO-4", "demo", "m4", "hola")
    assert "señor carlos" in r4.lower()
