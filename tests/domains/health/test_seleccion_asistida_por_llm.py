"""
Recado 052 — conexión del mecanismo genérico de Core
(`core/selection.py`) a `HealthBrain._interpretar_fecha`/
`_interpretar_horario`: ÚLTIMO recurso, solo cuando el matching
determinista (ordinal + texto libre específico de fecha/hora, recado
051) no encontró NINGÚN candidato. `domains/health/` solo le pasa al
mecanismo SUS opciones concretas (fechas/horas reales ya ofrecidas este
turno, como texto) — el Core (`core/selection.py`) nunca sabe que son
fechas ni horarios.

Este archivo verifica los 5 puntos pedidos explícitamente:
1. Interpretación exitosa con lenguaje natural variado.
2. El sistema rechaza una interpretación alucinada (no corresponde a
   ninguna opción real) y NO avanza — mismo criterio ya probado a nivel
   de guardrail en `tests/guardrails/test_seleccion_llm_guardrail.py`,
   aquí verificado de extremo a extremo dentro de `HealthBrain`.
3. Fallback correcto cuando no hay LLM disponible (`selection_proposer`
   no configurado, mismo estado que `HEALTH_BRAIN_TYPE=deterministico`)
   — sigue funcionando con la lógica determinista de siempre.
4. La selección verificada produce un `BrainOutput` IDÉNTICO
   (`tool_requerida`, `confirmacion_estructurada_para_write`,
   `propuesta_de_actualizacion_de_estado`) al que produciría el mismo
   paciente si hubiera escrito el ordinal directamente.
5. Al menos 1 prueba real contra la API de Anthropic (gateada, ver
   `ZANTIA_RUN_REAL_LLM_TESTS`, mismo patrón que `test_llm_brain.py`).
"""
import os

import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    accept_activity, build_health_agent_context, contact_patient, handle_patient_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import HealthBrain
from domains.health.models import Activity

_FECHA_LUNES = "2026-09-07"
_FECHA_MARTES = "2026-09-08"
_FECHA_MIERCOLES = "2026-09-09"


class _ServicioTresFechas(MockAppointmentService):
    """Disponibilidad real para las 3 fechas usadas en este archivo —
    `_interpretar_fecha` (camino de ÉXITO) llama a `_ofrecer_horarios`,
    que SÍ consulta `get_availability` de verdad; sin esto, cualquier
    fecha que no sea la sembrada por defecto de `MockAppointmentService`
    (solo 2026-09-05/06/07) caería al "sin horarios disponibles",
    aunque la selección de fecha en sí fuera correcta."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["medicina general"]
        for fecha, hora in ((_FECHA_LUNES, "08:00"), (_FECHA_MARTES, "09:00"), (_FECHA_MIERCOLES, "10:00")):
            slot_id = f"SLOT-{fecha}"
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="medicina general", professional="Dra. Prueba",
                location="Sede Norte", date=fecha, time=hora,
            )


class _ProposerRealistaLenguajeNatural:
    """Simula un LLM real y bien portado: interpreta frases naturales
    variadas usando la lista COMPLETA de opciones entregada (igual que
    lo haría un LLM real con el prompt de `AnthropicSelectionProposer`)
    — nunca vocabulario de dominio, solo posición/orden/texto citado."""

    def propose(self, free_text: str, options):
        texto = free_text.lower()
        if "medio" in texto:
            return options[1].id if len(options) >= 2 else None
        if "primero" in texto or "primera" in texto:
            return options[0].id
        if "ultima" in texto or "última" in texto or "tercera" in texto:
            return options[-1].id
        for o in options:
            if o.text.lower() in texto or texto in o.text.lower():
                return o.id
        return None


class _ProposerQueAlucina:
    """Simula un LLM que propone un id que NUNCA estuvo en la lista de
    opciones reales — exactamente el caso que debe rechazarse."""

    def propose(self, free_text: str, options):
        return "OPCION-QUE-NUNCA-EXISTIO"


def _brain(services, activity_factory, selection_proposer=None):
    activity = services["source"].create(activity_factory())
    return HealthBrain(lambda: activity, _ServicioTresFechas(), selection_proposer=selection_proposer)


def _datos_fecha():
    return {
        "etapa": "esperando_fecha",
        "servicio_elegido": "medicina general",
        "fechas_ofrecidas": [_FECHA_LUNES, _FECHA_MARTES, _FECHA_MIERCOLES],
    }


def _datos_horario():
    return {
        "etapa": "esperando_horario",
        "servicio_elegido": "medicina general",
        "fecha_elegida": _FECHA_LUNES,
        "opciones_horario": ["SLOT-A", "SLOT-B", "SLOT-C"],
        "horas_ofrecidas": ["09:00", "10:30", "14:00"],
    }


# ---------------------------------------------------------------------
# 1. Interpretación exitosa con lenguaje natural variado.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto,fecha_esperada",
    [
        ("la del medio", _FECHA_MARTES),
        ("esa que dijiste primero", _FECHA_LUNES),
        ("la última que mencionaste", _FECHA_MIERCOLES),
    ],
)
def test_interpreta_fecha_con_lenguaje_natural_variado(services, activity_factory, texto, fecha_esperada):
    brain = _brain(services, activity_factory, _ProposerRealistaLenguajeNatural())
    salida = brain._interpretar_fecha(texto, _datos_fecha())
    assert salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]["fecha_elegida"] == fecha_esperada
    # Tras aceptar la fecha, el flujo avanza normalmente al PASO 3
    # (`_ofrecer_horarios`, sin tocar) — igual que si hubiera llegado
    # por ordinal.
    assert "horarios disponibles" in salida.respuesta_propuesta.lower()
    assert salida.verificacion_de_seleccion is not None
    assert salida.verificacion_de_seleccion.id_seleccionado_via_llm == fecha_esperada


def test_interpreta_horario_con_lenguaje_natural_el_lunes_que_mencionaste(services, activity_factory):
    """"el lunes que mencionaste" ya se resuelve en la ETAPA de fecha
    (no de horario) — aquí se prueba el equivalente para horario:
    "la del medio" sobre horas reales."""
    brain = _brain(services, activity_factory, _ProposerRealistaLenguajeNatural())
    salida = brain._interpretar_horario("la del medio", _datos_horario())
    assert salida.tool_requerida["params"]["slot_id"] == "SLOT-B"  # 10:30, la del medio
    assert salida.verificacion_de_seleccion is not None
    # Recado 070 — hallazgo real contra hrmm-backend producción: dos
    # horarios reales pueden compartir la MISMA hora en consultorios
    # distintos, así que la hora bare ("10:30") ya no sirve como
    # identificador único de la selección verificada — ahora se
    # registra el `slot_id` real (siempre único), nunca ambiguo.
    assert salida.verificacion_de_seleccion.id_seleccionado_via_llm == "SLOT-B"


# ---------------------------------------------------------------------
# 2. Rechaza una interpretación alucinada — nunca avanza con una
#    selección inválida.
# ---------------------------------------------------------------------
def test_no_avanza_si_el_llm_alucina_una_opcion_que_no_fue_ofrecida(services, activity_factory):
    brain = _brain(services, activity_factory, _ProposerQueAlucina())
    salida = brain._interpretar_fecha("cualquier cosa que el LLM interprete mal", _datos_fecha())

    # No avanzó: sigue en "esperando_fecha", no se pobló "fecha_elegida".
    datos_resultantes = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos_resultantes.get("etapa", "esperando_fecha") == "esperando_fecha"
    assert "fecha_elegida" not in datos_resultantes
    assert salida.verificacion_de_seleccion is None
    # Mismo mensaje de aclaración de siempre (recado 034) — nunca un error.
    assert salida.tool_requerida is None


def test_no_avanza_ni_reserva_si_el_llm_alucina_un_horario(services, activity_factory):
    brain = _brain(services, activity_factory, _ProposerQueAlucina())
    salida = brain._interpretar_horario("cualquier cosa", _datos_horario())

    datos_resultantes = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos_resultantes.get("etapa") != "reservando"
    assert salida.tool_requerida is None  # nunca se propone book_appointment
    assert salida.verificacion_de_seleccion is None


# ---------------------------------------------------------------------
# 3. Fallback correcto cuando el LLM no está disponible.
# ---------------------------------------------------------------------
def test_sin_selection_proposer_configurado_usa_solo_la_logica_deterministica(services, activity_factory):
    """`HealthBrain` sin `selection_proposer` (default `None`, mismo
    estado que `HEALTH_BRAIN_TYPE=deterministico`) — "la del medio" no
    lo reconoce ninguna forma determinista del recado 051, así que debe
    caer al mensaje de aclaración de siempre, SIN fallar."""
    brain = _brain(services, activity_factory, selection_proposer=None)
    salida = brain._interpretar_fecha("la del medio", _datos_fecha())

    assert salida.respuesta_propuesta.strip() != ""  # nunca deja al paciente sin respuesta
    datos_resultantes = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert "fecha_elegida" not in datos_resultantes
    assert salida.verificacion_de_seleccion is None


def test_ordinal_y_texto_exacto_del_recado_051_nunca_llaman_al_proposer(services, activity_factory):
    """El determinista sigue siendo SIEMPRE el primer intento — ni
    ordinal ni texto exacto deben gastar una llamada al LLM."""
    llamadas = []

    class _ProposerQueRegistraLlamadas:
        def propose(self, free_text, options):
            llamadas.append(free_text)
            return None

    brain = _brain(services, activity_factory, _ProposerQueRegistraLlamadas())
    brain._interpretar_fecha("1", _datos_fecha())  # ordinal
    brain._interpretar_fecha("lunes", _datos_fecha())  # texto exacto (recado 051)
    assert llamadas == []


# ---------------------------------------------------------------------
# 4. Selección verificada produce un BrainOutput IDÉNTICO al del
#    ordinal — la garantía central pedida por el usuario.
# ---------------------------------------------------------------------
def test_seleccion_via_llm_produce_decision_identica_a_elegir_por_ordinal(services, activity_factory):
    # MISMA Activity (mismo `activity_id`/`patient_reference`) para
    # ambos Brains — de lo contrario `idempotency_key`/`patient_reference`
    # en `tool_requerida` divergirían por construcción, sin relación con
    # el mecanismo bajo prueba.
    activity = services["source"].create(activity_factory("ACT-052-IDENTICO", patient_reference="PAC-052-IDENTICO"))
    servicio = _ServicioTresFechas()
    brain_ordinal = HealthBrain(lambda: activity, servicio, selection_proposer=None)
    brain_llm = HealthBrain(lambda: activity, servicio, selection_proposer=_ProposerRealistaLenguajeNatural())

    salida_ordinal = brain_ordinal._interpretar_horario("2", _datos_horario())  # segunda opción -> SLOT-B
    salida_llm = brain_llm._interpretar_horario("la del medio", _datos_horario())  # misma opción, en lenguaje libre

    assert salida_llm.tool_requerida == salida_ordinal.tool_requerida
    assert (
        salida_llm.confirmacion_estructurada_para_write
        == salida_ordinal.confirmacion_estructurada_para_write
        == True  # noqa: E712 — explícito a propósito
    )
    # Único campo que difiere a propósito: `verificacion_de_seleccion`
    # (solo lo pobla el camino asistido por LLM) — todo lo demás,
    # incluida la actualización de estado propuesta, es idéntico.
    assert (
        salida_llm.propuesta_de_actualizacion_de_estado
        == salida_ordinal.propuesta_de_actualizacion_de_estado
    )
    assert salida_ordinal.verificacion_de_seleccion is None
    assert salida_llm.verificacion_de_seleccion is not None


# ---------------------------------------------------------------------
# Extra — de extremo a extremo por el Orchestrator + GuardrailEngine
# REALES (no solo llamando a `HealthBrain` directo, como los tests de
# arriba): confirma que `verificacion_de_seleccion` de verdad llega
# hasta `SeleccionAsistidaPorLLMNoVerificadaGuardrail` (Core) a través
# de `core/orchestrator.py`, y que una selección legítima asistida por
# LLM NUNCA se bloquea en el camino real.
# ---------------------------------------------------------------------
def test_de_extremo_a_extremo_por_el_orchestrator_y_guardrails_reales():
    source = MockActivitySource()
    activity = source.create(Activity(
        activity_id="ACT-052-E2E", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference="PAC-052-E2E", patient_contact={"nombre": "Prueba"}, service="medicina general",
    ))
    context = build_health_agent_context(
        activity, source, _ServicioTresFechas(), ReminderManager(), MockActivityResultSink()
    )
    # Swap post-construcción del Brain determinista por defecto por uno
    # CON `selection_proposer` — mismo objeto `appointment_service`, sin
    # tocar el `AgentDefinition`/`ToolRegistry` ya armados (el Core
    # relee `self._brain` en cada `handle_message`, nunca lo cachea en
    # otro lado — ver `core/orchestrator.py`).
    context.orchestrator._brain = HealthBrain(
        lambda: context.activity, _ServicioTresFechas(), selection_proposer=_ProposerRealistaLenguajeNatural()
    )
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "sí")
    assert "fechas disponibles" in r1.lower()

    r2 = handle_patient_message(context, "m2", "la del medio, por favor")
    assert "horarios disponibles" in r2.lower(), (
        f"el guardrail no debía bloquear una selección asistida por LLM verificada: {r2!r}"
    )
    estado = context.orchestrator.store.get(context.activity.activity_id)
    assert estado.datos_recopilados.get("fecha_elegida") == _FECHA_MARTES


# ---------------------------------------------------------------------
# 5. Prueba de integración REAL — DESHABILITADA por defecto (mismo
#    patrón que `test_llm_brain.py`, recado 038).
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)
def test_seleccion_asistida_por_llm_contra_la_api_real(services, activity_factory):
    from core.selection import AnthropicSelectionProposer

    brain = _brain(services, activity_factory, AnthropicSelectionProposer())
    salida = brain._interpretar_fecha("la del medio, por favor", _datos_fecha())

    datos_resultantes = salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos_resultantes.get("fecha_elegida") == _FECHA_MARTES, (
        f"Claude real no interpretó 'la del medio' como {_FECHA_MARTES}: {salida!r}"
    )
    assert salida.verificacion_de_seleccion is not None
    assert salida.verificacion_de_seleccion.id_seleccionado_via_llm == _FECHA_MARTES
