"""
Persistencia real de EventLog vía ZANTIA_EVENTS_DB_PATH (recado 037,
Parte 1, cierra R-11 para EventLog) — mismo patrón exacto que
`tests/core/test_agent_contract_persistencia.py` usó para
`ConversationState` (recado 021):

1. Con ZANTIA_EVENTS_DB_PATH configurada: los eventos sobreviven a un
   "reinicio del proceso" (nueva instancia de Orchestrator, mismo
   archivo).
2. Sin la variable: comportamiento por defecto documentado
   explícitamente (":memory:" + logger.warning, nunca en silencio).
"""
from __future__ import annotations

import logging
import uuid

from agents.demo.agent import build_demo_agent
from observability.events import EventType


def _nuevo_id() -> str:
    return str(uuid.uuid4())


def test_eventlog_sobrevive_a_reinicio_del_proceso(monkeypatch, tmp_path):
    ruta = str(tmp_path / "zantia_events.db")
    monkeypatch.setenv("ZANTIA_EVENTS_DB_PATH", ruta)

    proceso_1 = build_demo_agent()
    assert proceso_1.events._db_path == ruta  # confirma que sí conectó la env var, no ":memory:"

    conv = f"conv-{_nuevo_id()}"
    proceso_1.handle_message(conv, "demo", _nuevo_id(), "hola")
    eventos_antes = proceso_1.events.for_conversation(conv)
    assert len(eventos_antes) > 0
    proceso_1.events.close()

    # "Reinicio del proceso": Orchestrator nuevo, mismo archivo, CERO
    # eventos en memoria compartidos con proceso_1.
    proceso_2 = build_demo_agent()
    assert proceso_2.events._db_path == ruta

    eventos_despues = proceso_2.events.for_conversation(conv)
    assert len(eventos_despues) == len(eventos_antes)
    tipos_antes = [e.type for e in eventos_antes]
    tipos_despues = [e.type for e in eventos_despues]
    assert tipos_antes == tipos_despues
    # También el contenido real de un evento, no solo el conteo/tipo.
    assert any(e.type == EventType.STATE_TRANSITION for e in eventos_despues)
    proceso_2.events.close()


def test_sin_zantia_events_db_path_cae_a_memoria_y_advierte(monkeypatch, caplog):
    monkeypatch.delenv("ZANTIA_EVENTS_DB_PATH", raising=False)

    with caplog.at_level(logging.WARNING, logger="zantia.core"):
        orchestrator = build_demo_agent()

    assert orchestrator.events._db_path == ":memory:"
    mensajes = [r.message for r in caplog.records if r.name == "zantia.core"]
    assert any("ZANTIA_EVENTS_DB_PATH" in m and "no está configurada" in m for m in mensajes)


def test_con_zantia_events_db_path_no_advierte(monkeypatch, tmp_path, caplog):
    ruta = str(tmp_path / "zantia_events.db")
    monkeypatch.setenv("ZANTIA_EVENTS_DB_PATH", ruta)

    with caplog.at_level(logging.WARNING, logger="zantia.core"):
        orchestrator = build_demo_agent()

    mensajes = [r.message for r in caplog.records if r.name == "zantia.core"]
    assert not any("ZANTIA_EVENTS_DB_PATH" in m for m in mensajes)
    orchestrator.events.close()
