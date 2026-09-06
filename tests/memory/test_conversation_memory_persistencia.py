"""
Persistencia real de ConversationMemory vía ZANTIA_MEMORY_DB_PATH
(recado 037, Parte 1, cierra R-11 para ConversationMemory) — mismo
patrón que test_events_persistencia.py/test_agent_contract_persistencia.py.
"""
from __future__ import annotations

import logging
import uuid

from agents.demo.agent import build_demo_agent


def _nuevo_id() -> str:
    return str(uuid.uuid4())


def test_conversation_memory_sobrevive_a_reinicio_del_proceso(monkeypatch, tmp_path):
    ruta = str(tmp_path / "zantia_memory.db")
    monkeypatch.setenv("ZANTIA_MEMORY_DB_PATH", ruta)

    proceso_1 = build_demo_agent()
    assert proceso_1._memory._db_path == ruta

    conv = f"conv-{_nuevo_id()}"
    proceso_1.handle_message(conv, "demo", _nuevo_id(), "quiero programar un evento")
    turnos_antes = proceso_1._memory.get_recent(conv)
    assert len(turnos_antes) == 2  # turno "user" + turno "agent"
    proceso_1._memory.close()

    proceso_2 = build_demo_agent()
    assert proceso_2._memory._db_path == ruta
    turnos_despues = proceso_2._memory.get_recent(conv)
    assert [t.text for t in turnos_despues] == [t.text for t in turnos_antes]
    assert [t.role for t in turnos_despues] == [t.role for t in turnos_antes]
    proceso_2._memory.close()


def test_conversation_memory_sigue_acotada_a_la_ventana_tras_persistir(monkeypatch, tmp_path):
    """Requisito explícito del pedido: `get_recent()` sigue devolviendo
    como máximo la ventana configurada, aun con persistencia real — la
    tabla conserva todo, la LECTURA sigue acotada."""
    from memory.conversation_memory import SQLiteConversationMemory

    ruta = str(tmp_path / "zantia_memory_ventana.db")
    mem = SQLiteConversationMemory(window_size=3, db_path=ruta)
    conv = "conv-ventana"
    for i in range(10):
        mem.add_turn(conv, "user", f"mensaje {i}")

    recientes = mem.get_recent(conv)
    assert len(recientes) == 3
    assert [t.text for t in recientes] == ["mensaje 7", "mensaje 8", "mensaje 9"]
    mem.close()

    # La tabla conserva el historial completo, aunque get_recent() no
    # lo devuelva todo — verificado leyendo la tabla directamente.
    import sqlite3

    conn = sqlite3.connect(ruta)
    total = conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE conversation_id = ?", (conv,)).fetchone()[0]
    assert total == 10
    conn.close()


def test_sin_zantia_memory_db_path_cae_a_memoria_y_advierte(monkeypatch, caplog):
    monkeypatch.delenv("ZANTIA_MEMORY_DB_PATH", raising=False)

    with caplog.at_level(logging.WARNING, logger="zantia.core"):
        orchestrator = build_demo_agent()

    assert orchestrator._memory._db_path == ":memory:"
    mensajes = [r.message for r in caplog.records if r.name == "zantia.core"]
    assert any("ZANTIA_MEMORY_DB_PATH" in m and "no está configurada" in m for m in mensajes)
