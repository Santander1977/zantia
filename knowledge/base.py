"""
Separación CONOCIMIENTO ESTÁTICO / DINÁMICO (003 sección 9, hallado
originalmente en Dani — 002). El dato dinámico gana sobre el estático
y sobre lo que el Brain "recuerde" si hay conflicto.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol


class KnowledgeSource(Protocol):
    def get_static(self, key: str) -> Optional[Any]: ...

    def get_dynamic(self, key: str) -> Optional[Any]: ...
