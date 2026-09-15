"""
Recado 084 — dos hallazgos reportados por el usuario a partir de una
conversación real en producción (transcripción completa NO adjunta a
esta investigación — el mensaje del usuario incluía un placeholder sin
reemplazar; solo se confirmaron, con evidencia de código, las DOS
frases exactas que sí llegaron completas):

1. "consultame las citas del ultimo mes" — variante NO exacta de
   "consultar mis citas" — no coincidía con NINGUNA frase determinista
   de clasificación (`gateway.py:_interpretar_opcion_menu` exige la
   palabra "consultar" con límite de palabra completa — "consultame"
   nunca calza — y `intent.py:_CONSULTAR`/`brain.py:_CONSULTA_CITAS_EXISTENTES`
   solo reconocían la forma posesiva "mi(s) cita(s)", nunca "las citas"
   ni el pronombre enclítico "consultame"). Confirmado leyendo el código
   Y reproduciendo antes del fix: SIN un `selection_proposer` (LLM)
   configurado, el mensaje se trataba como "sin intención" y el paciente
   solo veía el saludo/menú — la pregunta sobre sus citas real quedaba
   sin responder, en silencio. Corregido agregando las formas reales
   ("consultame las citas", "consultame mis citas", "consultar las
   citas") a ambas listas deterministas (mismo criterio de duplicación
   ya documentado en `intent.py`) — ahora se clasifica exactamente
   igual, y con el mismo separador `\\n\\n` (recado 080) entre el
   saludo y la respuesta, que la forma exacta "consultar mis citas".

2. "ok enviame un email" (mensaje SIGUIENTE, inmediato, tras confirmar
   una reserva) — la categoría "pregunta sobre correo enviado" (recado
   058, `brain.py:_PREGUNTA_SOBRE_CORREO_ENVIADO`) SIGUE existiendo y
   sigue conectada (`_detectar_interrupcion_de_contexto`, reutilizada
   también por la ventana de gracia de un turno tras un cierre —
   `gateway.py:_evaluar_ventana_de_gracia`), pero su lista de frases
   solo cubría la forma PREGUNTA sobre algo ya hecho ("¿me enviaste...?",
   "¿llegó...?") — nunca la forma de PEDIDO/orden ("enviame", pronombre
   enclítico imperativo). Confirmado reproduciendo la secuencia real de
   3+1 turnos (reservar -> confirmar -> "ok enviame un email") antes del
   fix: como la Activity se cierra de inmediato al confirmarse la
   reserva (`gateway.py:_cerrar_si_definitivo`), el mensaje siguiente ya
   no encuentra conversación abierta, pasa por la ventana de gracia (que
   no reconocía la frase) y termina en `_enrutar_solicitud_nueva`, que
   tampoco la reconoce — sin ningún intent resuelto, cae al saludo CORTO
   genérico ("¡Buenos días! ¿Puedo ayudarte en algo más?"), exactamente
   el síntoma reportado. Corregido agregando las formas de pedido
   ("enviame"/"mandame"/"reenviame" + "el/un correo"/"email", y las
   variantes "puedes enviarme"/"puedes mandarme") a
   `_PREGUNTA_SOBRE_CORREO_ENVIADO` — el sistema no puede "reenviar" un
   correo bajo demanda (el único envío real ocurre dentro de
   `book_appointment`), así que la respuesta correcta a un PEDIDO de
   envío es la misma respuesta honesta ya existente sobre el estado
   real (`respuesta_pregunta_sobre_correo`).
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import MockAppointmentService
from domains.health.gateway import find_open_context
from domains.health.intent import classify_intent_or_none_estricto
from domains.health.models import RequestIntent


# ---------------------------------------------------------------------
# 1. "consultame las citas del ultimo mes" — clasificación determinista
#    (unidad, rápido de debuguear) + extremo a extremo.
# ---------------------------------------------------------------------
def test_consultame_las_citas_clasifica_igual_que_consultar_mis_citas():
    assert classify_intent_or_none_estricto("consultame las citas del ultimo mes") == RequestIntent.CONSULTAR_CITA


def test_consultame_las_citas_del_ultimo_mes_responde_con_las_citas_reales_separadas_del_saludo():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    respuesta = handle_inbound_message(
        gateway, "PAC-084-CONSULTA", "demo", "m1", "consultame las citas del ultimo mes"
    )

    # Antes del fix: el mensaje no coincidía con ninguna clasificación
    # determinista y, sin LLM configurado, el paciente solo veía el
    # saludo/menú — nunca una respuesta real a su pregunta.
    assert "revise y no tienes ninguna cita activa" in respuesta.lower() or "cita activa" in respuesta.lower(), (
        f"la pregunta sobre las citas quedó sin responder: {respuesta!r}"
    )
    # Mismo separador de párrafo que el recado 080 exige entre el saludo
    # institucional y la primera respuesta real — nunca pegados.
    assert "\n\n" in respuesta
    saludo, _, resto = respuesta.partition("\n\n")
    assert saludo.rstrip().endswith("5. Salir / terminar")
    assert "\n\n\n" not in respuesta


# ---------------------------------------------------------------------
# 2. "ok enviame un email" tras confirmar una reserva — reproduce la
#    secuencia real completa (reservar -> confirmar -> pedir el correo).
# ---------------------------------------------------------------------
def test_ok_enviame_un_email_tras_reservar_responde_sobre_el_correo_no_el_saludo_generico():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-084-CORREO"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, ref, "demo", "m2", "1")
    r3 = handle_inbound_message(gateway, ref, "demo", "m3", "la primera")
    assert "confirmado" in r3.lower()
    assert find_open_context(gateway, ref) is None

    r4 = handle_inbound_message(gateway, ref, "demo", "m4", "ok enviame un email")

    # Antes del fix: caía al saludo corto genérico, sin responder nada
    # sobre el correo — exactamente el síntoma reportado.
    assert "puedo ayudarte en algo mas" not in r4.lower().replace("á", "a").replace("é", "e"), (
        f"cayó al saludo corto genérico en vez de responder sobre el correo: {r4!r}"
    )
    # MockAppointmentService nunca recibe un correo real -> estado
    # honesto real es "nunca intentado" (mismo texto que recado 058).
    assert "no tenemos un correo tuyo registrado" in r4.lower()
