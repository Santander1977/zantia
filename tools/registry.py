"""ToolRegistry — el Orchestrator resuelve tools por nombre a través de
aquí; el Brain nunca ejecuta una tool directamente (004, sección 15)."""
from __future__ import annotations

from typing import Dict, List

from .base import Tool, ToolCategory


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool no registrada: '{name}'")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def category_of(self, name: str) -> ToolCategory:
        return self.get(name).category

    def categories_by_name(self) -> Dict[str, ToolCategory]:
        return {name: tool.category for name, tool in self._tools.items()}

    def list_by_category(self, category: ToolCategory) -> List[str]:
        return [name for name, tool in self._tools.items() if tool.category == category]
