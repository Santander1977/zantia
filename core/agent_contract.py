"""
Agent Contract (prompt maestro, sección 8): un agente se define por
configuración y componentes propios, no por código nuevo del Core.

    agents/
        agent-x/
            agent definition
            instructions
            tools
            knowledge
            configuration

Esta es la primera versión del "mecanismo que permita registrarlos y
ejecutarlos" pedido explícitamente (sección 8) — todavía no hay
múltiples agentes completos, solo el contrato y un agente demostrativo
(agents/demo/).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.brain import Brain
from core.orchestrator import Orchestrator
from guardrails.base import Guardrail
from guardrails.engine import GuardrailEngine
from knowledge.base import KnowledgeSource
from memory.conversation_memory import ConversationMemory
from observability.events import EventLog
from state.store import StateStore
from tools.base import Tool
from tools.registry import ToolRegistry


@dataclass
class AgentDefinition:
    """Todo lo que hace único a un agente, separado del Core (sección 7:
    'no coloques dentro del Core... herramientas exclusivas de un
    cliente, datos de un proyecto externo')."""

    name: str
    domain: str
    brain: Brain
    tools: List[Tool] = field(default_factory=list)
    knowledge: Optional[KnowledgeSource] = None
    extra_guardrails: List[Guardrail] = field(default_factory=list)
    memory_window: int = 8


def build_orchestrator(definition: AgentDefinition) -> Orchestrator:
    """Ensambla un Orchestrator real a partir de un AgentDefinition —
    el mecanismo de 'registrar y ejecutar' agentes pedido en la sección 8."""
    registry = ToolRegistry()
    for tool in definition.tools:
        registry.register(tool)

    from guardrails.rules import (
        ConsentimientoRequeridoParaWriteGuardrail,
        NoPrometerContactoGuardrail,
        SenalDeUrgenciaNoSePuedeBajarGuardrail,
    )

    reglas_core = [
        SenalDeUrgenciaNoSePuedeBajarGuardrail(),
        ConsentimientoRequeridoParaWriteGuardrail(registry.categories_by_name()),
        NoPrometerContactoGuardrail(),
    ]
    engine = GuardrailEngine(reglas_core + definition.extra_guardrails)

    from state.store import SQLiteStateStore

    store: StateStore = SQLiteStateStore(":memory:")
    memory = ConversationMemory(window_size=definition.memory_window)
    events = EventLog()

    return Orchestrator(
        state_store=store,
        memory=memory,
        brain=definition.brain,
        tool_registry=registry,
        event_log=events,
        guardrail_engine=engine,
    )
