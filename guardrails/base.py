"""
Contrato Orquestador <-> Guardrails (004, sección 16).

NO depende de instrucciones de prompt (a diferencia de Dani, donde las
14 secciones del system prompt eran, salvo el formato, puras
instrucciones de texto sin verificación de código — 002,
"Hallazgo transversal más importante"). Aquí cada regla es código real,
ejecutado después de que el Brain propone, antes de que el Orchestrator
escriba nada.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Protocol

from state.models import ConversationState


class GuardrailDecision(str, Enum):
    ALLOW = "ALLOW"
    MODIFY = "MODIFY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


@dataclass
class GuardrailContext:
    """Lo que el Orchestrator le entrega a Guardrails: la propuesta
    completa del Brain, más el estado vigente (004, sección 16)."""

    state: ConversationState
    proposed_state_changes: Dict[str, Any]
    proposed_tool: Optional[str]
    proposed_response: str


@dataclass
class GuardrailResult:
    decision: GuardrailDecision
    reason: str
    modified_response: Optional[str] = None
    forced_state_changes: Dict[str, Any] = field(default_factory=dict)
    guardrail_name: str = ""


class Guardrail(Protocol):
    name: str

    def evaluate(self, context: GuardrailContext) -> GuardrailResult: ...
