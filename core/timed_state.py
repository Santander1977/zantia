"""
Estado con timestamp real + ventana de tiempo configurable — mecanismo
GENÉRICO, agnóstico de dominio (recado 076).

Contexto: `domains/health/gateway.py` (ZANTIA, dominio salud) construyó,
a lo largo de varios recados reales (057, 067, 069, 071), el mismo
patrón una y otra vez: "algo pasó en un momento real; durante una
ventana de tiempo desde ese momento, el sistema se comporta distinto
que después de esa ventana" — el saludo corto de 30 minutos tras un
cierre (recado 057), el enfriamiento de 2 minutos tras una despedida
(recado 067, con su mensaje de tiempo restante calculado en tiempo real
contra el timestamp guardado — nunca un cronómetro que se actualiza
solo, recado 069), y el hallazgo de que ese enfriamiento no se armaba
en uno de los caminos reales (recado 071). Todo eso vivía como código
específico de `HealthGateway` — `_cierre_reciente`, un
`Dict[str, Tuple[datetime, Optional[str], bool]]` construido a mano.

Este módulo extrae la PARTE genérica de ese patrón (el registro
timestamp+payload, y el cálculo de "¿estoy dentro de esta ventana?"/
"¿cuánto falta?") para que un dominio futuro (ej. seguridad ciudadana)
la reutilice sin reconstruirla — el Core nunca sabe qué es "una cita",
"una despedida" ni "un caso": solo sabe que algo pasó, cuándo, y qué
payload arbitrario llevaba asociado.

## Dos modos de uso (documentados explícitamente — ambos previstos)

`ModoVentana` distingue dos formas de comportarse DENTRO de una
ventana — es metadata puramente descriptiva (`TimedStateStore` nunca la
lee ni bifurca su propio comportamiento según este valor; es el DOMINIO
llamador quien decide qué hacer):

- **BLOQUEO** — dentro de la ventana, no se procesa NADA nuevo; el
  dominio solo informa cuánto tiempo falta. Único modo con uso real en
  producción hasta hoy: el enfriamiento de 2 minutos de ZANTIA
  (`domains/health/gateway.py`, recados 067/069/071).
- **ABIERTA** — dentro de la ventana, el contenido nuevo SÍ se acepta y
  se acumula contra el mismo evento (ej. adjuntar evidencia a un caso ya
  creado, sin perder ni reiniciar el plazo original). Sin ningún uso
  real todavía — previsto para un dominio futuro (seguridad ciudadana,
  ver `.ai/CORE_REUSABLE_PATTERNS.md`) — pero el mecanismo YA lo soporta
  estructuralmente: `TimedStateStore.actualizar_payload` reemplaza el
  payload de una entrada existente sin tocar su `momento` original, así
  que un dominio puede ir acumulando contenido mientras sigue dentro de
  la misma ventana, sin que cada actualización extienda el plazo. Ningún
  archivo de este proyecto implementa todavía lógica de negocio para
  este modo — el diseño solo garantiza que no sea estructuralmente
  imposible después.

## Qué NO hace este módulo

No decide texto de mensajes, no decide qué significa "procesar" o
"bloquear" una solicitud, no sabe nada sobre canales, pacientes ni
casos. Eso sigue siendo, siempre, responsabilidad exclusiva del dominio
que lo usa — mismo principio que `core/selection.py` (el Core propone
un mecanismo verificable, nunca decide contenido de dominio)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional


class ModoVentana(str, Enum):
    """Ver docstring del módulo — metadata descriptiva, nunca leída por
    `TimedStateStore` para cambiar su propio comportamiento."""

    BLOQUEO = "bloqueo"
    ABIERTA = "abierta"


@dataclass(frozen=True)
class VentanaDeTiempo:
    """Configuración de una ventana: cuánto dura (`duracion`) y para
    qué modo de uso está pensada (`modo`, documental). `nombre` es solo
    para mensajes de error/debug legibles cuando un dominio configura
    VARIAS ventanas anidadas sobre el mismo evento — patrón real ya
    probado en ZANTIA: `_VENTANA_ENFRIAMIENTO` (2 min, BLOQUEO) anidada
    dentro de `_VENTANA_SALUDO_CORTO` (30 min, ABIERTA en el sentido de
    "sigue aceptando conversación, solo cambia el saludo") — ambas leen
    el MISMO timestamp guardado una sola vez."""

    duracion: timedelta
    modo: Optional[ModoVentana] = None
    nombre: str = ""


# Nota de diseño (recado 076): no todo uso real de `TimedStateStore`
# necesita encajar en BLOQUEO o ABIERTA — ZANTIA también usa el MISMO
# timestamp para una tercera cosa, más simple: elegir qué SALUDO
# mostrar (corto vs. completo) sin bloquear ni acumular nada
# (`_VENTANA_SALUDO_CORTO`, 30 min, anidada alrededor de los 2 min de
# `_VENTANA_ENFRIAMIENTO`/BLOQUEO). Ese caso solo necesita
# `dentro_de_ventana()` directo, sin ningún `ModoVentana` asociado —
# `VentanaDeTiempo.modo` es opcional en la práctica (el dominio puede
# usar el mecanismo sin declarar ninguno de los dos modos con nombre
# si su caso de uso, como este, no es ni bloqueo ni acumulación).


@dataclass
class _Entrada:
    momento: datetime
    payload: Any = None


class TimedStateStore:
    """Registro genérico de eventos con timestamp real + payload
    arbitrario, keyed por un identificador de texto — el dominio decide
    qué representa esa clave (un `patient_reference`, un `case_id`, lo
    que sea) y qué lleva el payload (el Core nunca lo inspecciona).
    Extraído de `domains/health/gateway.py:_cierre_reciente` (recados
    057/067/069/071) — mismo comportamiento observable, generalizado.

    Como cualquier estado de `HealthGateway`/estructuras equivalentes
    de otros dominios, vive en memoria de proceso — la misma limitación
    ya documentada y aceptada para el resto del estado conversacional
    de ZANTIA (ver `.ai/RISKS.md` R-11), no una regresión de este
    módulo."""

    def __init__(self) -> None:
        self._entradas: Dict[str, _Entrada] = {}

    def registrar(self, clave: str, payload: Any = None, *, ahora: Optional[datetime] = None) -> None:
        """Registra (o REEMPLAZA por completo, timestamp incluido) el
        evento para `clave`, con el reloj real de este momento — `ahora`
        existe solo para que los tests puedan controlar el reloj; código
        de dominio real nunca debería pasarlo."""
        self._entradas[clave] = _Entrada(momento=ahora or datetime.now(timezone.utc), payload=payload)

    def actualizar_payload(self, clave: str, payload: Any) -> bool:
        """Reemplaza SOLO el payload de una entrada YA existente —
        preserva el `momento` original, nunca reinicia la ventana. Es la
        operación que hace estructuralmente soportable `ModoVentana.ABIERTA`
        (ver docstring del módulo): acumular contenido nuevo sin extender
        el plazo cada vez. Devuelve `False` sin hacer nada si `clave` no
        tiene ninguna entrada registrada — nunca crea una implícitamente
        (el llamador decide qué hacer con ese caso, típicamente tratarlo
        como "ventana no existe")."""
        entrada = self._entradas.get(clave)
        if entrada is None:
            return False
        entrada.payload = payload
        return True

    def obtener_payload(self, clave: str) -> Optional[Any]:
        entrada = self._entradas.get(clave)
        return entrada.payload if entrada is not None else None

    def momento_de(self, clave: str) -> Optional[datetime]:
        """Lee el `momento` real guardado — junto con `registrar(...,
        ahora=...)`, es lo que permite a un test mover una entrada
        existente hacia atrás en el tiempo sin reconstruirla a mano
        (`registrar(clave, payload=store.obtener_payload(clave),
        ahora=store.momento_de(clave) - timedelta(...))`) — nunca
        necesario en código de dominio real."""
        entrada = self._entradas.get(clave)
        return entrada.momento if entrada is not None else None

    def existe(self, clave: str) -> bool:
        return clave in self._entradas

    def __contains__(self, clave: str) -> bool:
        """Azúcar sintáctica de `existe` (`clave in store`) — mismo
        criterio de legibilidad que un `dict` normal, sin exponer
        ninguna otra semántica de dict (nunca `store[clave]`, que
        obligaría a fijar la forma del payload — ver `obtener_payload`/
        `actualizar_payload`)."""
        return self.existe(clave)

    def limpiar(self, clave: str) -> None:
        self._entradas.pop(clave, None)

    def transcurrido(self, clave: str, *, ahora: Optional[datetime] = None) -> Optional[timedelta]:
        """`None` si `clave` no tiene ninguna entrada registrada —
        deliberadamente distinto de `timedelta(0)`, que sí sería un
        evento real recién registrado (nunca se confunden)."""
        entrada = self._entradas.get(clave)
        if entrada is None:
            return None
        return (ahora or datetime.now(timezone.utc)) - entrada.momento

    def dentro_de_ventana(self, clave: str, ventana: VentanaDeTiempo, *, ahora: Optional[datetime] = None) -> bool:
        """`True` solo si hay una entrada Y el tiempo transcurrido desde
        su `momento` es menor que `ventana.duracion`. `False` tanto si
        no hay entrada como si la ventana ya venció — el llamador nunca
        necesita distinguir esos dos casos para decidir si bloquear/
        aceptar (si sí necesita distinguirlos por otra razón, usa
        `existe`/`transcurrido` directamente)."""
        transcurrido = self.transcurrido(clave, ahora=ahora)
        return transcurrido is not None and transcurrido < ventana.duracion

    def tiempo_restante(
        self, clave: str, ventana: VentanaDeTiempo, *, ahora: Optional[datetime] = None
    ) -> Optional[timedelta]:
        """`None` si no hay entrada registrada. Nunca negativo — si la
        ventana ya venció, devuelve `timedelta(0)` (el llamador decide
        si eso significa "ventana vencida"; nunca se le entrega un valor
        negativo que tendría que aprender a interpretar). El redondeo
        para mostrarle un número entero de segundos/minutos al usuario
        final (ej. "+1 segundo" para nunca decir "0 segundos" mientras
        todavía está bloqueado) es decisión del dominio, no de este
        método — ver `domains/health/gateway.py:_mensaje_enfriamiento`
        para el criterio real ya usado en producción."""
        transcurrido = self.transcurrido(clave, ahora=ahora)
        if transcurrido is None:
            return None
        restante = ventana.duracion - transcurrido
        return restante if restante > timedelta(0) else timedelta(0)
