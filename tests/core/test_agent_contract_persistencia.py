"""
Persistencia real de ConversationState vía ZANTIA_DB_PATH (recado 021,
brecha de wiring documentada primero en 014/D-6 y en .ai/RISKS.md):
`core/agent_contract.py:build_orchestrator` construía siempre
`SQLiteStateStore(":memory:")` hardcodeado, sin conectar la variable de
entorno que ya existía en `.env.example` y en `core/config.py`. Este
archivo cubre, mismo patrón que
`tests/domains/health/test_identidad_persistente.py` usó para
`identity_store.py` en 014:

1. Con ZANTIA_DB_PATH configurada: el estado sobrevive a un "reinicio
   del proceso" (nueva instancia de Orchestrator, mismo archivo).
2. Sin ZANTIA_DB_PATH: comportamiento por defecto documentado
   explícitamente (":memory:" + logger.warning, nunca en silencio).
3. Dos conversaciones distintas en el mismo archivo no se mezclan.

No modifica ningún test existente — `tests/state/test_store.py` ya
cubre el `SQLiteStateStore` en sí; este archivo cubre específicamente
el wiring de `build_orchestrator`, que es lo que estaba roto.
"""
from __future__ import annotations

import logging
import uuid

import pytest

from agents.demo.agent import build_demo_agent
from core.agent_contract import AgentDefinition, build_orchestrator
from core.brain import FakeBrain
from state.models import FaseActual


def _nuevo_id() -> str:
    return str(uuid.uuid4())


def _definicion_minima() -> AgentDefinition:
    """Mismo agente demo que usa el resto de la suite de Core (sin
    tools/knowledge — no hacen falta para probar wiring de persistencia)."""
    return AgentDefinition(name="demo", domain="demo", brain=FakeBrain())


# ---------------------------------------------------------------------
# 1. Sobrevive a un "reinicio del proceso" real.
# ---------------------------------------------------------------------
def test_build_orchestrator_usa_zantia_db_path_y_sobrevive_a_reinicio(monkeypatch, tmp_path):
    ruta = str(tmp_path / "zantia_state.db")
    monkeypatch.setenv("ZANTIA_DB_PATH", ruta)

    # build_demo_agent() (mismo agente que test_orchestrator_e2e.py, con
    # sus tools reales) — necesario acá porque este test llega hasta la
    # ejecución de la tool "schedule_event"; _definicion_minima() (sin
    # tools) alcanza para los demás tests de este archivo, que no llegan
    # tan lejos en la conversación.
    proceso_1 = build_demo_agent()
    assert proceso_1.store._db_path == ruta  # confirma que sí conectó la env var, no ":memory:"

    conv = f"conv-{_nuevo_id()}"
    r1 = proceso_1.handle_message(conv, "demo", _nuevo_id(), "quiero programar un evento")
    assert r1.state.fase_actual == FaseActual.IDENTIFICACION_DE_INTENCION
    r2 = proceso_1.handle_message(conv, "demo", _nuevo_id(), "reunión de equipo")
    assert r2.state.datos_recopilados.get("evento") == "reunión de equipo"
    proceso_1.store.close()

    # "Reinicio del proceso": Orchestrator nuevo, mismo archivo, CERO
    # estado en memoria compartido con proceso_1 (ni siquiera la misma
    # instancia de ConversationMemory).
    proceso_2 = build_demo_agent()
    assert proceso_2.store._db_path == ruta

    recuperado = proceso_2.store.get(conv)
    assert recuperado is not None
    assert recuperado.fase_actual == FaseActual.RECOPILACION_DE_DATOS
    assert recuperado.datos_recopilados.get("evento") == "reunión de equipo"
    assert recuperado.version == r2.state.version

    # La conversación sigue avanzando normalmente desde el estado
    # recuperado — no es solo una lectura, es persistencia funcional.
    # Mismo paso manual de consentimiento que test_orchestrator_e2e.py
    # (FakeBrain no lo modela — se otorga fuera del flujo conversacional).
    proceso_2.store.save(
        recuperado.model_copy(update={"consentimiento_datos": True}),
        expected_version=recuperado.version,
    )
    r3 = proceso_2.handle_message(conv, "demo", _nuevo_id(), "mañana a las 10")
    assert r3.state.fase_actual == FaseActual.RESPUESTA
    proceso_2.store.close()


# ---------------------------------------------------------------------
# 2. Comportamiento por defecto SIN la variable — nunca en silencio.
# ---------------------------------------------------------------------
def test_build_orchestrator_sin_zantia_db_path_cae_a_memoria_y_advierte(monkeypatch, caplog):
    monkeypatch.delenv("ZANTIA_DB_PATH", raising=False)

    with caplog.at_level(logging.WARNING, logger="zantia.core"):
        orchestrator = build_demo_agent()

    assert orchestrator.store._db_path == ":memory:"
    # "Nunca en silencio" (requisito explícito del pedido): tiene que
    # quedar un warning imposible de no ver en los logs, no solo el
    # comportamiento silencioso de caer a memoria.
    mensajes = [r.message for r in caplog.records if r.name == "zantia.core"]
    assert any("ZANTIA_DB_PATH" in m and "no está configurada" in m for m in mensajes)


def test_build_orchestrator_con_zantia_db_path_no_advierte(monkeypatch, tmp_path, caplog):
    """El warning es específico de la falta de configuración — con la
    variable puesta, no debe aparecer (evita alarmar en producción bien
    configurada)."""
    ruta = str(tmp_path / "zantia_state.db")
    monkeypatch.setenv("ZANTIA_DB_PATH", ruta)

    with caplog.at_level(logging.WARNING, logger="zantia.core"):
        orchestrator = build_orchestrator(_definicion_minima())

    assert orchestrator.store._db_path == ruta
    mensajes = [r.message for r in caplog.records if r.name == "zantia.core"]
    assert not any("ZANTIA_DB_PATH" in m for m in mensajes)
    orchestrator.store.close()


# ---------------------------------------------------------------------
# 3. Aislamiento entre conversaciones distintas en el MISMO archivo.
# ---------------------------------------------------------------------
def test_dos_conversaciones_distintas_no_se_mezclan_en_el_mismo_archivo(monkeypatch, tmp_path):
    ruta = str(tmp_path / "zantia_state.db")
    monkeypatch.setenv("ZANTIA_DB_PATH", ruta)

    # Dos "procesos"/Orchestrators distintos contra el mismo archivo —
    # no solo dos conversation_id en la misma instancia en memoria.
    proceso_a = build_orchestrator(_definicion_minima())
    proceso_b = build_orchestrator(_definicion_minima())

    conv_a = f"conv-a-{_nuevo_id()}"
    conv_b = f"conv-b-{_nuevo_id()}"

    proceso_a.handle_message(conv_a, "demo", _nuevo_id(), "quiero programar un evento")
    proceso_a.handle_message(conv_a, "demo", _nuevo_id(), "cumpleaños de Ana")

    proceso_b.handle_message(conv_b, "demo", _nuevo_id(), "quiero programar un evento")
    proceso_b.handle_message(conv_b, "demo", _nuevo_id(), "reunión de trabajo")

    proceso_a.store.close()
    proceso_b.store.close()

    # Un tercer "proceso" que solo lee, contra el mismo archivo — si
    # hubiera mezcla de datos entre conversation_id, se vería acá.
    verificador = build_orchestrator(_definicion_minima())
    estado_a = verificador.store.get(conv_a)
    estado_b = verificador.store.get(conv_b)

    assert estado_a is not None and estado_b is not None
    assert estado_a.conversation_id == conv_a
    assert estado_b.conversation_id == conv_b
    assert estado_a.datos_recopilados.get("evento") == "cumpleaños de Ana"
    assert estado_b.datos_recopilados.get("evento") == "reunión de trabajo"
    # Ninguno "vio" el dato del otro.
    assert estado_a.datos_recopilados.get("evento") != estado_b.datos_recopilados.get("evento")
    verificador.store.close()


# ---------------------------------------------------------------------
# 3b. Otro lugar del Core con un store hardcodeado en memoria (requisito
# #3 del pedido) — smoke test negativo: no debería existir ninguno.
# ---------------------------------------------------------------------
def test_no_hay_otro_store_hardcodeado_en_memoria_en_el_core():
    """Documenta con un grep en código, no solo en prosa (recado 021):
    la única instanciación de SQLiteStateStore/InMemoryStateStore fuera
    de tests/domains queda en build_orchestrator, y ya usa la env var."""
    import inspect

    import core.agent_contract as agent_contract_module

    codigo = inspect.getsource(agent_contract_module)
    assert 'SQLiteStateStore(":memory:")' not in codigo
    assert "DEFAULT_CONFIG.db_path" in codigo
