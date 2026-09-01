"""Tool READ, tool WRITE, idempotencia, error de tool (sección 28)."""
import pytest

from tools.base import ToolError
from tools.demo_tools import GetDemoInfoTool, NotifyTeamTool, ScheduleEventTool


def test_tool_read():
    tool = GetDemoInfoTool()
    resultado = tool.run({"clave": "horario_atencion"})
    assert resultado.success
    assert "9:00" in resultado.data["valor"]


def test_tool_read_clave_desconocida():
    tool = GetDemoInfoTool()
    resultado = tool.run({"clave": "no-existe"})
    assert not resultado.success


def test_tool_write():
    tool = ScheduleEventTool()
    resultado = tool.run({"evento": "reunion", "fecha": "mañana", "idempotency_key": "k1"})
    assert resultado.success
    assert resultado.data["confirmado"] is True


def test_tool_write_es_idempotente():
    tool = ScheduleEventTool()
    r1 = tool.run({"evento": "reunion", "fecha": "mañana", "idempotency_key": "k1"})
    r2 = tool.run({"evento": "reunion-distinta", "fecha": "otra-fecha", "idempotency_key": "k1"})
    # misma idempotency_key -> mismo resultado, NO se re-ejecuta con los
    # datos nuevos (004, sección 10: evita doble-agendamiento)
    assert r1.data == r2.data


def test_tool_write_sin_idempotency_key_lanza_error():
    tool = ScheduleEventTool()
    with pytest.raises(ToolError):
        tool.run({"evento": "reunion", "fecha": "mañana"})


def test_tool_write_error_simulado():
    tool = ScheduleEventTool()
    with pytest.raises(ToolError):
        tool.run({"evento": "__forzar_error__", "idempotency_key": "k2"})


def test_tool_notify():
    tool = NotifyTeamTool()
    resultado = tool.run({"mensaje": "caso escalado"})
    assert resultado.success
    assert tool.notificaciones_enviadas == ["caso escalado"]
