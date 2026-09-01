"""
Agente demostrativo del Core (prompt maestro, sección 27).

Deliberadamente genérico — NO es un sistema médico, ni de ventas, ni un
CRM. Su único objetivo es demostrar que CONVERSACIÓN + ESTADO + MEMORIA
+ TOOL + GUARDRAIL + OBSERVABILIDAD funcionan juntos de extremo a
extremo, usando datos ficticios (sección 33).
"""
from __future__ import annotations

from core.agent_contract import AgentDefinition, build_orchestrator
from core.brain import FakeBrain
from core.orchestrator import Orchestrator
from knowledge.fixtures import InMemoryKnowledgeSource
from tools.demo_tools import GetDemoInfoTool, NotifyTeamTool, ScheduleEventTool


def build_demo_agent() -> Orchestrator:
    definition = AgentDefinition(
        name="demo",
        domain="demo",
        brain=FakeBrain(),
        tools=[GetDemoInfoTool(), ScheduleEventTool(), NotifyTeamTool()],
        knowledge=InMemoryKnowledgeSource(
            static_data={"info": "agente de demostración del Core de ZANTIA"},
            dynamic_data={"estado_servicio": "operativo (dato de ejemplo)"},
        ),
    )
    return build_orchestrator(definition)
