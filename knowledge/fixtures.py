"""Implementación de referencia con datos ficticios (sección 33)."""
from __future__ import annotations

from typing import Any, Dict, Optional


class InMemoryKnowledgeSource:
    def __init__(
        self,
        static_data: Optional[Dict[str, Any]] = None,
        dynamic_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._static = dict(static_data or {})
        self._dynamic = dict(dynamic_data or {})

    def get_static(self, key: str) -> Optional[Any]:
        return self._static.get(key)

    def get_dynamic(self, key: str) -> Optional[Any]:
        return self._dynamic.get(key)

    def set_dynamic(self, key: str, value: Any) -> None:
        """Simula que el dato dinámico cambia con el tiempo (a diferencia
        del estático) — útil para pruebas de jerarquía de verdad."""
        self._dynamic[key] = value
