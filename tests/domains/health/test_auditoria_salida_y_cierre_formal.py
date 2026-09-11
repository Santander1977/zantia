"""
Recado 067 — auditoría completa del callejón sin salida ("salir"/"exit")
+ condición de carrera en la despedida (mensajes duplicados) +
despedida formal con enfriamiento real de 2 minutos.

Reproduce, con evidencia real (no supuesta), 3 hallazgos de hoy:
1. Mensajes duplicados/contradictorios al despedirse — causa raíz:
   `handle_inbound_message` (gateway.py) SIEMPRE anteponía un saludo de
   bienvenida al resultado de `_enrutar_solicitud_nueva`, incluso
   cuando ese resultado YA era un mensaje de despedida completo.
   Corregido: `_enrutar_solicitud_nueva` ahora devuelve `(texto,
   es_cierre)`; un cierre NUNCA lleva saludo antepuesto. Hallazgo
   adicional en el camino: "gracias ya no necesito mas" (literalmente
   en `_DESPEDIDA`) se interceptaba antes por `classify_intent_or_none`
   ("necesito" activa `_tiene_senal_de_intencion`, recado 056) —
   reordenado: despedida/salir se revisan ANTES que ese fallback.
2. "salir"/"exit" nunca se reconocían DENTRO de una conversación
   abierta (`HealthBrain.interpret()`, cualquier etapa) — causa raíz:
   `_DESPEDIDA` excluye a propósito "salir"/"terminar" sueltos (recado
   059, falsos positivos reales tipo "quiero TERMINAR de agendar"), y
   la única lista que SÍ los reconocía (`_MENU_OPCIONES`) solo se
   revisa en `gateway.py:_enrutar_solicitud_nueva` (sin conversación
   abierta) — inalcanzable una vez que hay una Activity en curso.
   Corregido: `_es_solicitud_de_salir` (antes solo en gateway.py, ahora
   en brain.py, MISMA lista) se revisa con máxima prioridad en
   `HealthBrain.interpret()`, en TODAS las etapas sin excepción
   (incluidas `esperando_documento_beneficiario`/
   `esperando_confirmacion_beneficiario`, antes sin ninguna salida).
3. Un mensaje de feedback/comentario largo con un dígito suelto sin
   relación ("... en 2 minutos puede iniciar otro trámite") se
   interpretaba como si el paciente hubiera elegido la 2da opción de
   fecha/horario ya ofrecida — causa raíz: `_elegir_opcion`
   (brain.py)/`_elegir_opcion_ordinal` (gateway.py) solo exigían que el
   dígito fuera un TOKEN propio (`\\b...\\b`, recados 053/056), sin
   límite de longitud del mensaje completo — REPRODUCIDO creando una
   RESERVA REAL a partir de puro feedback, sin que el paciente pidiera
   nada. Corregido con `_indice_ordinal_seguro` (compartida entre
   ambas funciones): exige además que el mensaje completo tenga como
   mucho 8 palabras.

Y agrega la despedida formal + enfriamiento de 2 minutos pedidos
explícitamente (ver `_texto_despedida`/`_VENTANA_ENFRIAMIENTO`,
gateway.py).
"""
from datetime import datetime, timedelta, timezone

import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    accept_activity, contact_patient, handle_patient_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.gateway import build_health_gateway, find_open_context, handle_inbound_message
from domains.health.models import Activity, ManagementStatus


class _ServicioDosOpciones(MockAppointmentService):
    """Catálogo con 2 servicios reales — necesario para alcanzar
    `esperando_servicio` (con 1 solo servicio, el sistema lo asume
    directo y nunca pregunta, recado 030)."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["medicina general", "odontologia"]
        self._slots["SLOT1"] = AvailabilitySlot(
            slot_id="SLOT1", service="medicina general", professional="Dra. Prueba",
            location="Sede Norte", date="2026-09-05", time="09:00",
        )


def _texto_es_cierre(texto: str) -> bool:
    """Recado 069 — texto EXACTO pedido por el usuario. Confirma
    también las 2 prohibiciones explícitas: nunca la pregunta "¿algo
    más?" ni el menú numerado en el mismo mensaje."""
    minusculas = texto.lower()
    es_el_texto_de_cierre = (
        "fue un gusto atenderte" in minusculas
        and "en 2 minutos estaremos disponibles nuevamente" in minusculas
        and "hasta pronto" in minusculas
    )
    sin_pregunta_de_mas = "puedo ayudarte en algo" not in minusculas and "puedo ayudarlo en algo" not in minusculas
    sin_menu = "1. reservar una cita" not in minusculas
    return es_el_texto_de_cierre and sin_pregunta_de_mas and sin_menu


def _texto_es_fallback_generico(texto: str) -> bool:
    return "no logré identificar" in texto.lower() or "confirmas si es la 1" in texto.lower() or "confirmas 1, 2 o 3" in texto.lower()


# ---------------------------------------------------------------------
# 1. Transcripción real — duplicación de mensajes al despedirse.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto",
    ["gracias ya no necesito mas", "chao", "chao gracias", "no gracias ya termine", "5", "exit", "salir"],
)
def test_despedida_nunca_duplica_mensajes(texto):
    """Reproduce el escenario exacto que antes producía duplicación:
    saludo corto activo (cierre reciente sin enfriamiento) + primer
    mensaje de esta pre-conversación YA es una despedida clara — antes
    concatenaba saludo de bienvenida + despedida en el mismo turno."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = f"PAC-DUP-{hash(texto)}"
    gateway._cierre_reciente[ref] = (datetime.now(timezone.utc), "Paciente Ficticio", False)
    r = handle_inbound_message(gateway, ref, "demo", "m1", texto)
    assert "puedo ayudarte en algo" not in r.lower() and "puedo ayudarlo en algo" not in r.lower(), (
        f"no debía llevar un saludo de bienvenida antepuesto a la despedida: {r!r}"
    )
    assert _texto_es_cierre(r), f"debía ser el texto de despedida formal completo: {r!r}"


def test_mensaje_ambiguo_sin_despedida_sigue_dando_un_solo_mensaje():
    """Control: un mensaje genuinamente ambiguo (ni despedida — ni
    siquiera con el reconocimiento ampliado del recado 069 — ni
    intención reconocible) sigue dando UN solo mensaje (el saludo o el
    fallback), nunca dos concatenados — el fix no debía romper esto.
    Recado 069: "gracias" sola AHORA es despedida a propósito (ver
    `test_despedida_nunca_duplica_mensajes`), así que este control usa
    una frase que sigue sin ser ninguna de las dos cosas."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-AMBIGUO"
    gateway._cierre_reciente[ref] = (datetime.now(timezone.utc), "Paciente Ficticio", False)
    r = handle_inbound_message(gateway, ref, "demo", "m1", "mmm no se")
    assert r.count("¡Buenas") <= 1 and "fue un gusto atenderte" not in r.lower()


# ---------------------------------------------------------------------
# 2. Transcripción real — feedback interpretado como selección de
#    fecha/horario, inventando una reserva/oferta no pedida.
# ---------------------------------------------------------------------
_MENSAJE_FEEDBACK = "Aquí en este texto debe decir que finalizó la solicitud y que en 2 minutos puede iniciar otro trámite"


def test_feedback_con_digito_suelto_no_se_confunde_con_seleccion_de_fecha():
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-FEEDBACK-FECHA"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r = handle_inbound_message(gateway, ref, "demo", "m2", _MENSAJE_FEEDBACK)
    assert _texto_es_fallback_generico(r), f"debía caer en el fallback genérico de aclaración: {r!r}"
    assert "domingo" not in r.lower() and "sabado" not in r.lower() and "lunes" not in r.lower()


def test_feedback_con_digito_suelto_no_reserva_una_cita_real():
    """El caso MÁS grave: en `esperando_horario`, el mismo mensaje
    llegó a completar una RESERVA REAL antes de este fix."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-FEEDBACK-HORARIO"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, ref, "demo", "m2", "1")  # elige fecha -> ofrece horarios
    r = handle_inbound_message(gateway, ref, "demo", "m3", _MENSAJE_FEEDBACK)
    assert "confirmado" not in r.lower(), f"NO debía reservar nada a partir de puro feedback: {r!r}"
    assert _texto_es_fallback_generico(r)
    # Confirma también a nivel de estado real, no solo por el texto.
    contexto = find_open_context(gateway, ref)
    assert contexto is not None, "la conversación debía seguir abierta, sin haberse cerrado por una reserva falsa"


def test_ordinal_corto_legitimo_sigue_funcionando():
    """Control anti-regresión: una respuesta corta real ("la 2", "2",
    "segunda") sigue seleccionando correctamente — el límite de 8
    palabras no debía romper el caso normal."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-ORDINAL-OK"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r = handle_inbound_message(gateway, ref, "demo", "m2", "la 2, por favor")
    assert "domingo" in r.lower(), f"debía elegir la 2da fecha real: {r!r}"


# ---------------------------------------------------------------------
# 3. Auditoría completa de "salir"/"exit" — TODOS los puntos donde el
#    sistema espera una respuesta específica.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_menu_principal(texto):
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = f"PAC-MENU-{texto}"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    r = handle_inbound_message(gateway, ref, "demo", "m2", texto)
    assert _texto_es_cierre(r)


@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_seleccion_de_servicio(texto):
    gateway = build_health_gateway(MockActivitySource(), _ServicioDosOpciones(), ReminderManager(), MockActivityResultSink())
    ref = f"PAC-SERVICIO-{texto}"
    r1 = handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    assert "servicio" in r1.lower()
    r2 = handle_inbound_message(gateway, ref, "demo", "m2", texto)
    assert _texto_es_cierre(r2), f"'salir'/'exit' debía cerrar durante la selección de servicio: {r2!r}"
    assert find_open_context(gateway, ref) is None


@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_seleccion_de_fecha(texto):
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = f"PAC-FECHA-{texto}"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r = handle_inbound_message(gateway, ref, "demo", "m2", texto)
    assert _texto_es_cierre(r)
    assert find_open_context(gateway, ref) is None


@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_seleccion_de_horario(texto):
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = f"PAC-HORARIO-{texto}"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, ref, "demo", "m2", "1")
    r = handle_inbound_message(gateway, ref, "demo", "m3", texto)
    assert _texto_es_cierre(r)
    assert find_open_context(gateway, ref) is None


@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_esperando_decision(texto, services, activity_factory):
    """Flujo OUTBOUND (demanda inducida): la primera pregunta real es
    sí/no en `esperando_decision` — solo alcanzable así, ya que el
    camino inbound de `gateway.py` auto-envía "sí" (ver
    `_resolver_programar_cita`)."""
    activity = services["source"].create(activity_factory())
    from domains.health import build_health_agent_context

    context = build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )
    accept_activity(context)
    contact_patient(context)
    r = handle_patient_message(context, "m1", texto)
    assert _texto_es_cierre(r)
    assert context.activity.management_status == ManagementStatus.DECLINED


@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_seleccion_de_reprogramacion(texto, services):
    """Flujo OUTBOUND con una cita YA confirmada — el paciente responde
    a un recordatorio pidiendo reprogramar, llega a
    `esperando_seleccion_reprogramacion` (lista de horarios
    alternativos ya ofrecidos)."""
    from domains.health import build_health_agent_context
    from domains.health.models import Activity as _Activity

    activity = services["source"].create(_Activity(
        activity_id=f"ACT-REPROG-{texto}", source_system="IPS-DEMO", correlation_id="corr-reprog",
        objective="Seguimiento", patient_reference=f"PAC-REPROG-{texto}",
        patient_contact={"nombre": "Paciente Ficticio"}, service="medicina general",
        appointment_id="CITA-1",
    ))
    context = build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )
    accept_activity(context)
    contact_patient(context)
    r1 = handle_patient_message(context, "m1", "no puedo asistir, necesito reprogramar")
    assert "opciones" in r1.lower() or "2026-09" in r1
    r2 = handle_patient_message(context, "m2", texto)
    assert _texto_es_cierre(r2), f"'salir'/'exit' debía cerrar durante la selección de reprogramación: {r2!r}"


@pytest.mark.parametrize("texto", ["salir", "exit"])
def test_salir_funciona_en_wizard_de_beneficiario(texto):
    """Antes de este recado: sin NINGUNA salida — ni siquiera
    escalamiento tras intentos fallidos, a diferencia del wizard de
    identidad de gateway.py. `_PARA_OTRO` (gestión para un beneficiario)
    solo se activa con un `AppointmentService` que expone
    `buscar_paciente` (HrmmAppointmentService) — con `MockAppointmentService`
    esa rama nunca se alcanza, por diseño (recado 013), así que este
    test necesita el mismo doble real de HTTP que el resto de la suite
    de HrmmAppointmentService."""
    import os

    from domains.health.hrmm_appointment_service import HrmmAppointmentService
    from domains.health.hrmm_catalog import CatalogMirror
    from domains.health.hrmm_http import FakeHttpClient, HttpResponse

    os.environ["HRMM_BACKEND_SECRET"] = "secreto-de-prueba-no-real"

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-05", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, [])
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())
    ref = f"PAC-BENEF-{texto}"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r1 = handle_inbound_message(gateway, ref, "demo", "m2", "es para mi hija")
    assert "documento" in r1.lower()
    r2 = handle_inbound_message(gateway, ref, "demo", "m3", texto)
    assert _texto_es_cierre(r2)
    assert find_open_context(gateway, ref) is None


# ---------------------------------------------------------------------
# 4. Despedida formal + enfriamiento de 2 minutos.
# ---------------------------------------------------------------------
def test_enfriamiento_informa_tiempo_restante_real():
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-ENFRIA-1"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    r_cierre = handle_inbound_message(gateway, ref, "demo", "m2", "no gracias ya termine")
    assert _texto_es_cierre(r_cierre)
    assert gateway._cierre_reciente[ref][2] is True  # es_despedida

    r_durante = handle_inbound_message(gateway, ref, "demo", "m3", "hola de nuevo")
    assert "estamos en pausa" in r_durante.lower()
    assert "podremos atenderte de nuevo en 2 minutos y 0 segundos" in r_durante.lower()
    assert "no logré identificar" not in r_durante.lower()

    # Simula que ya pasaron 90 de los 120 segundos — el tiempo restante
    # informado debe reflejarlo (no un valor fijo): quedan 30 segundos,
    # 0 minutos.
    momento, nombre, es_desp = gateway._cierre_reciente[ref]
    gateway._cierre_reciente[ref] = (momento - timedelta(seconds=90), nombre, es_desp)
    r_casi = handle_inbound_message(gateway, ref, "demo", "m4", "ya?")
    assert "0 minutos y 30 segundos" in r_casi.lower()


def test_pasado_el_enfriamiento_es_un_contacto_completamente_nuevo():
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-ENFRIA-2"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, ref, "demo", "m2", "no gracias ya termine")

    momento, nombre, es_desp = gateway._cierre_reciente[ref]
    gateway._cierre_reciente[ref] = (momento - timedelta(minutes=3), nombre, es_desp)
    r = handle_inbound_message(gateway, ref, "demo", "m3", "hola")
    assert "segundos para poder atenderte" not in r.lower()
    assert "buenas" in r.lower() and "puedo ayudarte" in r.lower()  # saludo corto (aún dentro de los 30 min)


def test_reserva_confirmada_nunca_activa_el_enfriamiento():
    """Control crítico: el enfriamiento es SOLO para despedida/decline
    — una reserva exitosa debe poder seguir conversando de inmediato."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-ENFRIA-RESERVA"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, ref, "demo", "m2", "1")
    r_cierre = handle_inbound_message(gateway, ref, "demo", "m3", "1")
    assert "confirmado" in r_cierre.lower()
    assert gateway._cierre_reciente[ref][2] is False  # NO es despedida

    r_inmediato = handle_inbound_message(gateway, ref, "demo", "m4", "necesito otra cita")
    assert "segundos para poder atenderte" not in r_inmediato.lower()
    assert "fechas disponibles" in r_inmediato.lower()


def test_enfriamiento_no_interfiere_con_ventana_de_gracia_pasado_el_periodo():
    """Pasados los 2 minutos (pero dentro de los 30), un mensaje que SÍ
    es una interrupción real sobre lo recién cerrado (recado 050) debe
    seguir funcionando normalmente."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-ENFRIA-GRACIA"
    handle_inbound_message(gateway, ref, "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, ref, "demo", "m2", "1")
    handle_inbound_message(gateway, ref, "demo", "m3", "1")  # reserva CONFIRMADA (sin enfriamiento)

    # No hay enfriamiento (fue una reserva, no una despedida) — la
    # ventana de gracia debe seguir disponible de inmediato.
    r = handle_inbound_message(gateway, ref, "demo", "m4", "en realidad era para mi hija")
    assert "no logré identificar" not in r.lower()
