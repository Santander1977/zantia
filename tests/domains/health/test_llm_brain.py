"""
Recado 038 — primera conexión real de un LLM (Anthropic) al dominio
salud, con el principio de diseño del recado 037 respetado sin
excepción: ningún LLM decide si ejecutar una tool WRITE. Verificado
aquí con dobles de prueba (nunca gastan llamadas reales) salvo el
último test, gateado explícitamente por `ZANTIA_RUN_REAL_LLM_TESTS`.
"""
import os

import pytest

from domains.health import accept_activity, contact_patient, handle_patient_message
from domains.health.brain import HealthBrain
from domains.health.llm_brain import HealthAnthropicBrain, _construir_verificaciones_de_datos


class _DrafterQueParafrasea:
    """Simula un LLM bien portado: reformula sin cambiar ningún dato."""

    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return f"¡Con gusto! {texto_base}"


class _DrafterQueAlucina:
    """Simula un LLM que agrega un dato NO presente en el texto base —
    exactamente el caso que `DatoInventadoGuardrail` debe bloquear."""

    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return texto_base + " También tengo un cupo especial a las 23:59, ¿te sirve?"


class _DrafterQueFalla:
    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        raise RuntimeError("fallo simulado de red/API")


class _DrafterQueCambiaTipoDePregunta:
    """Reproduce el patrón EXACTO del "Caso 2" real encontrado en el
    recado 038 (primera llamada real a Claude): convierte una pregunta
    de selección ("¿Cuál prefieres?", con horarios ya enumerados) en
    una pregunta de sí/no ("¿Confirmamos esa cita?"). Reutiliza la(s)
    hora(s)/fecha(s) REALES del propio texto_base (nunca inventa un
    valor nuevo) — así aísla el hallazgo específico de este recado
    (cambio de TIPO de pregunta) sin disparar también
    `DatoInventadoGuardrail` (que es un hallazgo distinto, ya cubierto
    en `test_guardrail_bloquea_una_alucinacion_del_llm_de_extremo_a_extremo`)."""

    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        from domains.health.llm_brain import _RE_FECHA, _RE_HORA

        horas = _RE_HORA.findall(texto_base)
        fechas = _RE_FECHA.findall(texto_base)
        hora = horas[-1] if horas else "esa hora"
        fecha = fechas[0] if fechas else "esa fecha"
        return f"¡Perfecto! Entonces quedarías agendado el {fecha} a las {hora}. ¿Confirmamos esa cita?"


# ---------------------------------------------------------------------
# 1. HealthAnthropicBrain redacta usando datos reales del contexto —
#    tool_requerida/confirmacion_estructurada_para_write/propuesta de
#    estado se copian SIN TOCAR desde el Brain determinista.
# ---------------------------------------------------------------------
def test_redacta_el_texto_pero_preserva_la_decision_determinista(services, activity_factory):
    activity = services["source"].create(activity_factory())
    brain_determinista = HealthBrain(lambda: activity, services["appointment_service"])
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueParafrasea())

    datos = {"opciones_horario": ["SLOT-1", "SLOT-2"]}
    from state.models import ConversationState

    estado = ConversationState(canal="demo", datos_recopilados={**datos, "etapa": "esperando_horario"})

    salida_determinista = brain_determinista._interpretar_horario("1", datos)
    salida_llm = brain_llm.interpret("1", estado, [])

    assert salida_llm.respuesta_propuesta != salida_determinista.respuesta_propuesta
    assert salida_llm.respuesta_propuesta.startswith("¡Con gusto!")
    assert salida_determinista.respuesta_propuesta in salida_llm.respuesta_propuesta
    # Lo que de verdad importa (recado 037): la decisión NUNCA cambia.
    assert salida_llm.tool_requerida == salida_determinista.tool_requerida
    assert (
        salida_llm.confirmacion_estructurada_para_write
        == salida_determinista.confirmacion_estructurada_para_write
        == True  # noqa: E712 — explícito a propósito
    )
    assert salida_llm.propuesta_de_actualizacion_de_estado == salida_determinista.propuesta_de_actualizacion_de_estado


def test_si_el_drafter_falla_usa_el_texto_determinista_sin_romper(services, activity_factory):
    activity = services["source"].create(activity_factory())
    brain_determinista = HealthBrain(lambda: activity, services["appointment_service"])
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueFalla())

    from state.models import ConversationState

    estado = ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_decision"})
    salida = brain_llm.interpret("sí", estado, [])
    assert "fechas disponibles" in salida.respuesta_propuesta.lower()


# ---------------------------------------------------------------------
# 2. `_construir_verificaciones_de_datos` — unidad aislada.
# ---------------------------------------------------------------------
def test_construir_verificaciones_extrae_fecha_y_hora_reales():
    texto = "Para el Lunes 7 de septiembre, estos son los horarios disponibles: 1) 09:00 en Sede Norte."
    verificaciones = _construir_verificaciones_de_datos(texto)
    por_categoria = {v.nombre_categoria: v.valores_permitidos for v in verificaciones}
    assert por_categoria["fecha"] == ["Lunes 7 de septiembre"]
    assert por_categoria["hora"] == ["09:00"]


def test_construir_verificaciones_categoria_vacia_si_no_aparece_en_el_base():
    """Caso crítico: si el texto base NUNCA mencionó una hora, la
    categoría 'hora' debe existir igual con lista vacía — así CUALQUIER
    hora que el LLM agregue después se bloquea, no solo una distinta a
    las ya mencionadas."""
    texto = "Estas son las fechas disponibles: 1) Sábado 5 de septiembre. ¿Cuál te queda mejor?"
    verificaciones = _construir_verificaciones_de_datos(texto)
    por_categoria = {v.nombre_categoria: v.valores_permitidos for v in verificaciones}
    assert por_categoria["hora"] == []


# ---------------------------------------------------------------------
# 3. Extremo a extremo REAL, contra el Orchestrator/GuardrailEngine
#    completo: el guardrail intercepta y bloquea una alucinación.
# ---------------------------------------------------------------------
def _contexto_con_drafter(monkeypatch, services, activity_factory, drafter):
    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba-nunca-usada-en-red-real")
    monkeypatch.setattr("domains.health.llm_brain.AnthropicResponseDrafter", lambda **kwargs: drafter)

    from domains.health import build_health_agent_context

    activity = services["source"].create(activity_factory())
    return build_health_agent_context(
        activity, services["source"], services["appointment_service"],
        services["reminder_manager"], services["result_sink"],
    )


def test_guardrail_bloquea_una_alucinacion_del_llm_de_extremo_a_extremo(monkeypatch, services, activity_factory):
    context = _contexto_con_drafter(monkeypatch, services, activity_factory, _DrafterQueAlucina())
    accept_activity(context)
    respuesta = contact_patient(context)
    assert respuesta  # mensaje de contacto (determinista, sin pasar por el Brain todavía)

    r1 = handle_patient_message(context, "m1", "sí")
    # `_DrafterQueAlucina` agrega una hora ("23:59") que NO estaba en el
    # texto base de PASO 2 (que no menciona ninguna hora) — el
    # guardrail debe bloquear la respuesta ALUCINADA (nunca llega al
    # paciente la frase inventada "cupo especial"), aunque el mensaje
    # de bloqueo SÍ cite el valor detectado con fines de auditoría —
    # eso es esperado, no una filtración del texto original.
    assert "cupo especial" not in r1.lower()
    assert "no puedo continuar con esa acción todavía" in r1.lower()
    assert "dato_inventado" in r1.lower()


def test_guardrail_de_tipo_de_pregunta_restaura_el_texto_base_reproduciendo_caso_2(
    monkeypatch, services, activity_factory
):
    """Recado 039 — reproduce de extremo a extremo el hallazgo real del
    recado 038 (Caso 2): el LLM convierte "¿Cuál prefieres?" (PASO 3,
    horarios ya enumerados) en "¿Confirmamos esa cita?". El paciente
    debe seguir viendo la pregunta de selección ORIGINAL — nunca la
    de sí/no — para que su siguiente respuesta (un ordinal) siga
    siendo interpretable por `HealthBrain`."""
    context = _contexto_con_drafter(monkeypatch, services, activity_factory, _DrafterQueCambiaTipoDePregunta())
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí")  # ofrece fechas (PASO 2)
    r1 = handle_patient_message(context, "m2", "1")  # elige fecha -> ofrece horarios (PASO 3)

    assert "confirmamos esa cita" not in r1.lower()
    assert "¿cuál" in r1.lower()

    # Y la conversación sigue siendo interpretable con un ordinal —
    # nunca se rompió el contrato del turno siguiente.
    r2 = handle_patient_message(context, "m3", "1")
    assert "no logré identificar" not in r2.lower()


def test_flujo_normal_con_llm_bien_portado_llega_hasta_la_reserva_real(monkeypatch, services, activity_factory):
    """Control positivo: con un drafter que NO alucina, la reserva real
    se completa igual que con HealthBrain puro — el LLM solo cambió el
    tono, nunca la decisión."""
    context = _contexto_con_drafter(monkeypatch, services, activity_factory, _DrafterQueParafrasea())
    accept_activity(context)
    contact_patient(context)
    handle_patient_message(context, "m1", "sí")
    handle_patient_message(context, "m2", "1")  # fecha
    handle_patient_message(context, "m3", "1")  # horario -> reserva real

    assert context.activity.appointment_id is not None


# ---------------------------------------------------------------------
# 4. Sin ANTHROPIC_API_KEY, el sistema cae al Brain determinista.
# ---------------------------------------------------------------------
def test_sin_api_key_cae_al_brain_determinista_sin_fallar(monkeypatch, caplog, services, activity_factory):
    import logging

    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from domains.health.config import build_health_brain

    with caplog.at_level(logging.WARNING, logger="zantia.health"):
        brain = build_health_brain(lambda: None, services["appointment_service"])

    assert isinstance(brain, HealthBrain)
    mensajes = [r.message for r in caplog.records if r.name == "zantia.health"]
    assert any("ANTHROPIC_API_KEY" in m for m in mensajes)


def test_sin_health_brain_type_configurado_usa_determinista_por_default(services):
    from domains.health.config import build_health_brain

    brain = build_health_brain(lambda: None, services["appointment_service"])
    assert isinstance(brain, HealthBrain)


# ---------------------------------------------------------------------
# 5. Prueba de integración REAL — DESHABILITADA por defecto (mismo
#    patrón que ZANTIA_RUN_REAL_HRMM_TESTS, recado 009/025). Nunca se
#    activa sola: requiere la variable Y el paquete `anthropic`
#    instalado (no lo está en este entorno, ver recado 038) Y una
#    ANTHROPIC_API_KEY real.
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)
def test_anthropic_response_drafter_contra_la_api_real():
    from domains.health.llm_brain import AnthropicResponseDrafter

    drafter = AnthropicResponseDrafter()
    texto = drafter.draft(
        "hola, quiero ver disponibilidad",
        "Estas son las fechas disponibles: 1) Lunes 7 de septiembre. ¿Cuál te queda mejor?",
    )
    assert isinstance(texto, str) and texto.strip()
