"""
Bug real de producción (recado 030) — cuarto hallazgo de la misma
conversación real de Telegram (continúa 026/027):

1. "Que tienes disponible para citas" (SIN tilde en "que") seguía sin
   listar el catálogo real — el fix del recado 027 solo cubría la forma
   CON tilde ("qué"). Causa raíz confirmada con `classify_intent()`
   directo: un paciente real omite tildes constantemente al escribir
   rápido, y toda `_INFORMACION`/`_CONSULTAR_SERVICIOS` exigía la tilde
   exacta — cayendo en silencio al fallback por defecto (PROGRAMAR_CITA,
   que además asumía "medicina general" sin que el paciente lo pidiera).

2. Encadenado con lo anterior: una vez en "sin disponibilidad", incluso
   respuestas CLARAMENTE afirmativas como "Si claro ayúdame puedes
   orientarme mejor" no avanzaban — "si" sin tilde, siendo la PRIMERA
   palabra del mensaje (sin coma ni espacio previo), no coincidía con
   ningún patrón de `_ACEPTA` del recado 026. Corregido con
   reconocimiento de "sí"/"no" por LÍMITE DE PALABRA sobre texto sin
   tildes (`_es_afirmativo`/`_es_negativo`), reordenando además la
   prioridad de ramas en `_interpretar_decision` para que frases
   específicas (humano, no puede ahora, etc.) se revisen ANTES que el
   chequeo genérico de "no" — evita que "no, quiero hablar con alguien"
   se declare como un simple "no" en vez de escalar.

3. `_nueva_activity_sintetica` (`gateway.py`) asumía SIEMPRE
   `service="medicina general"` para cualquier solicitud de reserva
   nueva, sin que el paciente lo haya confirmado — causa estructural
   detrás de "sin disponibilidad" en primer lugar. Corregido: si el
   catálogo real tiene más de un servicio, se pregunta ANTES de mirar
   disponibilidad (`HealthBrain._interpretar_servicio`, nueva etapa
   "esperando_servicio"); con 0 o 1 servicio real, no hay nada que
   desambiguar y se sigue sin preguntar.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import _sin_tildes as _sin_tildes_brain
from domains.health.intent import _sin_tildes as _sin_tildes_intent
from domains.health.intent import classify_intent
from domains.health.models import RequestIntent


# ---------------------------------------------------------------------
# 0. La normalización de tildes NUNCA toca la "ñ" — "año"/"ano" son
#    palabras distintas en español (cumpleaños vs. una parte del
#    cuerpo); confundirlas sería un bug nuevo, no una corrección.
# ---------------------------------------------------------------------
def test_normalizacion_de_tildes_no_toca_la_ene_con_tilde_brain():
    assert _sin_tildes_brain("año") == "año"
    assert _sin_tildes_brain("año") != "ano"
    # Control positivo, en la MISMA llamada: las vocales sí se normalizan.
    assert _sin_tildes_brain("¿Cuál año, señor?") == "¿Cual año, señor?"


def test_normalizacion_de_tildes_no_toca_la_ene_con_tilde_intent():
    assert _sin_tildes_intent("año") == "año"
    assert _sin_tildes_intent("año") != "ano"


# ---------------------------------------------------------------------
# 1. classify_intent — accent-insensitive.
# ---------------------------------------------------------------------
def test_classify_intent_reconoce_catalogo_sin_tilde():
    assert classify_intent("Que tienes disponible para citas") == RequestIntent.INFORMACION_SERVICIO
    assert classify_intent("que tienes disponible") == RequestIntent.INFORMACION_SERVICIO
    assert classify_intent("cual tienes") == RequestIntent.INFORMACION_SERVICIO
    assert classify_intent("cuales servicios tienes") == RequestIntent.INFORMACION_SERVICIO


def test_classify_intent_sigue_reconociendo_catalogo_con_tilde():
    """Control: la forma CON tilde (ya cubierta en el recado 027) sigue
    funcionando exactamente igual."""
    assert classify_intent("Qué tienes disponible para citas") == RequestIntent.INFORMACION_SERVICIO
    assert classify_intent("Programar cuál servicios tienes disponible") == RequestIntent.INFORMACION_SERVICIO


def test_pregunta_por_catalogo_sin_tilde_lista_catalogo_real(gateway):
    """Reproduce el mensaje real exacto reportado."""
    respuesta = handle_inbound_message(gateway, "TG-030-1", "telegram", "m1", "Que tienes disponible para citas")
    assert "medicina general" in respuesta.lower()
    assert "sin disponibilidad" not in respuesta.lower()
    assert "por ahora no tengo horarios" not in respuesta.lower()


# ---------------------------------------------------------------------
# 2. Reconocimiento de "sí"/"no" por límite de palabra, sin tilde.
# ---------------------------------------------------------------------
def test_respuesta_afirmativa_sin_tilde_como_primera_palabra_avanza(gateway, services):
    """'Si claro ayúdame...' (real, reportado) — 'si' es la PRIMERA
    palabra, sin tilde, sin coma: no coincidía con ningún patrón viejo."""
    respuesta = handle_inbound_message(
        gateway, "TG-030-2", "telegram", "m1", "Si claro ayudame puedes orientarme mejor",
    )
    assert "opciones disponibles" in respuesta.lower()


def test_respuesta_afirmativa_variante_real_tambien_avanza(gateway):
    respuesta = handle_inbound_message(gateway, "TG-030-3", "telegram", "m1", "Si claro necesito tu ayuda")
    assert "opciones disponibles" in respuesta.lower()


def test_no_puedo_asistir_ahora_no_se_confunde_con_declinar(context):
    """Regresión del reordenamiento de prioridad (recado 030): 'no'
    como palabra suelta no debe ganarle a la rama específica de
    reprogramar/'no puede ahora' — antes de esto, mover `_es_negativo`
    a chequeo por límite de palabra sin reordenar habría roto esto."""
    from domains.health import accept_activity, contact_patient, handle_patient_message

    accept_activity(context)
    contact_patient(context)
    respuesta = handle_patient_message(context, "m1", "no puedo ahora, llámame después")
    assert "entiendo perfectamente" not in respuesta.lower()
    assert "en otro momento" in respuesta.lower()


def test_no_quiero_hablar_con_alguien_escala_y_no_declina(context):
    from domains.health import ManagementStatus, accept_activity, contact_patient, handle_patient_message

    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "no, prefiero hablar con un asesor")
    assert context.activity.management_status == ManagementStatus.ESCALATED


def test_declinar_bare_sigue_funcionando(context):
    from domains.health import ManagementStatus, accept_activity, contact_patient, handle_patient_message

    accept_activity(context)
    contact_patient(context)
    respuesta = handle_patient_message(context, "m1", "No")
    assert "entiendo perfectamente" in respuesta.lower()
    assert context.activity.management_status == ManagementStatus.DECLINED


def test_mensaje_no_reconocido_aclara_en_vez_de_repetir_ciegamente(context):
    """Pedido explícito del usuario (recado 030): un mensaje que no es
    claramente sí/no ni ninguna otra intención reconocida debe reconocer
    el intento del paciente, no repetir la pregunta original tal cual."""
    from domains.health import accept_activity, contact_patient, handle_patient_message

    accept_activity(context)
    contact_patient(context)
    respuesta = handle_patient_message(context, "m1", "Piensa")
    assert "no logré entender" in respuesta.lower()
    assert "sí" in respuesta.lower() and "no" in respuesta.lower()


# ---------------------------------------------------------------------
# 3. Preguntar servicio ANTES de disponibilidad, cuando hay más de uno.
# ---------------------------------------------------------------------
class _AppointmentServiceDosServicios(MockAppointmentService):
    """Catálogo real con DOS servicios — para probar que, cuando hay
    ambigüedad real, el sistema pregunta antes de asumir."""

    def _seed_fictional_data(self) -> None:
        super()._seed_fictional_data()
        self._catalogo_servicios = ["medicina general", "odontologia"]
        slot = AvailabilitySlot(
            slot_id="ODONTO-1", service="odontologia", professional="Dra. Ruiz",
            location="Sede Norte", date="2026-09-10", time="09:00",
        )
        self._slots[slot.slot_id] = slot


def _gateway_dos_servicios():
    return build_health_gateway(
        MockActivitySource(), _AppointmentServiceDosServicios(),
        ReminderManager(), MockActivityResultSink(),
    )


def test_con_catalogo_de_dos_servicios_pregunta_antes_de_ofrecer_disponibilidad():
    gateway = _gateway_dos_servicios()
    r1 = handle_inbound_message(gateway, "TG-030-SERV-1", "telegram", "m1", "necesito una cita")
    assert "medicina general" in r1.lower() and "odontologia" in r1.lower()
    assert "opciones disponibles" not in r1.lower()
    assert "sin disponibilidad" not in r1.lower() and "por ahora no tengo horarios" not in r1.lower()


def test_nombrar_el_servicio_real_despues_de_la_pregunta_avanza_a_disponibilidad():
    gateway = _gateway_dos_servicios()
    pref = "TG-030-SERV-2"
    handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "odontologia")
    assert "opciones disponibles" in r2.lower()


def test_nombrar_servicio_sin_tilde_tambien_matchea_el_nombre_real_con_tilde():
    gateway = build_health_gateway(
        MockActivitySource(),
        type(
            "_ConOdontologiaConTilde", (MockAppointmentService,),
            {"_seed_fictional_data": lambda self: (
                MockAppointmentService._seed_fictional_data(self),
                setattr(self, "_catalogo_servicios", ["medicina general", "odontología"]),
            )},
        )(),
        ReminderManager(), MockActivityResultSink(),
    )
    pref = "TG-030-SERV-3"
    handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "odontologia")
    # Sin turnos reales para "odontología" en este servicio de prueba —
    # lo que importa es que el nombre SÍ se identificó (no cae en el
    # mensaje de "no logré identificar").
    assert "no logré identificar" not in r2.lower()


def test_servicio_no_identificado_no_asume_ninguno():
    gateway = _gateway_dos_servicios()
    pref = "TG-030-SERV-4"
    handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "no sé, cualquiera")
    assert "no logré identificar" in r2.lower()
    assert "medicina general" in r2.lower() and "odontologia" in r2.lower()


def test_con_un_solo_servicio_real_no_pregunta_nada_comportamiento_sin_cambios(gateway):
    """Control: MockAppointmentService por defecto (un solo servicio)
    sigue yendo directo a disponibilidad, exactamente como antes."""
    respuesta = handle_inbound_message(gateway, "TG-030-UNO", "telegram", "m1", "necesito una cita")
    assert "opciones disponibles" in respuesta.lower()
