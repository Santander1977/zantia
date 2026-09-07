"""
Recado 054 — pedido explícito del usuario: TODOS los listados que
ZANTIA presenta al paciente se muestran como lista numerada, una opción
por línea (salto de línea REAL) — nunca como texto corrido separado por
comas/punto y coma. 4 lugares en `domains/health/brain.py` (catálogo,
fechas, horarios, consultar mis citas) + el duplicado en
`domains/health/gateway.py:_resolver_consulta` (mismo texto, alcanzado
desde primer contacto sin conversación abierta — corregido para que el
paciente vea siempre el mismo formato sin importar por cuál camino
llegó).

Este archivo verifica los 5 puntos pedidos explícitamente.
"""
import os

import pytest

from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import HealthBrain, _lista_numerada
from domains.health.models import Activity


def _activity():
    return Activity(
        activity_id="ACT-054", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference="TITULAR-054", patient_contact={"nombre": "Prueba"}, service="medicina general",
    )


class _ServicioMultiple(MockAppointmentService):
    """5 servicios reales (mismo catálogo real de hrmm-backend, sin
    tildes — confirmado en recados anteriores), con disponibilidad
    controlada para fecha/horario."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["Medicina General", "Odontologia", "Pediatria", "Psicologia", "Urgencias"]
        datos = [
            ("Medicina General", "Dra. A", "Consultorio 2", "2026-09-07", "07:00"),
            ("Medicina General", "Dra. A", "Consultorio 2", "2026-09-08", "08:00"),
            ("Medicina General", "Dra. A", "Consultorio 2", "2026-09-09", "09:00"),
        ]
        for servicio, prof, sede, fecha, hora in datos:
            slot_id = f"{servicio}-{fecha}"
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service=servicio, professional=prof, location=sede, date=fecha, time=hora,
            )


def _brain(servicio=None):
    return HealthBrain(_activity, servicio or _ServicioMultiple())


# ---------------------------------------------------------------------
# 1. Los 4 lugares — formato de lista numerada con salto de línea real.
# ---------------------------------------------------------------------
def test_lugar1_catalogo_lista_numerada():
    brain = _brain()
    salida = brain._ofrecer_catalogo_servicios({})
    assert salida.respuesta_propuesta == (
        "Claro, estas son las opciones disponibles:\n"
        "1. Medicina General\n"
        "2. Odontologia\n"
        "3. Pediatria\n"
        "4. Psicologia\n"
        "5. Urgencias\n"
        "¿Para cuál te gustaría agendar?"
    )


def test_lugar2_fechas_lista_numerada():
    brain = _brain()
    salida = brain._ofrecer_fechas({"servicio_elegido": "Medicina General"})
    assert salida.respuesta_propuesta == (
        "Estas son las fechas disponibles:\n"
        "1. Lunes 7 de septiembre\n"
        "2. Martes 8 de septiembre\n"
        "3. Miércoles 9 de septiembre\n"
        "¿Cuál te queda mejor?"
    )


def test_lugar3_horarios_lista_numerada_mismo_consultorio():
    """Las 3 fechas de `_ServicioMultiple` comparten el mismo
    profesional/consultorio para Medicina General — un horario por
    fecha, así que probamos el caso de horarios reales agrupando 3
    slots DISTINTOS del mismo servicio+fecha con un servicio dedicado."""

    class _ServicioTresHorariosMismoConsultorio(MockAppointmentService):
        def _seed_fictional_data(self) -> None:
            self._catalogo_servicios = ["Psicologia"]
            for slot_id, hora in (("A", "07:00"), ("B", "07:30"), ("C", "08:00")):
                self._slots[slot_id] = AvailabilitySlot(
                    slot_id=slot_id, service="Psicologia", professional="Dra. Galindo",
                    location="Consultorio 3", date="2026-09-09", time=hora,
                )

    brain = _brain(_ServicioTresHorariosMismoConsultorio())
    salida = brain._ofrecer_horarios({"servicio_elegido": "Psicologia", "fecha_elegida": "2026-09-09"})
    assert salida.respuesta_propuesta == (
        "Para el Miércoles 9 de septiembre tengo estos horarios disponibles en Consultorio 3:\n"
        "1. 07:00\n"
        "2. 07:30\n"
        "3. 08:00\n"
        "¿Cuál prefieres?"
    )


def test_lugar3_horarios_lista_numerada_consultorios_distintos():
    """Si los profesionales/consultorios DIFIEREN entre las opciones,
    nunca se inventa un consultorio único — se mantiene por línea."""

    class _ServicioDosConsultorios(MockAppointmentService):
        def _seed_fictional_data(self) -> None:
            self._catalogo_servicios = ["Pediatria"]
            self._slots["A"] = AvailabilitySlot(
                slot_id="A", service="Pediatria", professional="Dr. X",
                location="Consultorio 1", date="2026-09-09", time="09:00",
            )
            self._slots["B"] = AvailabilitySlot(
                slot_id="B", service="Pediatria", professional="Dr. Y",
                location="Consultorio 2", date="2026-09-09", time="10:00",
            )

    brain = _brain(_ServicioDosConsultorios())
    salida = brain._ofrecer_horarios({"servicio_elegido": "Pediatria", "fecha_elegida": "2026-09-09"})
    assert salida.respuesta_propuesta == (
        "Para el Miércoles 9 de septiembre, estos son los horarios disponibles:\n"
        "1. 09:00 en Consultorio 1\n"
        "2. 10:00 en Consultorio 2\n"
        "¿Cuál prefieres?"
    )


def test_lugar4_consultar_mis_citas_lista_numerada():
    servicio = _ServicioMultiple()
    slot = servicio.get_availability("Medicina General")[0]
    cita1 = servicio.book_appointment(slot.slot_id, "TITULAR-054", "idem-1")
    servicio.confirm_appointment(cita1.appointment_id)
    slot2 = servicio.get_availability("Medicina General")[0]
    cita2 = servicio.book_appointment(slot2.slot_id, "TITULAR-054", "idem-2")
    servicio.confirm_appointment(cita2.appointment_id)

    brain = _brain(servicio)
    salida = brain.interpret("mis citas", _estado({"etapa": "esperando_servicio"}), [])
    assert salida.respuesta_propuesta.startswith("Aquí tienes tus 2 citas activas:\n1. ")
    assert "\n2. " in salida.respuesta_propuesta
    assert "2026-09" not in salida.respuesta_propuesta  # nunca ISO cruda


def _estado(datos):
    from state.models import ConversationState

    return ConversationState(canal="demo", datos_recopilados=datos)


# ---------------------------------------------------------------------
# 2. Caso de UNA sola opción — sigue en formato de lista, con "1.".
# ---------------------------------------------------------------------
def test_catalogo_una_sola_opcion_sigue_en_formato_lista():
    class _ServicioUnico(MockAppointmentService):
        def _seed_fictional_data(self) -> None:
            self._catalogo_servicios = ["Medicina General"]

    brain = _brain(_ServicioUnico())
    salida = brain._ofrecer_catalogo_servicios({})
    assert salida.respuesta_propuesta == (
        "Claro, estas son las opciones disponibles:\n"
        "1. Medicina General\n"
        "¿Para cuál te gustaría agendar?"
    )


def test_consultar_mis_citas_una_sola_cita_singular_correcto():
    servicio = _ServicioMultiple()
    slot = servicio.get_availability("Medicina General")[0]
    cita = servicio.book_appointment(slot.slot_id, "TITULAR-054", "idem-uno")
    servicio.confirm_appointment(cita.appointment_id)

    brain = _brain(servicio)
    salida = brain.interpret("mis citas", _estado({"etapa": "esperando_servicio"}), [])
    assert salida.respuesta_propuesta.startswith("Aquí tienes tu 1 cita activa:\n1. ")


# ---------------------------------------------------------------------
# 3. Caso VACÍO — mensaje simple, sin forzar una lista vacía.
# ---------------------------------------------------------------------
def test_catalogo_vacio_mensaje_simple_sin_regresion():
    class _SinCatalogo(MockAppointmentService):
        def _seed_fictional_data(self) -> None:
            self._catalogo_servicios = []

    brain = _brain(_SinCatalogo())
    salida = brain._ofrecer_catalogo_servicios({})
    assert salida.respuesta_propuesta == (
        "Por ahora no tengo el catálogo de servicios a la mano — ¿me cuentas qué tipo de atención necesitas?"
    )
    assert "\n" not in salida.respuesta_propuesta


def test_consultar_mis_citas_vacio_mensaje_simple_sin_regresion():
    brain = _brain(_ServicioMultiple())  # sin ninguna cita reservada
    salida = brain.interpret("mis citas", _estado({"etapa": "esperando_servicio"}), [])
    assert salida.respuesta_propuesta == "Revisé y no tienes ninguna cita activa registrada por este canal por ahora."


# ---------------------------------------------------------------------
# 4. `_lista_numerada` — unidad.
# ---------------------------------------------------------------------
def test_lista_numerada_unidad():
    assert _lista_numerada(["A", "B", "C"]) == "1. A\n2. B\n3. C"
    assert _lista_numerada(["Único"]) == "1. Único"
    assert _lista_numerada([]) == ""


# ---------------------------------------------------------------------
# 5. HealthAnthropicBrain preserva el formato de lista — nunca lo
#    reformula en prosa. Al menos 1 prueba real gateada.
# ---------------------------------------------------------------------
class _DrafterQueParafraseaSinTocarLaLista:
    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return f"¡Con gusto! {texto_base}"


def test_healthanthropicbrain_preserva_lista_con_drafter_bien_portado():
    from domains.health.llm_brain import HealthAnthropicBrain

    brain_determinista = _brain()
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueParafraseaSinTocarLaLista())

    salida = brain_llm.interpret("qué servicios tienen", _estado({"etapa": "esperando_decision"}), [])
    assert "1. Medicina General\n2. Odontologia\n3. Pediatria\n4. Psicologia\n5. Urgencias" in salida.respuesta_propuesta


@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)
@pytest.mark.parametrize(
    "mensaje,fragmento_lista",
    [
        ("qué servicios tienen", "1. Medicina General\n2. Odontologia\n3. Pediatria\n4. Psicologia\n5. Urgencias"),
        ("sí", "1. Lunes 7 de septiembre\n2. Martes 8 de septiembre\n3. Miércoles 9 de septiembre"),
    ],
)
def test_healthanthropicbrain_preserva_lista_contra_la_api_real(mensaje, fragmento_lista):
    from domains.health.llm_brain import AnthropicResponseDrafter, HealthAnthropicBrain

    brain_determinista = _brain()
    brain_llm = HealthAnthropicBrain(brain_determinista, AnthropicResponseDrafter())

    etapa = "esperando_decision"
    salida = brain_llm.interpret(mensaje, _estado({"etapa": etapa}), [])
    assert fragmento_lista in salida.respuesta_propuesta, (
        f"Claude real reformuló la lista en prosa (regla 7 del prompt violada): {salida.respuesta_propuesta!r}"
    )
