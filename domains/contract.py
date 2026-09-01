"""
Contrato de dominio (prompt maestro, sección 9): la arquitectura mínima
para que un dominio pueda incorporarse después, SIN desarrollar todavía
su lógica real (explícitamente prohibido en esta fase — sección 9).

Un dominio real (health/, emergency/, sales/, citizen/) deberá construir
una función `build_agent_definition() -> AgentDefinition` (ver
core/agent_contract.py) que provea sus propias tools, knowledge y
guardrails adicionales — sin tocar el Core.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol

from core.agent_contract import AgentDefinition


class DomainModule(Protocol):
    """Lo que todo paquete domains/<nombre>/ deberá exponer cuando se
    diseñe de verdad (PENDIENTE por dominio — ver recado 006)."""

    def build_agent_definition(self) -> AgentDefinition: ...


@dataclass(frozen=True)
class DomainMetadata:
    name: str
    description: str
    implemented: bool
