"""
Conversación normal end-to-end, e interrupción prioritaria (sección 28
del prompt maestro) — reproduce, con lenguaje genérico no médico, los
dos ejemplos completos de 004 sección 18 (flujo normal /
interrupción de seguridad), para trazabilidad directa con la
arquitectura ya diseñada en papel.
"""
import uuid

from state.models import FaseActual


def _nuevo_id():
    return str(uuid.uuid4())


def test_conversacion_normal_de_extremo_a_extremo(orchestrator):
    conv = f"conv-{_nuevo_id()}"

    r1 = orchestrator.handle_message(conv, "demo", _nuevo_id(), "quiero programar un evento")
    assert r1.state.fase_actual == FaseActual.IDENTIFICACION_DE_INTENCION
    assert not r1.escalated

    r2 = orchestrator.handle_message(conv, "demo", _nuevo_id(), "reunión de equipo")
    assert r2.state.fase_actual == FaseActual.RECOPILACION_DE_DATOS
    assert r2.state.datos_recopilados.get("evento") == "reunión de equipo"

    # El consentimiento se otorga fuera del flujo conversacional (p. ej.
    # una casilla de un formulario) — deliberadamente no modelado por
    # FakeBrain, para mantener el demo enfocado en la mecánica del Core.
    estado_actual = orchestrator.store.get(conv)
    orchestrator.store.save(
        estado_actual.model_copy(update={"consentimiento_datos": True}),
        expected_version=estado_actual.version,
    )

    r3 = orchestrator.handle_message(conv, "demo", _nuevo_id(), "mañana a las 10")
    assert not r3.escalated
    assert r3.state.datos_recopilados.get("fecha") == "mañana a las 10"
    # Recado 037, Parte 3: antes de ejecutar la tool WRITE, FakeBrain
    # ahora exige una confirmación estructurada explícita (sí/no) —
    # `ConfirmacionEstructuradaRequeridaParaWriteGuardrail` bloquearía
    # "schedule_event" si se propusiera sin este paso.
    assert "confirmas" in r3.response.lower()
    assert r3.state.herramientas_utilizadas == []

    r4 = orchestrator.handle_message(conv, "demo", _nuevo_id(), "sí")
    assert not r4.escalated
    assert r4.state.fase_actual == FaseActual.RESPUESTA
    assert r4.state.resultado_de_herramientas.get("schedule_event", {}).get("confirmado") is True
    assert len(r4.state.herramientas_utilizadas) == 1
    assert r4.state.herramientas_utilizadas[0]["tool"] == "schedule_event"

    eventos_tool = [e for e in orchestrator.events.for_conversation(conv) if e.type.value == "TOOL_INVOKED"]
    assert len(eventos_tool) == 1


def test_interrupcion_prioritaria_por_riesgo(orchestrator):
    """Reproduce 004 sección 18, ejemplo 2 — con palabra clave genérica
    en vez de contenido médico (prompt maestro, sección 27)."""
    conv = f"conv-{_nuevo_id()}"

    resultado = orchestrator.handle_message(
        conv, "demo", _nuevo_id(), "quiero programar un evento, es urgente"
    )

    assert resultado.escalated
    assert resultado.state.fase_actual == FaseActual.ESCALADO_URGENTE
    assert resultado.state.senal_de_urgencia is True
    assert resultado.state.necesidad_de_escalar is True
    # Nunca promete contacto ni tiempo (lección de Dani, 002):
    for frase_prohibida in ("te contactamos", "te llamamos", "en 10 minutos"):
        assert frase_prohibida not in resultado.response.lower()


def test_riesgo_gana_sobre_cualquier_otra_intencion_simultanea(orchestrator):
    """004 sección 7: ante señal de riesgo simultánea con cualquier otra
    intención (agendar, tool disponible, dato faltante, pedir humano),
    gana siempre el riesgo."""
    conv = f"conv-{_nuevo_id()}"
    resultado = orchestrator.handle_message(
        conv,
        "demo",
        _nuevo_id(),
        "quiero programar un evento y hablar con alguien, es una emergencia",
    )
    assert resultado.state.fase_actual == FaseActual.ESCALADO_URGENTE
    # No llegó a pedir datos del evento ni a tocar ninguna tool:
    assert resultado.state.herramientas_utilizadas == []


def test_conversacion_no_se_reprocesa_tras_escalado_urgente(orchestrator):
    conv = f"conv-{_nuevo_id()}"
    orchestrator.handle_message(conv, "demo", _nuevo_id(), "es una emergencia")

    siguiente = orchestrator.handle_message(conv, "demo", _nuevo_id(), "hola de nuevo")
    assert siguiente.escalated
    assert "no puede continuar de forma" in siguiente.response.lower()
