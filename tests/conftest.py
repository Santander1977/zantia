import pytest

from agents.demo.agent import build_demo_agent


@pytest.fixture
def orchestrator():
    """Un Orchestrator fresco por test — agente demo, FakeBrain,
    SQLiteStateStore(':memory:') aislado (sin compartir estado entre tests)."""
    return build_demo_agent()
