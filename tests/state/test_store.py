"""Cubre, del listado de la sección 28 del prompt maestro: creación de
sesión, recuperación de estado, persistencia, y (parte de) idempotencia
a nivel de concurrencia."""
import pytest

from state.models import ConversationState
from state.store import ConcurrencyConflictError, InMemoryStateStore, SQLiteStateStore


@pytest.mark.parametrize("store_factory", [InMemoryStateStore, lambda: SQLiteStateStore(":memory:")])
def test_creacion_de_sesion(store_factory):
    store = store_factory()
    state = store.create("conv-1", canal="demo")
    assert isinstance(state, ConversationState)
    assert state.conversation_id == "conv-1"
    assert state.version == 0


@pytest.mark.parametrize("store_factory", [InMemoryStateStore, lambda: SQLiteStateStore(":memory:")])
def test_recuperacion_de_estado(store_factory):
    store = store_factory()
    store.create("conv-1", canal="demo")
    recuperado = store.get("conv-1")
    assert recuperado is not None
    assert recuperado.conversation_id == "conv-1"


def test_recuperacion_de_estado_inexistente():
    store = InMemoryStateStore()
    assert store.get("no-existe") is None


def test_persistencia_real_sqlite_sobrevive_a_nueva_conexion(tmp_path):
    """Persistencia real (no solo en memoria de proceso): se escribe con
    una conexión, se lee con una conexión SQLite distinta al mismo archivo."""
    db_path = str(tmp_path / "zantia_test.db")
    store_1 = SQLiteStateStore(db_path)
    creado = store_1.create("conv-persistente", canal="demo")
    store_1.save(creado.model_copy(update={"intencion": "programar_evento"}), expected_version=0)
    store_1.close()

    store_2 = SQLiteStateStore(db_path)
    recuperado = store_2.get("conv-persistente")
    assert recuperado is not None
    assert recuperado.intencion == "programar_evento"
    assert recuperado.version == 1
    store_2.close()


@pytest.mark.parametrize("store_factory", [InMemoryStateStore, lambda: SQLiteStateStore(":memory:")])
def test_concurrencia_optimista_rechaza_version_desactualizada(store_factory):
    store = store_factory()
    state = store.create("conv-1", canal="demo")

    store.save(state.model_copy(update={"intencion": "A"}), expected_version=0)

    with pytest.raises(ConcurrencyConflictError):
        # Reintenta guardar usando la MISMA versión vieja (0) — ya no es
        # la vigente (ahora es 1) — debe rechazarse (004, sección 11).
        store.save(state.model_copy(update={"intencion": "B"}), expected_version=0)
