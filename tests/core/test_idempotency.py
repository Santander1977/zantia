"""Idempotencia a nivel de Orchestrator (004, sección 10): el mismo
message_id procesado dos veces no debe duplicar efectos."""
import uuid


def _nuevo_id():
    return str(uuid.uuid4())


def test_mismo_message_id_no_reprocesa(orchestrator):
    conv = f"conv-{_nuevo_id()}"
    msg_id = _nuevo_id()

    r1 = orchestrator.handle_message(conv, "demo", msg_id, "quiero programar un evento")
    r2 = orchestrator.handle_message(conv, "demo", msg_id, "quiero programar un evento")

    assert r1.response == r2.response
    # Solo debió registrarse una transición real de estado por el mismo mensaje
    eventos = orchestrator.events.for_conversation(conv)
    transiciones = [e for e in eventos if e.type.value == "STATE_TRANSITION"]
    assert len(transiciones) == 1


def test_reintento_de_tool_con_misma_idempotency_key_no_duplica(orchestrator):
    """A nivel de tool (no de mensaje): dos invocaciones con la misma
    idempotency_key devuelven el mismo resultado, sin duplicar el
    efecto (ver también tests/tools/test_tools.py)."""
    tool = orchestrator.tools.get("schedule_event")
    r1 = tool.run({"evento": "A", "fecha": "hoy", "idempotency_key": "misma-clave"})
    r2 = tool.run({"evento": "B", "fecha": "mañana", "idempotency_key": "misma-clave"})
    assert r1.data == r2.data
