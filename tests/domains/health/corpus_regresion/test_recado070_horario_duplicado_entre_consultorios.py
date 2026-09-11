"""
Recado 070 (parte 3) — hallazgo real, encontrado ejecutando el código
REAL contra el hrmm-backend de PRODUCCIÓN (no contra un catálogo
ficticio): para "Medicina General" el viernes 11 de septiembre de 2026,
dos médicos reales distintos ofrecen la MISMA hora (07:30) en
consultorios distintos (Consultorio 1 y Consultorio 2).

Contra ese dato real, los mensajes de ACLARACIÓN de horario (tanto "no
identificado" como "ambigüedad genuina") mostraban líneas IDÉNTICAS:

    No logré identificar cuál prefieres:
    1. 07:00
    2. 07:30
    3. 07:30
    ¿me confirmas si es la 1, la 2 o la 3?

— imposible de distinguir cuál era cuál. Esto NUNCA se reprodujo contra
el catálogo ficticio de los tests existentes (`MockAppointmentService`
por defecto, y la mayoría de los fixtures de este proyecto) porque
ninguno tenía dos horas reales idénticas en consultorios distintos.

Causa raíz: `datos["horas_ofrecidas"]` (usada para reconstruir la lista
en la aclaración) es solo la hora, sin consultorio — a diferencia de la
oferta ORIGINAL (`_ofrecer_horarios`), que SÍ incluye el consultorio en
cada línea cuando hay más de una ubicación real entre las opciones.

Corrección: se guarda además `horas_display_ofrecidas` (SIEMPRE con
consultorio) y `texto_horario_ofrecido` (el texto YA renderizado de la
oferta original) — las aclaraciones reutilizan estos, nunca reconstruyen
una versión empobrecida.

Hallazgo adicional de CORRECTITUD (no solo de presentación): el camino
asistido por LLM (recado 052) usaba la hora bare como "id" de selección
— con horas repetidas, un id duplicado rompe la garantía de
`core.selection.interpret_selection` de identificar una ÚNICA opción
real. Corregido para usar el `slot_id` real (siempre único) como id.
"""
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import HealthBrain
from domains.health.models import Activity
from state.models import ConversationState


class _CatalogoConHorarioDuplicadoEntreConsultorios(MockAppointmentService):
    """Reproduce EXACTAMENTE el dato real confirmado contra hrmm-backend
    producción el 2026-09-10: Medicina General, viernes 11 de
    septiembre, 3 bloques — 07:00 (Consultorio 2), 07:30 (Consultorio
    2), 07:30 (Consultorio 1). La hora 07:30 aparece DOS VECES."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["Medicina General"]
        datos = [
            ("MG-1", "07:00", "Consultorio 2"),
            ("MG-2", "07:30", "Consultorio 2"),
            ("MG-3", "07:30", "Consultorio 1"),
        ]
        for slot_id, hora, consultorio in datos:
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="Medicina General", professional="Dr. Real",
                location=consultorio, date="2026-09-11", time=hora,
            )


def _datos_horario_ofrecido():
    activity = Activity(
        activity_id="ACT-070-DUP", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="Medicina General",
    )
    brain = HealthBrain(lambda: activity, _CatalogoConHorarioDuplicadoEntreConsultorios())
    salida = brain._ofrecer_horarios({"servicio_elegido": "Medicina General", "fecha_elegida": "2026-09-11"})
    return brain, salida


def test_oferta_original_desambigua_con_consultorio():
    _, salida = _datos_horario_ofrecido()
    assert "07:00 en Consultorio 2" in salida.respuesta_propuesta
    assert "07:30 en Consultorio 2" in salida.respuesta_propuesta
    assert "07:30 en Consultorio 1" in salida.respuesta_propuesta


def test_aclaracion_no_identificada_repite_lista_desambiguada_con_consultorio():
    brain, salida = _datos_horario_ofrecido()
    datos = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    respuesta = brain._interpretar_horario("no se cual prefiero, tu que me recomiendas", datos)
    assert "1. 07:00 en Consultorio 2" in respuesta.respuesta_propuesta
    assert "2. 07:30 en Consultorio 2" in respuesta.respuesta_propuesta
    assert "3. 07:30 en Consultorio 1" in respuesta.respuesta_propuesta


def test_ambiguedad_genuina_desambigua_con_consultorio():
    brain, salida = _datos_horario_ofrecido()
    datos = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    respuesta = brain._interpretar_horario("07:30", datos)
    assert "07:30 en Consultorio 2" in respuesta.respuesta_propuesta
    assert "07:30 en Consultorio 1" in respuesta.respuesta_propuesta
    # Control explícito: NUNCA 2 líneas idénticas (el bug real
    # reportado) — cada línea de la lista debe ser única.
    lineas_lista = [
        l for l in respuesta.respuesta_propuesta.splitlines() if l.strip().startswith(("1.", "2.", "3."))
    ]
    assert len(lineas_lista) == len(set(lineas_lista)), (
        f"la lista de aclaración tiene líneas duplicadas, indistinguibles: {lineas_lista!r}"
    )


def test_ordinal_sigue_reservando_el_horario_correcto_pese_a_la_duplicidad():
    """Control: aunque dos horas sean idénticas, elegir por ORDINAL
    (nunca ambiguo, es posicional) sigue resolviendo al slot_id real
    correcto — el hallazgo es solo de PRESENTACIÓN/id de selección
    asistida, nunca de la resolución determinista por ordinal."""
    brain, salida = _datos_horario_ofrecido()
    datos = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    respuesta = brain._interpretar_horario("3", datos)
    assert respuesta.tool_requerida["params"]["slot_id"] == "MG-3"
