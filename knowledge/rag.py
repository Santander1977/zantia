"""
Stub deliberado (prompt maestro, sección 10: "NO inventes todavía una
arquitectura RAG compleja si no es necesaria para el MVP. Construye la
interfaz correcta.").

RagKnowledgeSource implementa el mismo protocolo `KnowledgeSource` que
`InMemoryKnowledgeSource`, para que sea un reemplazo directo el día que
se decida construir recuperación real — pero no ejecuta nada todavía.
"""
from __future__ import annotations

from typing import Any, Optional


class RagKnowledgeSource:
    """PENDIENTE: no implementado en este MVP. Ver
    /Users/enzoalfonso/recado/006-construccion-zantia.md, sección de
    pendientes, para el motivo (no hay corpus real ni decisión de stack
    de recuperación todavía)."""

    def get_static(self, key: str) -> Optional[Any]:
        raise NotImplementedError("RAG no implementado en este MVP — ver recado 006")

    def get_dynamic(self, key: str) -> Optional[Any]:
        raise NotImplementedError("RAG no implementado en este MVP — ver recado 006")
