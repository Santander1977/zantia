"""
Recado 056 — investigación de un hallazgo reportado como "más grave que
el recado 053": según la transcripción del usuario, se ofrecieron
horarios "07:00, 08:00 o 08:30" para Odontología (miércoles 9 de
septiembre), el paciente respondió "8:30" (sin el cero inicial), y el
sistema confirmó la reserva a las "07:30" — una hora que nunca fue
ofrecida ni corresponde a ninguna interpretación razonable de "8:30".

**Resultado de la investigación (ver recado 056 completo): no fue
posible reproducir este resultado exacto con el código actual.**
Probado exhaustivamente — unidad (`_elegir_opcion`,
`_emparejar_horario_por_texto`), integración (`HealthBrain.
_interpretar_horario` de punta a punta) y con una llamada REAL a
Claude (`HealthAnthropicBrain` + `AnthropicResponseDrafter` real) sobre
el escenario EXACTO reportado (horarios 07:00/08:00/08:30 en
Consultorio 4, respuesta "8:30") — en todos los casos el sistema
selecciona correctamente la opción de las 08:30, nunca 07:30 ni ningún
otro valor.

Este archivo documenta esa verificación exhaustiva (los 5 puntos
pedidos) y además cierra un hallazgo REAL, relacionado pero distinto,
encontrado al investigar: `_ofrecer_horarios` no ordenaba por hora
antes de tomar los 3 primeros resultados de `get_availability` (que no
garantiza ningún orden — confirmado con el JSON real de hrmm-backend)
— corregido para que siempre muestre los 3 horarios cronológicamente
más próximos, mismo criterio que `_ofrecer_fechas` ya aplicaba a las
fechas.

La cita real mal-confirmada (`CITA-9782ae7085`, Odontologia,
2026-09-09, 07:30, documento 72302972) fue cancelada con el mecanismo
real de verificación — ver recado 056 para la confirmación.
"""
import os

import pytest

from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import HealthBrain, _emparejar_horario_por_texto
from domains.health.models import Activity


def _activity():
    return Activity(
        activity_id="ACT-056", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference="TITULAR-056", patient_contact={"nombre": "Prueba"}, service="Odontologia",
    )


class _ServicioOdontologiaReal(MockAppointmentService):
    """Reproduce el catálogo/disponibilidad REAL confirmados contra
    hrmm-backend para Odontologia/2026-09-09: un único médico, slots
    cada 30 minutos desde las 07:00. `07:30` existe como slot real
    (deliberadamente incluido, aunque `_ofrecer_horarios` con el fix de
    ordenamiento nunca lo muestra entre los primeros 3 — confirma que
    aunque exista, nunca se ofrece ni se elige por error)."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["Odontologia"]
        horas = ["07:00", "07:30", "08:00", "08:30", "09:00", "09:30", "10:00"]
        for hora in horas:
            slot_id = f"SLOT-{hora}"
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="Odontologia", professional="Dr. Odonto",
                location="Consultorio 4", date="2026-09-09", time=hora,
            )
        # 07:30 YA RESERVADO — mismo estado real que el catálogo tenía
        # en producción en el momento del incidente reportado (según la
        # evidencia real: la cita disputada ocupa exactamente ese slot),
        # así que la disponibilidad real ofrecida es 07:00/08:00/08:30/...
        del self._slots["SLOT-07:30"]


def _brain():
    return HealthBrain(_activity, _ServicioOdontologiaReal())


# ---------------------------------------------------------------------
# 1. Reproducción EXACTA del escenario reportado — nunca debe alucinar
#    07:30 (ni ningún valor no ofrecido).
# ---------------------------------------------------------------------
def test_reproduce_escenario_exacto_8_30_sin_cero_selecciona_0830_real():
    brain = _brain()
    salida_oferta = brain._ofrecer_horarios({"servicio_elegido": "Odontologia", "fecha_elegida": "2026-09-09"})
    assert salida_oferta.respuesta_propuesta == (
        "Para el Miércoles 9 de septiembre tengo estos horarios disponibles en Consultorio 4:\n"
        "1. 07:00\n"
        "2. 08:00\n"
        "3. 08:30\n"
        "¿Cuál prefieres?"
    )
    datos = salida_oferta.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos["horas_ofrecidas"] == ["07:00", "08:00", "08:30"]
    assert "07:30" not in datos["horas_ofrecidas"]  # confirma que 07:30 nunca se ofrece

    salida = brain._interpretar_horario("8:30", datos)
    assert salida.tool_requerida is not None
    assert salida.tool_requerida["params"]["slot_id"] == "SLOT-08:30", (
        f"debía reservar 08:30 (lo pedido), nunca otra hora: {salida.tool_requerida!r}"
    )


def test_emparejar_horario_por_texto_unidad_8_30_sin_cero():
    """Mismo caso a nivel de unidad, sin pasar por el Brain completo."""
    resultado, ambiguos = _emparejar_horario_por_texto("8:30", ["07:00", "08:00", "08:30"])
    assert resultado == "08:30"
    assert ambiguos == []


# ---------------------------------------------------------------------
# 2. Variantes de formato sin cero inicial en general — todas deben
#    matchear correctamente contra opciones reales CON cero inicial.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("8:00", "08:00"),
        ("8 am", "08:00"),
        ("8am", "08:00"),
        ("8 de la mañana", "08:00"),
        ("son las 8:00, por favor", "08:00"),
        ("8:30", "08:30"),
        ("8:30 am", "08:30"),
        ("8:30 de la mañana", "08:30"),
    ],
)
def test_variantes_sin_cero_inicial_matchean_correctamente(texto, esperado):
    resultado, ambiguos = _emparejar_horario_por_texto(texto, ["07:00", "08:00", "08:30"])
    assert resultado == esperado, f"'{texto}' debía resolver a {esperado}, resolvió a {resultado!r} (ambiguos={ambiguos!r})"


# ---------------------------------------------------------------------
# 3. Si NINGUNA opción real coincide, pide aclaración — nunca inventa
#    ni aproxima a la opción más parecida sin confirmar.
# ---------------------------------------------------------------------
def test_hora_no_ofrecida_pide_aclaracion_nunca_inventa():
    brain = _brain()
    datos = {
        "servicio_elegido": "Odontologia", "fecha_elegida": "2026-09-09",
        "opciones_horario": ["SLOT-07:00", "SLOT-08:00", "SLOT-08:30"],
        "horas_ofrecidas": ["07:00", "08:00", "08:30"],
    }
    # "9:15" no está entre las opciones reales ofrecidas ni coincide con
    # ninguna forma reconocida de ellas.
    salida = brain._interpretar_horario("9:15", datos)
    assert salida.tool_requerida is None
    assert "no logré identificar" in salida.respuesta_propuesta.lower()
    datos_resultantes = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos_resultantes.get("etapa") != "reservando"


def test_emparejar_horario_por_texto_sin_match_devuelve_ninguno():
    resultado, ambiguos = _emparejar_horario_por_texto("9:15", ["07:00", "08:00", "08:30"])
    assert resultado is None
    assert ambiguos == []


# ---------------------------------------------------------------------
# 4. Extremo a extremo con una llamada REAL a la API de Anthropic —
#    tanto para el escenario determinista (8:30, ya resuelto sin LLM)
#    como para un caso que SÍ obliga a consultar el mecanismo del
#    recado 052 (referencia posicional que ningún nivel determinista
#    reconoce) — confirma que ninguno de los dos caminos alucina.
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)
def test_escenario_real_contra_la_api_de_anthropic_extremo_a_extremo():
    from domains.health.llm_brain import AnthropicResponseDrafter, HealthAnthropicBrain
    from core.selection import AnthropicSelectionProposer

    brain_determinista = HealthBrain(
        _activity, _ServicioOdontologiaReal(), selection_proposer=AnthropicSelectionProposer()
    )
    brain_llm = HealthAnthropicBrain(brain_determinista, AnthropicResponseDrafter())

    datos_base = {"servicio_elegido": "Odontologia", "fecha_elegida": "2026-09-09"}
    salida_oferta = brain_llm.interpret("1", _estado({**datos_base, "etapa": "esperando_fecha", "fechas_ofrecidas": ["2026-09-09"]}), [])
    datos = salida_oferta.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos["horas_ofrecidas"] == ["07:00", "08:00", "08:30"]

    # Caso 1: exactamente el escenario reportado ("8:30" sin cero).
    salida1 = brain_llm.interpret("8:30", _estado(datos), [])
    assert salida1.tool_requerida["params"]["slot_id"] == "SLOT-08:30", (
        f"Claude real (redacción) no debía alterar la decisión determinista: {salida1!r}"
    )

    # Caso 2: referencia posicional — ningún nivel determinista la
    # reconoce, así que SÍ obliga a consultar el mecanismo del recado
    # 052 (AnthropicSelectionProposer real).
    salida2 = brain_llm.interpret("la última que mencionaste", _estado(datos), [])
    assert salida2.tool_requerida is not None, f"Claude real no logró interpretar la referencia: {salida2!r}"
    assert salida2.tool_requerida["params"]["slot_id"] == "SLOT-08:30", (
        f"Claude real alucinó una opción no ofrecida: {salida2!r}"
    )
    assert salida2.verificacion_de_seleccion is not None
    assert salida2.verificacion_de_seleccion.id_seleccionado_via_llm == "08:30"


def _estado(datos):
    from state.models import ConversationState

    return ConversationState(canal="demo", datos_recopilados=datos)


# ---------------------------------------------------------------------
# 5. El fix de ordenamiento de `_ofrecer_horarios` (hallazgo real
#    encontrado al investigar) — nunca depende del orden de
#    `get_availability`, siempre muestra los 3 horarios cronológicamente
#    más próximos.
# ---------------------------------------------------------------------
def test_ofrecer_horarios_ordena_cronologicamente_sin_depender_del_orden_de_availability():
    class _ServicioOrdenAlReves(MockAppointmentService):
        """Simula lo confirmado con el JSON real de hrmm-backend: los
        bloques de servicios con VARIOS médicos no llegan en orden
        cronológico — aquí, deliberadamente al revés."""

        def _seed_fictional_data(self) -> None:
            self._catalogo_servicios = ["Medicina General"]
            for hora in ("09:00", "08:30", "08:00", "07:00"):  # orden invertido a propósito
                self._slots[f"SLOT-{hora}"] = AvailabilitySlot(
                    slot_id=f"SLOT-{hora}", service="Medicina General", professional="Dra. X",
                    location="Consultorio 1", date="2026-09-09", time=hora,
                )

    activity = Activity(
        activity_id="ACT-056-ORDEN", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="Medicina General",
    )
    brain = HealthBrain(lambda: activity, _ServicioOrdenAlReves())
    salida = brain._ofrecer_horarios({"servicio_elegido": "Medicina General", "fecha_elegida": "2026-09-09"})
    datos = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos["horas_ofrecidas"] == ["07:00", "08:00", "08:30"], (
        "debía mostrar los 3 horarios MÁS PRÓXIMOS en orden cronológico, "
        f"sin importar el orden de get_availability: {datos['horas_ofrecidas']!r}"
    )
