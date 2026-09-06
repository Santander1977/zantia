"""ActivityResult y callback al sistema originador (secciones 25-26,
28)."""
from domains.health import (
    ActivityResultType,
    ActivityStatus,
    accept_activity,
    contact_patient,
    finalize_and_report,
    handle_patient_message,
)


def test_activity_result_reported_after_booking(context, services):
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí, me interesa")
    handle_patient_message(context, "m1b", "1")  # elige fecha (recado 035)
    handle_patient_message(context, "m2", "la primera")

    finalize_and_report(context)

    resultados = services["result_sink"].results_for(context.activity.activity_id)
    assert len(resultados) == 1
    assert resultados[0].result == ActivityResultType.APPOINTMENT_CONFIRMED
    assert resultados[0].appointment_id == context.activity.appointment_id
    assert context.activity.status == ActivityStatus.COMPLETED


def test_callback_idempotent_when_reported_twice(context, services):
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "no me interesa")

    finalize_and_report(context)
    finalize_and_report(context)  # reintento

    assert len(services["result_sink"].results_for(context.activity.activity_id)) == 1


def test_result_sink_send_result_directly_is_idempotent(services):
    from domains.health.models import ActivityResult

    resultado = ActivityResult(activity_id="ACT-X", result=ActivityResultType.DECLINED)
    assert services["result_sink"].send_result(resultado)
    assert services["result_sink"].send_result(resultado)
    assert len(services["result_sink"].results_for("ACT-X")) == 1
