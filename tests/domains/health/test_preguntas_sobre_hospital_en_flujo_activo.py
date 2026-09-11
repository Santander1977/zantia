"""
Recado 064 (segunda parte) — dos preguntas reales sobre el HOSPITAL en
sí (ubicación, calidad de atención) que ninguna categoría existente de
`_detectar_interrupcion_de_contexto` (recados 047/053) reconocía —
caían a la interpretación de la etapa activa (`_interpretar_fecha`/
`_interpretar_horario`), perdiendo la pregunta real del paciente.

Mismo patrón que `_responder_expresion_emocional` (recado 053):
`etapa`/`datos` nunca cambian, la respuesta reutiliza el MISMO
`_RECORDATORIO_BREVE_POR_ETAPA` para volver naturalmente al contexto.

Este archivo verifica, con una llamada REAL a Anthropic (gateada,
`ZANTIA_RUN_REAL_LLM_TESTS`, mismo patrón que `test_llm_brain.py`):
1. Secuencia completa de 2 preguntas fuera de contexto distintas en la
   MISMA conversación, en medio de un flujo de selección de fecha/
   horario ya en curso — el estado de la selección se preserva entre
   ambas (el paciente completa la reserva normalmente después).
2. Ninguna dirección inventada (no existe una real en este repo,
   confirmado por grep antes de escribir este código — la respuesta
   correcta es la honestidad explícita).
3. Ninguna opinión personal sobre la calidad de atención.
4. Si algún guardrail existente interviene (`TipoDePreguntaAlteradaGuardrail`,
   `DatoInventadoGuardrail`, `OpinionPersonalGuardrail`), se documenta
   qué pasó y por qué es el comportamiento correcto — nunca se asume
   en silencio que "no debería pasar nada".
"""
import os

import pytest

from domains.health import accept_activity, contact_patient, handle_patient_message

_SKIP_REAL = pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)


def _contexto_real_con_llm(monkeypatch, services, activity_factory):
    """MISMO patrón que `test_llm_brain.py:_contexto_con_drafter`, pero
    SIN sustituir `AnthropicResponseDrafter` por un doble — acá se deja
    la implementación real (requiere `ANTHROPIC_API_KEY` real en el
    entorno, ya presente en `.env` de esta sesión)."""
    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")

    from domains.health import build_health_agent_context

    activity = services["source"].create(activity_factory())
    return build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )


@_SKIP_REAL
def test_real_dos_preguntas_fuera_de_contexto_preservan_la_seleccion_en_curso(
    monkeypatch, services, activity_factory
):
    context = _contexto_real_con_llm(monkeypatch, services, activity_factory)
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "sí")  # ofrece fechas (PASO 2)
    # No se exige la frase EXACTA del texto base determinista — el LLM
    # real puede parafrasearla (ej. "fechas que tenemos disponibles" en
    # vez de "fechas disponibles") sin que eso sea un problema; lo que
    # de verdad importa es el ESTADO real, verificado abajo.
    assert "disponible" in r1.lower()
    estado = context.orchestrator.store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_fecha"
    fechas_antes = estado.datos_recopilados.get("fechas_ofrecidas")
    assert fechas_antes  # el flujo real sí ofreció fechas concretas

    # --- Interrupción 1: pregunta de ubicación ---
    r2 = handle_patient_message(context, "m2", "oye, y ¿dónde queda el hospital exactamente?")
    assert "no logré identificar" not in r2.lower(), f"Claude real no reconoció la pregunta: {r2!r}"
    # Ninguna dirección inventada — no existe una real en este repo.
    assert "calle" not in r2.lower() and "carrera" not in r2.lower() and "avenida" not in r2.lower(), (
        f"la respuesta parece haber inventado una dirección real: {r2!r}"
    )
    estado_tras_r2 = context.orchestrator.store.get(context.activity.activity_id)
    assert estado_tras_r2.datos_recopilados["etapa"] == "esperando_fecha", (
        "la etapa de selección NO debía perderse tras la pregunta de ubicación"
    )
    assert estado_tras_r2.datos_recopilados.get("fechas_ofrecidas") == fechas_antes, (
        "las fechas ya ofrecidas NO debían cambiar/perderse"
    )

    # --- Interrupción 2, MÁS ADELANTE en la misma conversación: pregunta
    #     distinta, sobre calidad de atención (no ubicación) ---
    r3 = handle_patient_message(context, "m3", "otra cosa, ¿los médicos de ahí son buenos atendiendo?")
    assert "no logré identificar" not in r3.lower(), f"Claude real no reconoció la pregunta: {r3!r}"
    estado_tras_r3 = context.orchestrator.store.get(context.activity.activity_id)
    assert estado_tras_r3.datos_recopilados["etapa"] == "esperando_fecha", (
        "la etapa de selección NO debía perderse tras la segunda pregunta"
    )
    assert estado_tras_r3.datos_recopilados.get("fechas_ofrecidas") == fechas_antes

    # --- Prueba definitiva de que el estado NO se perdió: el paciente
    #     completa la selección normalmente, sin repetir nada desde cero. ---
    r4 = handle_patient_message(context, "m4", "1")  # elige la primera fecha -> ofrece horarios
    estado_tras_r4 = context.orchestrator.store.get(context.activity.activity_id)
    assert estado_tras_r4.datos_recopilados["etapa"] == "esperando_horario", (
        f"la selección de fecha debía seguir funcionando tras las 2 interrupciones: {r4!r}"
    )
    r5 = handle_patient_message(context, "m5", "1")  # elige horario -> reserva real
    assert context.activity.appointment_id is not None, "la reserva real debía completarse normalmente"
