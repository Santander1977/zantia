"""
Recado 070 (parte 4) — hallazgo REAL, encontrado con una prueba en
TIEMPO REAL (no simulada, `time.sleep()` real de ~2 minutos) contra el
código local, tras el reporte del usuario de que "el cierre/enfriamiento
sigue sin funcionar" pese al commit y despliegue del recado 069.

Transcripción real de la prueba (timestamps relativos, wall-clock real):

    [t=+0.0s] "no gracias ya termine" (PRIMER mensaje, SIN conversación
               abierta) -> "Fue un gusto atenderte. En 2 minutos
               estaremos disponibles nuevamente si necesitas algo más.
               ¡Hasta pronto!"
    [t=+0.0s] "hola" -> el saludo institucional COMPLETO con el menú de
               5 opciones — NUNCA debió pasar, el enfriamiento debía
               bloquear esto.
    [t=+60.0s] "sigues ahi?" -> el fallback genérico de menú — tampoco
               bloqueado.
    [t=+110.0s] "hola de nuevo" -> igual, sin bloqueo.
    [t=+125.0s] "hola" -> igual (esto sí sería correcto, PERO por la
               razón equivocada: nunca hubo enfriamiento que expirara).

Causa raíz exacta, confirmada leyendo el código (`gateway.py`,
`_resolver_por_intent`, rama `RequestIntent.SALIR` — alcanzada cuando el
paciente se despide SIN haber abierto antes una conversación, el camino
MÁS COMÚN de todos: "gracias"/"chao"/"5"/"salir" como primer mensaje, o
tras un cierre anterior): un comentario explícito del recado 060 decía
"Deliberadamente NO se toca `_cierre_reciente` acá" — decisión tomada
ANTES de que el recado 067 construyera el enfriamiento de 2 minutos
sobre esa MISMA estructura (`gateway._cierre_reciente`). La decisión del
060 nunca se revisó al agregar el enfriamiento: como esta rama nunca
escribía en `_cierre_reciente`, el chequeo de enfriamiento en
`handle_inbound_message` (que LEE esa estructura) nunca encontraba nada
que bloquear — CUALQUIER mensaje inmediatamente después de esta
despedida se procesaba con toda normalidad.

Ningún test anterior (recados 067/069) reprodujo esto porque TODOS
abrían una conversación primero ("necesito una cita") antes de
despedirse — ese camino SÍ pasa por `_cerrar_si_definitivo`, que SIEMPRE
armó `_cierre_reciente` correctamente desde el recado 067. El hueco
real estaba específicamente en la despedida SIN conversación previa.

Corrección: la rama `RequestIntent.SALIR` de `_resolver_por_intent`
ahora también arma `gateway._cierre_reciente[...]` (mismo patrón que
`_cerrar_si_definitivo`), con `es_despedida=True` siempre (esta rama es
exclusivamente despedida/salir). El requisito explícito del recado 069
(punto 4: "pasados los 2 minutos... saludo corto si aplica") además
reemplaza la expectativa original del recado 060 ("guion institucional
completo siempre") — un saludo corto tras el enfriamiento es ahora el
comportamiento correcto.
"""
from datetime import timedelta

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import MockAppointmentService


def test_despedida_sin_conversacion_abierta_arma_el_enfriamiento():
    """Reproduce EXACTAMENTE la transcripción real de arriba (usando
    manipulación determinista del timestamp en vez de `time.sleep()`
    real, para que la suite siga siendo rápida — la prueba en tiempo
    real que encontró el bug está documentada arriba, no repetida aquí
    turno por turno)."""
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-070-DESP-SIN-CONVO"

    r_cierre = handle_inbound_message(gateway, ref, "demo", "m1", "no gracias ya termine")
    assert "fue un gusto atenderte" in r_cierre.lower()

    # El hallazgo real: ANTES de este fix, `_cierre_reciente` nunca se
    # armaba en este camino — este assert es la prueba DIRECTA de la
    # causa raíz, no solo de sus síntomas.
    assert ref in gateway._cierre_reciente, "la despedida sin conversación abierta debía armar el enfriamiento"
    assert gateway._cierre_reciente.obtener_payload(ref)[1] is True  # es_despedida

    r_inmediato = handle_inbound_message(gateway, ref, "demo", "m2", "hola")
    assert "estamos en pausa" in r_inmediato.lower(), (
        f"un mensaje inmediato tras la despedida debía quedar bloqueado por el enfriamiento: {r_inmediato!r}"
    )
    assert "1. reservar una cita" not in r_inmediato.lower(), (
        f"NUNCA debía mostrar el menú completo durante el enfriamiento: {r_inmediato!r}"
    )

    # Pasados los 2 minutos: contacto normal (saludo corto, recado 069
    # punto 4).
    payload = gateway._cierre_reciente.obtener_payload(ref)
    momento = gateway._cierre_reciente.momento_de(ref)
    gateway._cierre_reciente.registrar(ref, payload=payload, ahora=momento - timedelta(minutes=3))
    r_pasado = handle_inbound_message(gateway, ref, "demo", "m3", "hola")
    assert "estamos en pausa" not in r_pasado.lower()
    assert "puedo ayudarte" in r_pasado.lower()


def test_despedida_por_opcion_de_menu_5_sin_conversacion_tambien_arma_el_enfriamiento():
    """Mismo hallazgo, alcanzado por la 5ta opción del menú numerado en
    vez de lenguaje natural — MISMA rama de código (`RequestIntent.SALIR`)."""
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-070-DESP-MENU5"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    r_cierre = handle_inbound_message(gateway, ref, "demo", "m2", "5")
    assert "fue un gusto atenderte" in r_cierre.lower()
    assert gateway._cierre_reciente.obtener_payload(ref)[1] is True

    r_inmediato = handle_inbound_message(gateway, ref, "demo", "m3", "necesito otra cita")
    assert "estamos en pausa" in r_inmediato.lower()
