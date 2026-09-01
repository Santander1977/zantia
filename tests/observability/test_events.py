"""Observabilidad: transiciones, tools y bloqueos de guardrail quedan
registrados como eventos (004, sección 13; prompt maestro, sección 15)."""
import uuid

from observability.events import EventType


def _nuevo_id():
    return str(uuid.uuid4())


def test_se_registran_eventos_de_transicion_y_guardrail(orchestrator):
    conv = f"conv-{_nuevo_id()}"
    orchestrator.handle_message(conv, "demo", _nuevo_id(), "hola")

    eventos = orchestrator.events.for_conversation(conv)
    tipos = {e.type for e in eventos}
    assert EventType.STATE_TRANSITION in tipos
    assert EventType.GUARDRAIL_DECISION in tipos


def test_bloqueo_de_guardrail_queda_registrado(orchestrator):
    conv = f"conv-{_nuevo_id()}"
    orchestrator.handle_message(conv, "demo", _nuevo_id(), "quiero programar un evento")
    orchestrator.handle_message(conv, "demo", _nuevo_id(), "reunión")
    # Sin otorgar consentimiento: al llegar el último dato, la tool WRITE
    # debe bloquearse y quedar auditado.
    orchestrator.handle_message(conv, "demo", _nuevo_id(), "mañana")

    eventos = orchestrator.events.for_conversation(conv)
    decisiones = [e for e in eventos if e.type == EventType.GUARDRAIL_DECISION]
    assert any(e.payload["decision"] == "BLOCK" for e in decisiones)
