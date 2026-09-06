"""
Quinto hallazgo real de la misma conversación de Telegram (recado 031,
continúa 026/027/030):

1. El catálogo real de hrmm-backend NO usa tildes ("Pediatria",
   "Odontologia", "Psicologia" — confirmado con una llamada real de
   solo lectura a `GET /api/agenda/servicios` el 2026-09-06, ver recado
   031). La normalización de tildes se aplicó igual, de forma
   defensiva, al ÚNICO punto real donde un nombre se traduce a
   `servicio_id` (`CatalogMirror.servicio_id_por_nombre`) — protege
   contra cualquier fuente (Activity outbound de la IPS, futuro cambio
   de convención del catálogo) que sí use tildes.

2. Bug real confirmado y corregido: preguntar "qué servicios tienen"
   como PRIMER mensaje (sin conversación previa) devolvía el catálogo
   pero NUNCA abría ninguna Activity/conversación rastreable — si el
   paciente respondía justo después nombrando un servicio real (ej.
   "Medicina general"), esa respuesta se reprocesaba desde cero como un
   mensaje sin relación (`find_open_context` devolvía `None`), sin
   ningún estado "esperando_servicio" que la reconociera. Terminaba
   cayendo al fallback genérico de sí/no de `HealthBrain` — el paciente
   sentía que responder correctamente no servía de nada. Mismo bug
   dentro de una conversación YA abierta (`HealthBrain._interpretar_decision`,
   rama `_CONSULTAR_SERVICIOS`): se quedaba en "esperando_decision" en
   vez de pasar a "esperando_servicio".

Corrección: ambas rutas (`gateway.py:_resolver_consulta_catalogo` y
`brain.py:_interpretar_decision`) ahora dejan la conversación en
"esperando_servicio" tras listar el catálogo — la respuesta siguiente
se interpreta con `HealthBrain._interpretar_servicio`, el MISMO
mecanismo que ya usaba `_resolver_programar_cita`.
"""
from domains.health import (
    Activity, MockActivitySource, MockActivityResultSink, ReminderManager,
    accept_activity, build_health_agent_context, build_health_gateway, contact_patient,
    handle_inbound_message, handle_patient_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.hrmm_catalog import CatalogMirror


class _DosServiciosReales(MockAppointmentService):
    """Catálogo real con DOS servicios — reproduce el escenario exacto
    donde el paciente pregunta por el catálogo y luego nombra uno."""

    def _seed_fictional_data(self) -> None:
        super()._seed_fictional_data()
        self._catalogo_servicios = ["medicina general", "pediatria"]
        self._slots["pediatria-1"] = AvailabilitySlot(
            slot_id="pediatria-1", service="pediatria", professional="Dr. Ruiz",
            location="Sede Norte", date="2026-09-10", time="09:00",
        )


def _gateway_dos_servicios():
    return build_health_gateway(
        MockActivitySource(), _DosServiciosReales(),
        ReminderManager(), MockActivityResultSink(),
    )


# ---------------------------------------------------------------------
# 1. El bug real: catálogo como PRIMER mensaje -> nombrar un servicio.
# ---------------------------------------------------------------------
def test_responder_con_servicio_real_tras_preguntar_catalogo_avanza_a_disponibilidad():
    gateway = _gateway_dos_servicios()
    pref = "TG-031-1"
    r1 = handle_inbound_message(gateway, pref, "telegram", "m1", "que servicios tienen")
    assert "medicina general" in r1.lower() and "pediatria" in r1.lower()

    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "Medicina general")
    assert "opciones disponibles" in r2.lower(), (
        "responder con un servicio real del catálogo debe avanzar a disponibilidad, "
        "no caer en el fallback genérico de sí/no (bug real, recado 031)"
    )
    assert "no logré entender si es un sí o un no" not in r2.lower()


def test_responder_con_el_segundo_servicio_del_catalogo_tambien_avanza():
    gateway = _gateway_dos_servicios()
    pref = "TG-031-2"
    handle_inbound_message(gateway, pref, "telegram", "m1", "que servicios tienen")
    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "pediatria")
    assert "opciones disponibles" in r2.lower()


# ---------------------------------------------------------------------
# 2. Mismo bug, pero preguntando el catálogo A MITAD de una conversación
#    ya abierta (HealthBrain._interpretar_decision, no gateway.py).
# ---------------------------------------------------------------------
def test_pregunta_de_catalogo_a_mitad_de_conversacion_tambien_deja_esperando_servicio():
    gateway = build_health_gateway(
        MockActivitySource(), _DosServiciosReales(), ReminderManager(), MockActivityResultSink(),
    )
    activity = gateway.activity_source.create(
        Activity(
            activity_id="ACT-031-MID", source_system="IPS-DEMO", objective="Seguimiento",
            patient_reference="PAC-031-MID", patient_contact={"nombre": "Juan"}, service="medicina general",
        )
    )
    context = build_health_agent_context(
        activity, gateway.activity_source, gateway.appointment_service,
        gateway.reminder_manager, gateway.result_sink,
    )
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "que servicios tienen")
    assert "medicina general" in r1.lower() and "pediatria" in r1.lower()

    r2 = handle_patient_message(context, "m2", "pediatria")
    assert "opciones disponibles" in r2.lower()


# ---------------------------------------------------------------------
# 3. Normalización de tildes en la traducción real nombre -> servicio_id.
# ---------------------------------------------------------------------
def test_catalog_mirror_servicio_id_por_nombre_ignora_tildes():
    """El catálogo REAL de hrmm-backend no usa tildes (confirmado en
    vivo, recado 031) — este test simula el caso contrario (una fuente
    QUE SÍ use tildes, ej. una Activity outbound provista por la IPS)
    para confirmar que la traducción a `servicio_id` no se rompe por
    esto en ningún sentido."""
    from domains.health.hrmm_http import FakeHttpClient, HttpResponse

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S2", "nombre": "Pediatría"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [])
        raise AssertionError(f"no programado en este test: {method} {path}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)

    # Catálogo real CON tilde ("Pediatría") — el paciente/la Activity
    # puede referirse a él SIN tilde ("Pediatria") y viceversa.
    assert catalog.servicio_id_por_nombre("Pediatria") == "S2"
    assert catalog.servicio_id_por_nombre("pediatria") == "S2"
    assert catalog.servicio_id_por_nombre("Pediatría") == "S2"
    assert catalog.servicio_id_por_nombre("Odontologia") is None
