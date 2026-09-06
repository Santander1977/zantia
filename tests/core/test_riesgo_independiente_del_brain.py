"""
Recado 037, Parte 4 — la detección de riesgo (`detect_risk_keywords`)
es una capa DETERMINISTA, independiente del Brain conversacional (004,
sección 2.3) — este archivo confirma que sigue funcionando incluso
cuando el Brain FALLA (lanza una excepción), no solo cuando responde
con éxito.

Hallazgo real de esta sesión: antes de este cambio,
`core/orchestrator.py:handle_message` calculaba
`riesgo_detectado = detect_risk_keywords(text)` DESPUÉS de invocar
`self._brain.interpret(...)` — si el Brain hubiera lanzado una
excepción (network/API real, todavía no conectado — pero ya posible
hoy con cualquier Brain custom), la detección de riesgo nunca se
habría ejecutado, y el mensaje se habría perdido en un crash sin
escalar, en vez de tratarse como riesgo. Corregido reordenando el
cálculo ANTES de invocar al Brain, y envolviendo la llamada al Brain
en un try/except que escala (urgente si había riesgo, estándar si no)
en vez de propagar la excepción sin control.
"""
import uuid

import pytest

from core.agent_contract import AgentDefinition, build_orchestrator
from state.models import ConversationState
from state.models import FaseActual
from memory.conversation_memory import Turn
from typing import List


def _nuevo_id() -> str:
    return str(uuid.uuid4())


class _BrainQueSiempreFalla:
    """Doble de prueba que simula un Brain real fallando (ej. timeout
    de red, error de API, JSON inválido) — nunca falla en producción
    real con FakeBrain/HealthBrain (deterministas), pero SÍ podría
    fallar con un futuro Brain basado en LLM (todavía no conectado)."""

    def interpret(self, message: str, state: ConversationState, recent_turns: List[Turn]):
        raise RuntimeError("fallo simulado de un Brain real (network/API)")


def _orchestrator_con_brain_que_falla():
    definition = AgentDefinition(name="test-riesgo", domain="test", brain=_BrainQueSiempreFalla())
    return build_orchestrator(definition)


def test_mensaje_de_riesgo_escala_urgente_aunque_el_brain_falle():
    orchestrator = _orchestrator_con_brain_que_falla()
    conv = f"conv-{_nuevo_id()}"

    resultado = orchestrator.handle_message(conv, "demo", _nuevo_id(), "es una emergencia, ayuda")

    assert resultado.escalated
    assert resultado.state.fase_actual == FaseActual.ESCALADO_URGENTE
    assert resultado.state.senal_de_urgencia is True


def test_mensaje_sin_riesgo_escala_estandar_si_el_brain_falla_en_vez_de_crashear():
    orchestrator = _orchestrator_con_brain_que_falla()
    conv = f"conv-{_nuevo_id()}"

    # No debe lanzar ninguna excepción hacia quien llama — el fallo del
    # Brain se convierte en un escalamiento estándar, nunca en un crash.
    resultado = orchestrator.handle_message(conv, "demo", _nuevo_id(), "hola, quiero información")

    assert resultado.escalated
    assert resultado.state.fase_actual == FaseActual.ESCALADO_ESTANDAR
    assert resultado.state.senal_de_urgencia is False


def test_fallo_del_brain_queda_auditado_en_eventlog():
    orchestrator = _orchestrator_con_brain_que_falla()
    conv = f"conv-{_nuevo_id()}"
    orchestrator.handle_message(conv, "demo", _nuevo_id(), "hola")

    from observability.events import EventType

    eventos_error = [e for e in orchestrator.events.for_conversation(conv) if e.type == EventType.ERROR]
    assert any("Brain.interpret()" in e.payload.get("detalle", "") for e in eventos_error)
