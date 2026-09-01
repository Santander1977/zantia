"""Transición válida / transición inválida (sección 28)."""
import pytest

from state.machine import GLOBAL_INTERRUPTION_TARGETS, InvalidTransitionError, is_terminal, validate_transition
from state.models import FaseActual


def test_transicion_valida_inicio_a_identificacion():
    validate_transition(FaseActual.INICIO, FaseActual.IDENTIFICACION_DE_INTENCION)  # no debe lanzar


def test_transicion_invalida_respuesta_a_accion_directo():
    with pytest.raises(InvalidTransitionError):
        validate_transition(FaseActual.RESPUESTA, FaseActual.ACCION)


def test_transicion_invalida_desde_estado_terminal():
    with pytest.raises(InvalidTransitionError):
        validate_transition(FaseActual.ESCALADO_URGENTE, FaseActual.RESPUESTA)


def test_interrupcion_global_siempre_permitida_desde_no_terminal():
    for destino in GLOBAL_INTERRUPTION_TARGETS:
        validate_transition(FaseActual.RECOPILACION_DE_DATOS, destino)  # no debe lanzar


def test_cierre_puede_reabrirse_con_mensaje_nuevo():
    validate_transition(FaseActual.CIERRE, FaseActual.IDENTIFICACION_DE_INTENCION)  # no debe lanzar


def test_estados_terminales():
    assert is_terminal(FaseActual.ESCALADO_URGENTE)
    assert is_terminal(FaseActual.ESCALADO_ESTANDAR)
    assert is_terminal(FaseActual.ABANDONADA)
    assert not is_terminal(FaseActual.RESPUESTA)
