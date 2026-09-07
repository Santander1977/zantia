"""
Recado 053 — hallazgo real de producción, caso Giselle Tornay
(documento 22669564): se ofrecieron horarios "1) 07:00, 2) 07:30, 3)
08:00" para Psicología. La paciente respondió "7" (ambiguo,
correctamente aclarado entre 07:00/07:30 — nivel 2 del recado 051), y
al confirmar "7:30" el sistema reservó la TERCERA opción real (08:00),
no la que pidió — confirmado con una consulta REAL contra hrmm-backend
(`CITA-af8f98cb8c`, Psicologia, 2026-09-08, 08:00, CONFIRMED).

Causa raíz confirmada con código, no con la hipótesis original del
usuario (que apuntaba a `DatoInventadoGuardrail` verificando contra el
conjunto equivocado de horas): `HealthBrain._elegir_opcion` (el
matcher de ordinal COMPARTIDO por `_interpretar_fecha`/
`_interpretar_horario`/`_interpretar_seleccion_reprogramacion`) usaba
un `in` simple sobre las claves "1"/"2"/"3" — "3" es substring literal
de "7:30" ("7:" + "3" + "0"), así que la respuesta se reinterpretó como
ordinal "3" (índice 2, la tercera opción) ANTES de que
`_emparejar_horario_por_texto` (recado 051) tuviera oportunidad de
reconocer "7:30" como la hora real. Mismo patrón exacto que el bug
"programar"/"reprogramar" del recado 046 (`gateway.py`), nunca
corregido en `_elegir_opcion`.

Nunca fue un problema de `DatoInventadoGuardrail`: la reserva real
quedó consistentemente en 08:00 (texto Y booking coinciden) porque
`_elegir_opcion` decidió mal DESDE ANTES de que existiera ningún texto
que verificar — ningún guardrail puede detectar "se ejecutó
correctamente sobre un valor real, pero no es el que el paciente quiso
decir": eso es un problema de interpretación, no de datos inventados.
"""
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import HealthBrain
from domains.health.models import Activity


# ---------------------------------------------------------------------
# 1. Unidad — `_elegir_opcion` ya no confunde un dígito ordinal que es
#    substring de una hora/fecha con una elección de ordinal real.
# ---------------------------------------------------------------------
def _brain_minimo():
    return HealthBrain(lambda: None, MockAppointmentService())


def test_elegir_opcion_no_confunde_730_con_ordinal_3():
    brain = _brain_minimo()
    assert brain._elegir_opcion("7:30", ["A", "B", "C"]) is None


def test_elegir_opcion_no_confunde_1300_con_ordinal_1():
    brain = _brain_minimo()
    assert brain._elegir_opcion("13:00", ["A", "B", "C"]) is None


def test_elegir_opcion_sigue_reconociendo_el_ordinal_literal():
    """Control positivo — el fix no debe romper el caso real de
    siempre: el paciente escribiendo el número solo."""
    brain = _brain_minimo()
    assert brain._elegir_opcion("1", ["A", "B", "C"]) == "A"
    assert brain._elegir_opcion("2", ["A", "B", "C"]) == "B"
    assert brain._elegir_opcion("3", ["A", "B", "C"]) == "C"
    assert brain._elegir_opcion("la segunda", ["A", "B", "C"]) == "B"
    assert brain._elegir_opcion("opción 3, por favor", ["A", "B", "C"]) == "C"


def test_elegir_opcion_no_confunde_dia_del_mes_13_con_ordinales_1_o_3():
    brain = _brain_minimo()
    assert brain._elegir_opcion("13", ["A", "B", "C"]) is None
    assert brain._elegir_opcion("13 de septiembre", ["A", "B", "C"]) is None


# ---------------------------------------------------------------------
# 2. Reproducción EXACTA del caso real — "7" ambiguo, "7:30" reserva la
#    hora correcta (no la tercera opción).
# ---------------------------------------------------------------------
class _ServicioPsicologiaTresHorarios(MockAppointmentService):
    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["psicologia"]
        for slot_id, hora in (("SLOT-0700", "07:00"), ("SLOT-0730", "07:30"), ("SLOT-0800", "08:00")):
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="psicologia", professional="Dra. Galindo",
                location="Consultorio 6", date="2026-09-08", time=hora,
            )


def test_reproduce_caso_real_giselle_7_ambiguo_luego_730_reserva_la_correcta():
    activity = Activity(
        activity_id="ACT-053-GISELLE", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference="22669564", patient_contact={"nombre": "Giselle"}, service="psicologia",
    )
    brain = HealthBrain(lambda: activity, _ServicioPsicologiaTresHorarios())
    datos = {
        "etapa": "esperando_horario",
        "servicio_elegido": "psicologia",
        "fecha_elegida": "2026-09-08",
        "opciones_horario": ["SLOT-0700", "SLOT-0730", "SLOT-0800"],
        "horas_ofrecidas": ["07:00", "07:30", "08:00"],
    }

    # Turno 1: "7" — ambiguo entre 07:00 y 07:30 (08:00 correctamente excluido).
    salida1 = brain._interpretar_horario("7", datos)
    assert salida1.tool_requerida is None
    assert "07:00" in salida1.respuesta_propuesta and "07:30" in salida1.respuesta_propuesta
    assert "08:00" not in salida1.respuesta_propuesta

    # Turno 2: "7:30" — debe reservar la hora REAL pedida (SLOT-0730),
    # nunca la tercera opción (SLOT-0800, el bug real de producción).
    datos_turno2 = salida1.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    salida2 = brain._interpretar_horario("7:30", datos_turno2)
    assert salida2.tool_requerida is not None
    assert salida2.tool_requerida["params"]["slot_id"] == "SLOT-0730", (
        f"reservó la opción equivocada: {salida2.tool_requerida!r}"
    )
    assert salida2.confirmacion_estructurada_para_write is True
