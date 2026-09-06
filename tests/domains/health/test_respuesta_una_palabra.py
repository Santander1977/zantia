"""
Bug real de producción (recado 026) — primera conversación real de un
paciente por Telegram, ya con identidad confirmada:

1. Tras "¿Te gustaría que te ayude a programar tu atención? Puedes
   responder sí o no.", el paciente respondió literalmente "Si" (sin
   tilde, mensaje completo, sin coma). `HealthBrain._ACEPTA`
   (`domains/health/brain.py`) solo reconocía "sí" (con tilde), "si,"
   (con coma) o " si " (con espacios alrededor) — un "Si" bare no
   coincidía con NINGÚN patrón, y la conversación quedaba repitiendo la
   misma pregunta sin avanzar nunca, sin importar qué escribiera el
   paciente después.

2. Por separado: cuando `AppointmentService.get_availability()` no
   tiene turnos, el mensaje original ("...te contactamos pronto.")
   contenía una frase de `guardrails/rules.py:_PROMESAS_PROHIBIDAS`
   (lección de Dani, 002) — `NoPrometerContactoGuardrail` la reescribía
   en silencio por el mensaje genérico de escalamiento
   ("Voy a registrar tu caso... no puedo garantizar contacto"),
   confundiendo al paciente sobre la razón real (sin disponibilidad,
   no un caso escalado).

Ambos reproducidos aquí tal cual, sin inventar mecanismo nuevo de
matching (ver `_es_palabra_unica`/`_es_afirmativo`/`_es_negativo` en
`domains/health/brain.py`, que comparan por IGUALDAD el mensaje ya
limpio de puntuación de borde — nunca agregan "si" como substring
suelto, para no generar falsos positivos con palabras como "asistir" o
"sinceramente").
"""
from domains.health import ManagementStatus, accept_activity, contact_patient, handle_patient_message


def _iniciar(context):
    accept_activity(context)
    contact_patient(context)


def test_respuesta_si_sin_tilde_avanza_la_conversacion(context):
    """Reproduce el bug #2 real: 'Si' (sin tilde) debe ofrecer
    disponibilidad, no repetir la pregunta de sí/no."""
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "Si")
    assert "¿te gustaría" not in r1.lower(), (
        "'Si' sin tilde no avanzó la conversación — quedó repitiendo la "
        "pregunta de sí/no (bug real de producción, recado 026)"
    )
    assert "opciones disponibles" in r1.lower()


def test_respuesta_si_minuscula_sin_tilde_tambien_avanza(context):
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "si")
    assert "opciones disponibles" in r1.lower()


def test_respuesta_si_con_signos_de_puntuacion_tambien_avanza(context):
    """'¡Si!'/'Si.' — puntuación de borde no debe impedir el match."""
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "¡Si!")
    assert "opciones disponibles" in r1.lower()


def test_respuesta_no_bare_declina_sin_quedar_atascada(context):
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "No")
    assert "gracias por tu tiempo" in r1.lower()


def test_sin_disponibilidad_no_usa_frase_de_promesa_de_contacto(context, activity_factory, services):
    """El mensaje de 'sin disponibilidad' nunca debe contener una frase
    de `_PROMESAS_PROHIBIDAS` (`guardrails/rules.py`) — si la contiene,
    el guardrail la reescribe en silencio por el mensaje genérico de
    escalamiento, y el paciente pierde la razón real (sin turnos, no un
    caso escalado)."""
    from domains.health import build_health_agent_context

    activity = services["source"].create(
        activity_factory(service="servicio-sin-turnos-de-prueba")
    )
    context = build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "sí")
    assert "te contactamos" not in r1.lower()
    assert "no puedo garantizar" not in r1.lower()
    assert context.activity.management_status != ManagementStatus.ESCALATED
