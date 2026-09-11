"""
Recado 058 — dos categorías nuevas en el detector centralizado ya
existente (`HealthBrain._detectar_interrupcion_de_contexto`, recados
047/053), reproduciendo una conversación real:

1. "confirmame si me enviastes el email" (tras una reserva exitosa) no
   se reconocía como pregunta sobre la acción recién hecha — caía al
   saludo corto (recado 057) + directo a preguntar servicio, arrancando
   una reserva nueva sin que el paciente la pidiera.
2. "no gracias ya termine" (despedida clara) se interpretaba como un
   intento de nombrar un servicio, quedando atascado pidiendo "el
   nombre tal como aparece en la lista".

Hallazgo adicional encontrado verificando la reproducción EXACTA de la
conversación real (3 turnos: cierre -> pregunta -> despedida): la
ventana de gracia de un turno (recado 050) es de UN SOLO USO — la
pregunta sobre el correo se reconocía bien, pero la despedida
INMEDIATAMENTE después ya no, porque la ventana ya se había consumido.
Corregido: la ventana se RE-ARMA cuando la interrupción detectada deja
la etapa exactamente igual que antes (nunca para las que sí cambian de
etapa — un solo turno a propósito, o abren un wizard que ya reabre la
conversación por su cuenta).
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import MockAppointmentService
from domains.health.brain import HealthBrain
from domains.health.gateway import find_open_context
from domains.health.models import Activity


# ---------------------------------------------------------------------
# 1. Reproducción EXACTA de la conversación real (3 turnos).
# ---------------------------------------------------------------------
def test_reproduce_conversacion_real_completa_cierre_pregunta_despedida():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    handle_inbound_message(gateway, "PAC-058", "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, "PAC-058", "demo", "m2", "1")
    r3 = handle_inbound_message(gateway, "PAC-058", "demo", "m3", "la primera")
    assert "confirmado" in r3.lower()
    assert find_open_context(gateway, "PAC-058") is None

    r4 = handle_inbound_message(gateway, "PAC-058", "demo", "m4", "confirmame si me enviastes el email")
    assert "servicio" not in r4.lower(), f"no debía arrancar una reserva nueva: {r4!r}"
    assert "hospital regional" not in r4.lower(), f"no debía repetir la presentación: {r4!r}"
    # Recado 054 — MockAppointmentService no tiene concepto de correo
    # real (nunca se le pasa `correo`), así que el estado real es
    # "nunca intentado" — la respuesta honesta para ese caso.
    assert "no tenemos un correo tuyo registrado" in r4.lower()

    r5 = handle_inbound_message(gateway, "PAC-058", "demo", "m5", "no gracias ya termine")
    assert "nombre tal como aparece" not in r5.lower(), f"no debía interpretarlo como un servicio: {r5!r}"
    assert "fue un gusto atenderte" in r5.lower() and "hasta pronto" in r5.lower()


# ---------------------------------------------------------------------
# 2. Varias formas reales de despedida.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto",
    [
        "no gracias ya termine",
        "gracias, ya no necesito más",
        "listo así está bien",
        "eso sería todo, gracias",
        "nada más por ahora",
    ],
)
def test_varias_formas_de_despedida_cierran_la_conversacion(texto):
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    handle_inbound_message(gateway, f"PAC-DESP-{hash(texto)}", "demo", "m1", "necesito una cita")
    respuesta = handle_inbound_message(gateway, f"PAC-DESP-{hash(texto)}", "demo", "m2", texto)
    assert "fue un gusto atenderte" in respuesta.lower()
    assert "nombre tal como aparece" not in respuesta.lower()
    assert "no logré identificar" not in respuesta.lower()


# ---------------------------------------------------------------------
# 3. La pregunta sobre el correo da una respuesta HONESTA — el envío
#    real (recado 054) sigue sin implementarse, así que la respuesta
#    NUNCA reafirma la promesa como un hecho confirmado.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto",
    [
        "confirmame si me enviastes el email",
        "me enviaste el correo?",
        "ya me llego el correo",
        "recibi el email?",
    ],
)
def test_pregunta_sobre_correo_responde_con_honestidad(texto):
    activity = Activity(
        activity_id="ACT-058-CORREO", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="medicina general",
    )
    brain = HealthBrain(lambda: activity, MockAppointmentService())
    from state.models import ConversationState

    salida = brain.interpret(texto, ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_decision"}), [])
    # Nunca afirma "sí, se envió" como un hecho — sin `resultado_de_herramientas`
    # (ningún `book_appointment` corrió en este test), el estado real es
    # "nunca intentado".
    assert "sí, se envió" not in salida.respuesta_propuesta.lower()
    assert "no tenemos un correo tuyo registrado" in salida.respuesta_propuesta.lower()
    assert salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]["etapa"] == "esperando_decision"


# ---------------------------------------------------------------------
# 3b. La respuesta cambia según el estado REAL de
#     `correo_confirmacion_enviado` en `resultado_de_herramientas`
#     (recado 054) — nunca un texto fijo sin importar lo que pasó.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "enviado, fragmento_esperado",
    [
        (True, "sí — te enviamos la confirmación por correo"),
        (False, "intentamos enviarte la confirmación por correo, pero no pudimos verificar"),
        (None, "no tenemos un correo tuyo registrado"),
    ],
)
def test_pregunta_sobre_correo_usa_estado_real_de_la_herramienta(enviado, fragmento_esperado):
    activity = Activity(
        activity_id="ACT-058-CORREO-2", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="medicina general",
    )
    brain = HealthBrain(lambda: activity, MockAppointmentService())
    from state.models import ConversationState

    estado = ConversationState(
        canal="demo",
        datos_recopilados={"etapa": "esperando_decision"},
        resultado_de_herramientas={"book_appointment": {"correo_confirmacion_enviado": enviado}},
    )
    salida = brain.interpret("me enviaste el correo?", estado, [])
    assert fragmento_esperado in salida.respuesta_propuesta.lower()


# ---------------------------------------------------------------------
# 4. Compatibilidad con HealthAnthropicBrain — el LLM puede variar la
#    calidez, pero el contenido esencial (honestidad, cierre real) no
#    cambia.
# ---------------------------------------------------------------------
class _DrafterQueVariaCalidez:
    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return texto_base.replace("Buena pregunta —", "Qué bueno que preguntas —").replace(
            "Fue un gusto atenderte", "Fue un placer haberte atendido"
        )


def test_pregunta_correo_funciona_igual_con_llm_activo():
    from domains.health.llm_brain import HealthAnthropicBrain
    from state.models import ConversationState

    activity = Activity(
        activity_id="ACT-058-LLM", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="medicina general",
    )
    brain_determinista = HealthBrain(lambda: activity, MockAppointmentService())
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueVariaCalidez())

    estado = ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_decision"})
    salida_determinista = brain_determinista.interpret("me enviaste el correo?", estado, [])
    salida_llm = brain_llm.interpret("me enviaste el correo?", estado, [])

    assert salida_llm.propuesta_de_actualizacion_de_estado == salida_determinista.propuesta_de_actualizacion_de_estado
    assert salida_llm.tool_requerida is None
    assert "no tenemos un correo tuyo registrado" in salida_llm.respuesta_propuesta.lower()


def test_despedida_funciona_igual_con_llm_activo():
    from domains.health.llm_brain import HealthAnthropicBrain
    from state.models import ConversationState

    activity = Activity(
        activity_id="ACT-058-LLM-2", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="medicina general",
    )
    brain_determinista = HealthBrain(lambda: activity, MockAppointmentService())
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueVariaCalidez())

    estado = ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_decision"})
    salida_determinista = brain_determinista.interpret("no gracias ya termine", estado, [])
    salida_llm = brain_llm.interpret("no gracias ya termine", estado, [])

    assert salida_llm.propuesta_de_actualizacion_de_estado == salida_determinista.propuesta_de_actualizacion_de_estado
    assert salida_llm.propuesta_de_actualizacion_de_estado["datos_recopilados"]["decision"] == "DECLINED"
    assert "fue un placer haberte atendido" in salida_llm.respuesta_propuesta.lower()


# ---------------------------------------------------------------------
# 5. Mensaje urgente posterior al 058 — hallazgo real de producción:
#    el trabajo del recado 058 NUNCA se había commiteado/desplegado
#    (confirmado vía `git log`/`git ls-remote`), así que ninguna de
#    estas despedidas se reconocía todavía. Reproduce la transcripción
#    real de 6+ turnos SIN conversación abierta (el paciente nunca
#    llegó a elegir ninguna opción del menú) — antes quedaba atrapado
#    repitiendo `_MENSAJE_INTENCION_NO_RECONOCIDA` indefinidamente.
# ---------------------------------------------------------------------
def test_reproduce_bucle_real_de_despedida_sin_conversacion_abierta():
    """Recado 070 — desde que la despedida SIN conversación abierta
    (`_resolver_por_intent`, rama `RequestIntent.SALIR`) también arma el
    enfriamiento de 2 minutos (hallazgo real, ver ese commit), solo el
    PRIMER mensaje de despedida de este bucle produce el texto de
    cierre — los siguientes, todavía dentro del enfriamiento, deben
    producir el mensaje de bloqueo (nunca el menú repetido, que era el
    bug original de este test)."""
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-BUCLE-058"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")

    textos = (
        "No gracias q tengas buenas noches",
        "No ya terminé",
        "Chao",
        "No sé que hacer chao",
    )
    for i, texto in enumerate(textos):
        respuesta = handle_inbound_message(gateway, ref, "demo", f"m-{hash(texto)}", texto)
        assert "no logré identificar" not in respuesta.lower(), (
            f"quedó atrapado en el loop del menú con: {texto!r} -> {respuesta!r}"
        )
        if i == 0:
            assert "fue un gusto atenderte" in respuesta.lower()
        else:
            assert "estamos en pausa" in respuesta.lower(), (
                f"debía estar en enfriamiento tras la primera despedida: {texto!r} -> {respuesta!r}"
            )


# ---------------------------------------------------------------------
# 6. Salida EXPLÍCITA y garantizada por el menú (opción 5 / palabra
#    "salir"/"terminar"), independiente de si el lenguaje natural se
#    reconoce o no — MISMO mecanismo ya existente
#    (`_interpretar_opcion_menu`/`_resolver_por_intent`, nunca un camino
#    nuevo y paralelo).
# ---------------------------------------------------------------------
@pytest.mark.parametrize("texto", ["5", "salir", "terminar", "Salir, gracias"])
def test_opcion_de_menu_salir_cierra_la_conversacion(texto):
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = f"PAC-SALIR-{hash(texto)}"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    respuesta = handle_inbound_message(gateway, ref, "demo", "m2", texto)
    assert "fue un gusto atenderte" in respuesta.lower()
    assert find_open_context(gateway, ref) is None


def test_mensaje_no_reconocido_incluye_la_opcion_de_salir():
    from domains.health.gateway import _MENSAJE_INTENCION_NO_RECONOCIDA, _MENU_NUMERADO

    assert "5. salir" in _MENU_NUMERADO.lower()
    assert "salir" in _MENSAJE_INTENCION_NO_RECONOCIDA.lower()


# ---------------------------------------------------------------------
# 7. Recado 060 — hallazgo urgente de producción real: tras usar la
#    opción "5" del menú (SALIR sin conversación abierta, sección 6
#    arriba), un "Hola" siguiente quedaba atrapado repitiendo
#    `_MENSAJE_INTENCION_NO_RECONOCIDA` en vez de mostrar el saludo
#    institucional completo de nuevo. Causa raíz: a diferencia del
#    cierre de una Activity REAL (`_cerrar_si_definitivo`, que libera
#    `_saludo_mostrado`), la rama `RequestIntent.SALIR` de
#    `_resolver_por_intent` nunca hay Activity que cerrar (se alcanza
#    SIN conversación abierta), así que nadie liberaba esa marca —
#    `patient_reference` seguía marcado como "ya se le mostró el saludo"
#    desde el turno anterior, para siempre.
#
#    Recado 070 — actualizado: esta MISMA rama (SALIR sin conversación
#    abierta) ahora TAMBIÉN arma el enfriamiento de 2 minutos (hallazgo
#    real GRAVE, confirmado con una prueba en tiempo real: antes NUNCA
#    lo armaba, así que el enfriamiento jamás se activaba para el camino
#    de despedida más común de todos). Consecuencia correcta y
#    esperada: un "Hola" INMEDIATO tras la despedida ya no muestra el
#    guion completo — debe mostrar el mensaje de bloqueo del
#    enfriamiento (requisito explícito del recado 069). Pasados los 2
#    minutos, el requisito explícito del recado 069 (punto 4) es
#    "saludo corto si aplica" — no el guion completo, que era la
#    expectativa del recado 060 ANTES de que existiera el enfriamiento.
# ---------------------------------------------------------------------
def test_hola_despues_de_opcion_salir_activa_el_enfriamiento_y_luego_saludo_corto():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-SALIR-LUEGO-HOLA-060"
    r1 = handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    assert "1. reservar una cita" in r1.lower(), f"m1 debía mostrar el menú: {r1!r}"

    r2 = handle_inbound_message(gateway, ref, "demo", "m2", "5")
    assert "fue un gusto atenderte" in r2.lower()
    assert find_open_context(gateway, ref) is None
    assert gateway._cierre_reciente.obtener_payload(ref)[1] is True  # es_despedida -> arma el enfriamiento

    r3 = handle_inbound_message(gateway, ref, "demo", "m3", "Hola")
    assert "no logré identificar" not in r3.lower(), (
        f"quedó atrapado en el error genérico tras la opción 5: {r3!r}"
    )
    assert "estamos en pausa" in r3.lower(), (
        f"un 'Hola' INMEDIATO tras la despedida debía quedar bloqueado por el enfriamiento: {r3!r}"
    )

    # Pasados los 2 minutos: contacto normal, saludo CORTO (recado 069,
    # punto 4 — "no la variante completa", a diferencia de antes de que
    # existiera el enfriamiento).
    from datetime import timedelta

    payload = gateway._cierre_reciente.obtener_payload(ref)
    momento = gateway._cierre_reciente.momento_de(ref)
    gateway._cierre_reciente.registrar(ref, payload=payload, ahora=momento - timedelta(minutes=3))
    r4 = handle_inbound_message(gateway, ref, "demo", "m4", "Hola")
    assert "no logré identificar" not in r4.lower(), (
        f"quedó atrapado en el error genérico pasado el enfriamiento: {r4!r}"
    )
    assert "estamos en pausa" not in r4.lower()
    assert "1. reservar una cita" not in r4.lower(), f"debía ser el saludo CORTO, no el completo: {r4!r}"
    assert "puedo ayudarte" in r4.lower()
