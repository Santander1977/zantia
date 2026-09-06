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

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from core.brain import Brain
from core.config import DEFAULT_CONFIG
from core.orchestrator import Orchestrator
from guardrails.base import Guardrail
from guardrails.engine import GuardrailEngine
from knowledge.base import KnowledgeSource
from state.store import StateStore
from tools.base import Tool
from tools.registry import ToolRegistry

logger = logging.getLogger("zantia.core")


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

    from guardrails.rules import reglas_core_por_defecto

    engine = GuardrailEngine(reglas_core_por_defecto(registry.categories_by_name()) + definition.extra_guardrails)

    from state.store import SQLiteStateStore

    db_path = DEFAULT_CONFIG.db_path
    if db_path == ":memory:":
        # Brecha de wiring resuelta (recado 021, previamente documentada
        # en 014/D-6 y en .ai/RISKS.md): ZANTIA_DB_PATH ya se lee acá.
        # Este warning es la parte "nunca en silencio" del fix — si
        # alguien despliega un canal real sin configurar la variable,
        # tiene que quedar un rastro imposible de ignorar en los logs,
        # no un ":memory:" mudo que se descubre recién cuando el proceso
        # se reinicia y una conversación real pierde todo su estado.
        logger.warning(
            "ZANTIA_DB_PATH no está configurada — el ConversationState de "
            "esta conversación vive solo en memoria del proceso y se "
            "pierde por completo si el proceso se reinicia a mitad de "
            "camino. Configurar ZANTIA_DB_PATH (ver .env.example) antes "
            "de desplegar cualquier canal en producción."
        )
    store: StateStore = SQLiteStateStore(db_path)

    # Persistencia real de EventLog/ConversationMemory (recado 037,
    # Parte 1, R-11) — mismo patrón exacto que ZANTIA_DB_PATH arriba
    # (recado 021): sin la variable, cae a ":memory:" (SQLite en modo
    # memoria, nunca objetos Python puros — mismo motor, mismo esquema,
    # solo sin archivo en disco), pero NUNCA en silencio.
    from memory.conversation_memory import SQLiteConversationMemory
    from observability.events import SQLiteEventLog

    events_db_path = DEFAULT_CONFIG.events_db_path
    if events_db_path == ":memory:":
        logger.warning(
            "ZANTIA_EVENTS_DB_PATH no está configurada — el EventLog "
            "(auditoría de transiciones, tools y decisiones de guardrail) "
            "de esta conversación vive solo en memoria del proceso y se "
            "pierde por completo si el proceso se reinicia a mitad de "
            "camino. Sin esto, no hay forma de auditar qué decidió o "
            "propuso el sistema tras un reinicio. Configurar "
            "ZANTIA_EVENTS_DB_PATH (ver .env.example) antes de desplegar "
            "cualquier canal en producción."
        )
    events = SQLiteEventLog(events_db_path)

    memory_db_path = DEFAULT_CONFIG.memory_db_path
    if memory_db_path == ":memory:":
        logger.warning(
            "ZANTIA_MEMORY_DB_PATH no está configurada — el historial "
            "reciente de turnos (ConversationMemory) de esta conversación "
            "vive solo en memoria del proceso y se pierde por completo si "
            "el proceso se reinicia a mitad de camino. Configurar "
            "ZANTIA_MEMORY_DB_PATH (ver .env.example) antes de desplegar "
            "cualquier canal en producción."
        )
    memory = SQLiteConversationMemory(window_size=definition.memory_window, db_path=memory_db_path)

    return Orchestrator(
        state_store=store,
        memory=memory,
        brain=definition.brain,
        tool_registry=registry,
        event_log=events,
        guardrail_engine=engine,
    )
