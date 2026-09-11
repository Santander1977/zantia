"""
Recado 070 (parte 2) — hallazgo real confirmado en varias conversaciones
de hoy: los mensajes de ACLARACIÓN (cuando el sistema no reconoció la
respuesta del paciente a una lista numerada ya ofrecida) para fecha,
horario, y la selección de slot dentro del wizard de verificación de
código, pedían "¿me confirmas si es la 1, la 2 o la 3?" SIN volver a
mostrar qué era cada opción — el paciente tenía que recordarlo de
memoria. La selección de SERVICIO (`_VARIANTES_SERVICIO_NO_IDENTIFICADO`)
y las 3 variantes de AMBIGÜEDAD genuina (servicio/fecha/horario) ya
incluían la lista completa desde que se crearon (recados 034/036/051) —
el hueco estaba específicamente en 3 lugares:

1. `_VARIANTES_FECHA_NO_IDENTIFICADA` (brain.py) — usada por
   `_interpretar_fecha` cuando ningún ordinal/texto libre matcheó nada.
2. `_VARIANTES_SELECCION_NO_IDENTIFICADA` (brain.py) — usada por
   `_interpretar_horario` en el mismo caso.
3. `_interpretar_seleccion_reprogramacion` (brain.py) y el wizard
   paralelo de verificación por código (`gateway.py:_procesar_intento_de_codigo`,
   stage "esperando_seleccion") — ambos con su propio mensaje fijo sin
   `{opciones}`.

Corrección: las 3 ahora reconstruyen y repiten la lista YA mostrada al
paciente (mismo formato "1. ...\\n2. ...", número + dato real) antes de
la pregunta de aclaración — nunca solo el número suelto.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService


class _CatalogoUnServicioTresFechas(MockAppointmentService):
    """Un solo servicio, con disponibilidad en 3 fechas reales
    DISTINTAS — necesario para llegar a `esperando_fecha` sin que el
    sistema pregunte antes por el servicio (un solo servicio se asume
    directo, recado 030)."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["Medicina General"]
        for slot_id, fecha in (("MG-1", "2026-09-14"), ("MG-2", "2026-09-15"), ("MG-3", "2026-09-16")):
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="Medicina General", professional="Dr. Ruiz",
                location="Sede Norte", date=fecha, time="09:00",
            )


class _CatalogoUnServicioTresHorarios(MockAppointmentService):
    """Un solo servicio, una sola fecha, con 3 horarios reales
    DISTINTOS en el mismo consultorio — necesario para llegar a
    `esperando_horario`."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["Medicina General"]
        for slot_id, hora in (("MG-1", "09:00"), ("MG-2", "10:00"), ("MG-3", "11:00")):
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="Medicina General", professional="Dr. Ruiz",
                location="Sede Norte", date="2026-09-14", time=hora,
            )


def _no_es_solo_numero_suelto(texto: str) -> bool:
    """Confirma que el mensaje de aclaración trae MÁS que solo la
    pregunta por el número — es decir, que el texto contiene al menos
    una línea de lista numerada real (formato "N. dato")."""
    import re

    return re.search(r"(?m)^\s*\d\.\s+\S", texto) is not None


# ---------------------------------------------------------------------
# 1. Fecha — reproduce transcripción real: "No logré identificar cuál
#    fecha prefieres — ¿me confirmas si es la 1, la 2 o la 3?" SIN lista.
# ---------------------------------------------------------------------
def test_aclaracion_de_fecha_repite_la_lista_completa():
    gateway = build_health_gateway(
        MockActivitySource(), _CatalogoUnServicioTresFechas(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-070-ACLARA-FECHA"
    r1 = handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    assert "14 de septiembre" in r1.lower()

    r2 = handle_inbound_message(gateway, ref, "demo", "m2", "blablabla no se")
    assert "no logré identificar cuál fecha prefieres" in r2.lower()
    assert _no_es_solo_numero_suelto(r2), f"la aclaración de fecha NO repitió la lista: {r2!r}"
    assert "14 de septiembre" in r2.lower() and "15 de septiembre" in r2.lower() and "16 de septiembre" in r2.lower()


# ---------------------------------------------------------------------
# 2. Horario — reproduce transcripción real: "¿me confirmas si es la 1,
#    la 2 o la 3?" SIN lista.
# ---------------------------------------------------------------------
def test_aclaracion_de_horario_repite_la_lista_completa():
    gateway = build_health_gateway(
        MockActivitySource(), _CatalogoUnServicioTresHorarios(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-070-ACLARA-HORARIO"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, ref, "demo", "m2", "14 de septiembre")
    assert "09:00" in r2

    r3 = handle_inbound_message(gateway, ref, "demo", "m3", "no entendi nada de eso")
    assert "no logré identificar" in r3.lower() or "no estoy seguro" in r3.lower()
    assert _no_es_solo_numero_suelto(r3), f"la aclaración de horario NO repitió la lista: {r3!r}"
    assert "09:00" in r3 and "10:00" in r3 and "11:00" in r3


# ---------------------------------------------------------------------
# 3. Reprogramación (Brain, camino de Activity ya reservada) — mismo
#    hallazgo en "¿Me confirmas cuál opción prefieres — la 1, la 2 o la
#    3?" (sin lista, `_interpretar_seleccion_reprogramacion`).
# ---------------------------------------------------------------------
def test_aclaracion_de_reprogramacion_repite_la_lista_completa():
    from domains.health import accept_activity
    from domains.health.brain import HealthBrain
    from domains.health.models import Activity
    from state.models import ConversationState

    activity = Activity(
        activity_id="ACT-070-REPROG", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="Medicina General",
        appointment_id="APT-1",
    )
    brain = HealthBrain(lambda: activity, _CatalogoUnServicioTresFechas())
    estado_ofrecida = brain.interpret(
        "quiero reprogramar", ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_decision"}), []
    )
    datos_ofrecidos = estado_ofrecida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert "14 de septiembre" in estado_ofrecida.respuesta_propuesta.lower()

    salida = brain.interpret(
        "no entendi nada", ConversationState(canal="demo", datos_recopilados=datos_ofrecidos), []
    )
    assert _no_es_solo_numero_suelto(salida.respuesta_propuesta), (
        f"la aclaración de reprogramación NO repitió la lista: {salida.respuesta_propuesta!r}"
    )
    assert "14 de septiembre" in salida.respuesta_propuesta.lower()


# ---------------------------------------------------------------------
# 4. Wizard de verificación por código, sub-etapa "esperando_seleccion"
#    (reprogramar con 2FA) — mismo hallazgo en gateway.py.
# ---------------------------------------------------------------------
def test_aclaracion_de_seleccion_en_wizard_de_codigo_repite_la_lista_completa():
    from domains.health.gateway import _procesar_intento_de_codigo

    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-070-WIZ"
    gateway._pending_verifications[ref] = {
        "action": "reprogramar",
        "appointment_id": "APT-1",
        "documento_paciente": "123",
        "stage": "esperando_seleccion",
        "opciones_slot_id": ["S1", "S2", "S3"],
        "request_id": "REQ-1",
        "service": "Medicina General",
        "texto_opciones_slot": (
            "1. Lunes 14 de septiembre, 09:00, Sede Norte\n"
            "2. Martes 15 de septiembre, 09:00, Sede Norte\n"
            "3. Miércoles 16 de septiembre, 09:00, Sede Norte"
        ),
    }

    respuesta = _procesar_intento_de_codigo(gateway, ref, "no entendi nada")
    assert _no_es_solo_numero_suelto(respuesta), f"la aclaración del wizard NO repitió la lista: {respuesta!r}"
    assert "14 de septiembre" in respuesta.lower()


# ---------------------------------------------------------------------
# 5. Control: selección de SERVICIO ya funcionaba bien desde antes
#    (recado 034/036) — confirma que no se rompió al tocar el resto.
# ---------------------------------------------------------------------
def test_aclaracion_de_servicio_ya_repetia_la_lista_sin_cambios():
    from domains.health.appointment_service import MockAppointmentService as _MAS

    class _DosServicios(_MAS):
        def _seed_fictional_data(self) -> None:
            self._catalogo_servicios = ["Medicina General", "Odontologia"]
            self._slots["MG-1"] = AvailabilitySlot(
                slot_id="MG-1", service="Medicina General", professional="Dr. Ruiz",
                location="Sede Norte", date="2026-09-14", time="09:00",
            )
            self._slots["ODO-1"] = AvailabilitySlot(
                slot_id="ODO-1", service="Odontologia", professional="Dr. Ruiz",
                location="Sede Norte", date="2026-09-15", time="09:00",
            )

    gateway = build_health_gateway(MockActivitySource(), _DosServicios(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-070-ACLARA-SERVICIO"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, ref, "demo", "m2", "no se cual quiero")
    assert _no_es_solo_numero_suelto(r2)
    assert "medicina general" in r2.lower() and "odontologia" in r2.lower()
