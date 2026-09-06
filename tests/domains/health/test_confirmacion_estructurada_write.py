"""
Recado 037, Parte 3 — verificación de que ninguna tool WRITE del
dominio salud se ejecuta sin que `HealthBrain` declare explícitamente
`confirmacion_estructurada_para_write=True` (ver
`guardrails/rules.py:ConfirmacionEstructuradaRequeridaParaWriteGuardrail`,
ya activo por default en `reglas_core_por_defecto` — recado 037).

Los 3 puntos donde `HealthBrain` propone una tool WRITE (`book_appointment`,
`reschedule_appointment` vía Mock, `cancel_appointment` vía Mock) declaran
el flag en el mismo `return` donde ya ocurrió la confirmación
determinista (ordinal elegido, o frase imperativa exacta) — este archivo
lo confirma directamente sobre el `BrainOutput`, y con un flujo real de
extremo a extremo que confirma que la tool efectivamente se ejecuta
(si el flag faltara, `ConfirmacionEstructuradaRequeridaParaWriteGuardrail`
bloquearía la reserva real y estos tests fallarían).
"""
from domains.health import accept_activity, contact_patient, handle_patient_message


def test_reserva_real_se_ejecuta_con_confirmacion_estructurada(context):
    """Flujo completo real (servicio único -> fecha -> horario) — si
    `_interpretar_horario` no declarara `confirmacion_estructurada_para_write=True`,
    el guardrail bloquearía `book_appointment` y `appointment_id` nunca
    quedaría asignado."""
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí")
    handle_patient_message(context, "m2", "1")  # fecha
    handle_patient_message(context, "m3", "1")  # horario -> ejecuta book_appointment

    assert context.activity.appointment_id is not None


def test_brain_output_de_interpretar_horario_declara_confirmacion_estructurada(services, activity_factory):
    from domains.health.brain import HealthBrain

    activity = services["source"].create(activity_factory())
    brain = HealthBrain(lambda: activity, services["appointment_service"])
    datos = {"opciones_horario": ["SLOT-1", "SLOT-2"]}
    salida = brain._interpretar_horario("1", datos)
    assert salida.tool_requerida["name"] == "book_appointment"
    assert salida.confirmacion_estructurada_para_write is True


def test_brain_output_de_cancelar_declara_confirmacion_estructurada(services, activity_factory):
    from domains.health.brain import HealthBrain

    activity = services["source"].create(activity_factory(appointment_id="CITA-1"))
    brain = HealthBrain(lambda: activity, services["appointment_service"])
    salida = brain._cancelar({})
    assert salida.tool_requerida["name"] == "cancel_appointment"
    assert salida.confirmacion_estructurada_para_write is True


def test_brain_output_de_reprogramacion_declara_confirmacion_estructurada(services, activity_factory):
    from domains.health.brain import HealthBrain

    activity = services["source"].create(activity_factory(appointment_id="CITA-1"))
    brain = HealthBrain(lambda: activity, services["appointment_service"])
    datos = {"opciones_reprogramacion": ["SLOT-1", "SLOT-2"]}
    salida = brain._interpretar_seleccion_reprogramacion("1", datos)
    assert salida.tool_requerida["name"] == "reschedule_appointment"
    assert salida.confirmacion_estructurada_para_write is True
