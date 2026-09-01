"""
Tools de demostración — datos 100% ficticios (prompt maestro, sección 33:
"todo ejemplo debe utilizar datos ficticios"). Existen para validar que
el Core funciona de extremo a extremo (sección 27), no para resolver
ningún caso de negocio real.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

from .base import ToolCategory, ToolError, ToolResult

_DATOS_FICTICIOS = {
    "horario_atencion": "lunes a viernes, 9:00-18:00 (dato de ejemplo)",
    "canal_soporte": "demo@zantia.example (dato de ejemplo)",
}


class GetDemoInfoTool:
    name = "get_demo_info"
    description = "Tool READ de ejemplo: devuelve datos ficticios estáticos."
    category = ToolCategory.READ
    idempotent = True  # leer nunca duplica efectos

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        clave = params.get("clave")
        if clave not in _DATOS_FICTICIOS:
            return ToolResult(success=False, error=f"clave desconocida: {clave!r}")
        return ToolResult(success=True, data={"valor": _DATOS_FICTICIOS[clave]})


class ScheduleEventTool:
    """Tool WRITE de ejemplo, deliberadamente genérica (no de salud —
    prompt maestro sección 27) — 'programar un evento' ficticio.

    Idempotente por `idempotency_key`: ejecutar dos veces con la misma
    clave no duplica el efecto (004, sección 10).
    """

    name = "schedule_event"
    description = "Tool WRITE de ejemplo: programa un evento ficticio, idempotente por clave."
    category = ToolCategory.WRITE
    idempotent = True

    def __init__(self) -> None:
        self._ejecutadas: Set[str] = set()
        self._resultados: Dict[str, Dict[str, Any]] = {}

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        idempotency_key = params.get("idempotency_key")
        if not idempotency_key:
            raise ToolError("schedule_event requiere 'idempotency_key' (004, sección 10)")

        if idempotency_key in self._ejecutadas:
            # Reintento del mismo evento: se devuelve el mismo resultado,
            # sin volver a "ejecutar" nada (evita doble-agendamiento).
            return ToolResult(success=True, data=self._resultados[idempotency_key])

        evento = params.get("evento")
        if evento == "__forzar_error__":
            # Vía determinista para probar el manejo de errores (sección 28).
            raise ToolError("fallo simulado de integración externa")

        resultado = {
            "evento": evento,
            "fecha": params.get("fecha", "sin especificar"),
            "confirmado": True,
        }
        self._ejecutadas.add(idempotency_key)
        self._resultados[idempotency_key] = resultado
        return ToolResult(success=True, data=resultado)


class NotifyTeamTool:
    """Tool NOTIFY de ejemplo — nunca promete nada al usuario, solo dispara
    un evento interno (lección de Dani: 'escalate_to_human', 002)."""

    name = "notify_team"
    description = "Tool NOTIFY de ejemplo: registra una notificación interna ficticia."
    category = ToolCategory.NOTIFY
    idempotent = False  # no idempotente por diseño: cada notificación es un evento propio

    def __init__(self) -> None:
        self.notificaciones_enviadas: list = []

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        mensaje = params.get("mensaje", "")
        self.notificaciones_enviadas.append(mensaje)
        return ToolResult(success=True, data={"notificado": True})
