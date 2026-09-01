"""
Máquina de estados formal (004, secciones 6 y 9).

Regla central: ninguna transición se aplica sin pasar por
`validate_transition`. El Orchestrator es el único que la invoca — el
Brain (LLM) nunca decide una transición por sí mismo, solo la propone
(004, sección 8).
"""
from typing import Dict, Set

from .models import FaseActual

# Estados que terminan el flujo automatizado por completo. Ninguna
# transición saliente es válida desde aquí sin intervención humana
# (004, sección 9: "ESCALADO_URGENTE → reanudación automática... nunca").
FULLY_TERMINAL_STATES: Set[FaseActual] = {
    FaseActual.ESCALADO_URGENTE,
    FaseActual.ESCALADO_ESTANDAR,
    FaseActual.ABANDONADA,
}

# CIERRE es semi-terminal: no acepta transiciones automáticas encadenadas,
# pero un mensaje nuevo del usuario sí puede reabrir un ciclo (004, sección 9).
_REOPEN_FROM_CIERRE = {FaseActual.IDENTIFICACION_DE_INTENCION}

# Interrupciones globales (004, sección 6-7): alcanzables desde
# CUALQUIER estado no terminal, sin necesidad de listarlas en cada fila.
GLOBAL_INTERRUPTION_TARGETS: Set[FaseActual] = {
    FaseActual.ESCALADO_URGENTE,
    FaseActual.ESCALADO_ESTANDAR,
    FaseActual.ABANDONADA,
}

# Transiciones válidas "normales" (004, sección 9, tabla de transiciones).
VALID_TRANSITIONS: Dict[FaseActual, Set[FaseActual]] = {
    FaseActual.INICIO: {FaseActual.IDENTIFICACION_DE_INTENCION},
    FaseActual.IDENTIFICACION_DE_INTENCION: {
        FaseActual.IDENTIFICACION_DE_INTENCION,  # reintento por ambigüedad
        FaseActual.RECOPILACION_DE_DATOS,
        # Misma corrección de implementación que RECOPILACION_DE_DATOS ->
        # RESPUESTA (ver más abajo): cuando la intención ya es suficiente
        # para ejecutar una acción sin necesitar más datos (p. ej. una
        # decisión final del paciente, o una cancelación), el turno
        # completo (razonamiento + acción) ocurre de forma síncrona.
        # Encontrado al construir el dominio salud — ver recado 007.
        FaseActual.RESPUESTA,
    },
    FaseActual.RECOPILACION_DE_DATOS: {
        FaseActual.RECOPILACION_DE_DATOS,  # ciclo válido, con contador (orchestrator)
        FaseActual.RAZONAMIENTO_DECISION,
        FaseActual.PAUSA_POR_DATOS_FALTANTES,
        # Corrección encontrada al implementar (no estaba en 004 sección 9
        # tal cual): cuando el último dato llega y el Brain ya propone
        # ejecutar la tool en el MISMO turno, RAZONAMIENTO_DECISION y
        # ACCION ocurren como micro-pasos internos síncronos (quedan
        # igualmente en el registro de observabilidad vía eventos
        # TOOL_INVOKED), no como paradas de fase_actual separadas. Ver
        # recado 006, sección de hallazgos de implementación.
        FaseActual.RESPUESTA,
    },
    FaseActual.RAZONAMIENTO_DECISION: {
        FaseActual.ACCION,
        FaseActual.RAZONAMIENTO_DECISION,  # replantea tras guardrail
        FaseActual.RESPUESTA,  # respuesta directa, sin tool
    },
    FaseActual.ACCION: {
        FaseActual.RESPUESTA,
        FaseActual.RAZONAMIENTO_DECISION,  # reintento tras error/timeout
    },
    FaseActual.RESPUESTA: {
        FaseActual.CIERRE,
        FaseActual.SEGUIMIENTO,
        FaseActual.MANEJO_DE_DUDA,
    },
    FaseActual.MANEJO_DE_DUDA: {
        FaseActual.RESPUESTA,
    },
    FaseActual.PAUSA_POR_DATOS_FALTANTES: {
        FaseActual.RECOPILACION_DE_DATOS,
    },
    FaseActual.SEGUIMIENTO: {
        FaseActual.IDENTIFICACION_DE_INTENCION,
    },
    FaseActual.CIERRE: _REOPEN_FROM_CIERRE,
    # Los estados terminales no tienen salidas normales:
    FaseActual.ESCALADO_URGENTE: set(),
    FaseActual.ESCALADO_ESTANDAR: set(),
    FaseActual.ABANDONADA: set(),
}


class InvalidTransitionError(Exception):
    def __init__(self, origen: FaseActual, destino: FaseActual):
        self.origen = origen
        self.destino = destino
        super().__init__(
            f"Transición inválida: {origen.value} -> {destino.value} "
            "(004, sección 9 — transiciones explícitamente inválidas)"
        )


def is_terminal(fase: FaseActual) -> bool:
    return fase in FULLY_TERMINAL_STATES


def validate_transition(origen: FaseActual, destino: FaseActual) -> None:
    """Lanza InvalidTransitionError si la transición no está permitida.

    No modifica nada — es una función pura de validación. Quien la llama
    (el Orchestrator) decide qué hacer si falla.
    """
    if is_terminal(origen):
        raise InvalidTransitionError(origen, destino)
    if destino in GLOBAL_INTERRUPTION_TARGETS:
        # Interrupción global: siempre permitida desde un estado no terminal,
        # sin necesidad de que destino esté en VALID_TRANSITIONS[origen].
        return
    permitidos = VALID_TRANSITIONS.get(origen, set())
    if destino not in permitidos:
        raise InvalidTransitionError(origen, destino)
