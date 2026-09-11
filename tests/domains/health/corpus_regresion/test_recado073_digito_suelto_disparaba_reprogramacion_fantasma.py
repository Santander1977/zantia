"""
Recado 073 — reproduce, de extremo a extremo, la transcripción real
(Telegram, 2026-09-11) que reveló el hallazgo:

    07:08 Enzo:   "Y pasaron los 2 minutos"
    07:08 ZANTIA: "Aquí tienes otras opciones: 1. Viernes 11 de septiembre,
                   07:30, Consultorio 5 2. Viernes 11 de septiembre, 08:00,
                   Consultorio 5 3. Viernes 11 de septiembre, 08:30,
                   Consultorio 5 ¿Cuál prefieres?"

El paciente comentaba sobre el enfriamiento de 2 minutos (recado 067),
sin pedir nada — pero el "2" suelto dentro de esa frase se interpretó
como si hubiera elegido la opción "2. Reprogramar una cita" del menú
principal, y — al tener una cita real reservada — disparó de verdad el
wizard de reprogramación con verificación por código (`gateway.py:
_iniciar_verificacion_para_gestion`), ofreciendo horarios reales que
nadie pidió.

Causa raíz confirmada leyendo y ejecutando el código real:
`gateway.py::_interpretar_opcion_menu` (la función que se revisa
PRIMERO de todo un mensaje nuevo, antes incluso de la despedida) usaba
`re.search(rf"\\b{ordinal}\\b", texto)` sin ningún límite de longitud —
un dígito del 1 al 5 en CUALQUIER parte de un mensaje, sin importar cuán
largo o ajeno al menú fuera el resto, contaba como si el paciente
hubiera elegido esa opción. Mismo patrón EXACTO ya corregido en el
recado 067 para `_elegir_opcion`/`_elegir_opcion_ordinal` (selección de
una lista YA ofrecida) — ese fix (`_indice_ordinal_seguro`, límite de 8
palabras) nunca se extendió a esta función, que audita el PRIMER
mensaje de una conversación nueva.

Corrección: `_interpretar_opcion_menu` ahora usa `_indice_menu_ordinal_seguro`
— reutiliza `_indice_ordinal_seguro` (MISMA función del recado 067) MÁS
una segunda capa de seguridad (`_PALABRAS_FILLER_SELECCION_MENU`):
confirmado empíricamente que el límite de 8 palabras por sí solo NO
bastaba acá ("Y pasaron los 2 minutos" son solo 5 palabras) — a
diferencia de "¿cuál de estas 3 prefieres?" (una pregunta ya hecha,
cualquier respuesta corta se presume sobre eso), el PRIMER mensaje de
una conversación nueva no tiene esa garantía. Ahora TODA palabra del
mensaje, además del propio ordinal, debe ser relleno reconocido
("opción", "la", "por favor", etc.) para que un ordinal SUELTO cuente.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.gateway import _interpretar_opcion_menu


class _CatalogoConCitaExistente(MockAppointmentService):
    """Catálogo con disponibilidad real para reprogramar — necesario
    para que, SI `_interpretar_opcion_menu` fallara, se pudiera
    reproducir el mismo síntoma completo (oferta real de horarios)."""

    def _seed_fictional_data(self) -> None:
        self._catalogo_servicios = ["Medicina General"]
        for slot_id, hora in (("MG-1", "07:30"), ("MG-2", "08:00"), ("MG-3", "08:30")):
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service="Medicina General", professional="Dr. Real",
                location="Consultorio 5", date="2026-09-11", time=hora,
            )


# ---------------------------------------------------------------------
# 1. Reproducción directa de la función exacta que falló — un dígito
#    suelto en una oración larga y ajena NUNCA debe contar como opción
#    de menú.
# ---------------------------------------------------------------------
def test_frase_real_sobre_el_enfriamiento_no_dispara_ninguna_opcion_de_menu():
    assert _interpretar_opcion_menu("Y pasaron los 2 minutos") is None


def test_otras_frases_reales_con_digitos_sueltos_ajenos_al_menu_no_disparan_nada():
    for texto in (
        "tengo una duda, nos vemos el 3 de este mes",
        "mi hijo cumple 4 años la otra semana",
        "llego en 1 hora aprox",
    ):
        assert _interpretar_opcion_menu(texto) is None, f"{texto!r} no debía disparar ninguna opción de menú"


# ---------------------------------------------------------------------
# 2. Control: las formas cortas y legítimas de responder al menú deben
#    seguir funcionando exactamente igual que antes.
# ---------------------------------------------------------------------
def test_formas_cortas_legitimas_de_elegir_del_menu_siguen_funcionando():
    from domains.health.models import RequestIntent

    casos = {
        "2": RequestIntent.REPROGRAMAR_CITA,
        "opcion 2": RequestIntent.REPROGRAMAR_CITA,
        "la 2": RequestIntent.REPROGRAMAR_CITA,
        "quiero la 2 por favor": RequestIntent.REPROGRAMAR_CITA,
        "la segunda": RequestIntent.REPROGRAMAR_CITA,
        "quiero la segunda opcion": RequestIntent.REPROGRAMAR_CITA,
        "5": RequestIntent.SALIR,
        "salir": RequestIntent.SALIR,
        "quiero cancelar mi cita": RequestIntent.CANCELAR_CITA,
    }
    for texto, esperado in casos.items():
        assert _interpretar_opcion_menu(texto) == esperado, f"{texto!r} dejó de reconocerse correctamente"


# ---------------------------------------------------------------------
# 3. Reproducción de EXTREMO A EXTREMO (handle_inbound_message) de la
#    transcripción real — nunca debe ofrecer una reprogramación cuando
#    el paciente solo comentó sobre el tiempo, ni en ningún punto de la
#    conversación (despedida -> cooldown -> comentario ajeno).
# ---------------------------------------------------------------------
def test_reproduce_transcripcion_real_completa_sin_disparar_reprogramacion_fantasma():
    gateway = build_health_gateway(
        MockActivitySource(), _CatalogoConCitaExistente(), ReminderManager(), MockActivityResultSink()
    )
    ref = "PAC-073-TRANSCRIPCION-REAL"

    r1 = handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    assert "1. reservar una cita" in r1.lower()

    r2 = handle_inbound_message(gateway, ref, "demo", "m2", "5")
    assert "fue un gusto atenderte" in r2.lower()

    r3 = handle_inbound_message(gateway, ref, "demo", "m3", "Y pasaron los 2 minutos")
    assert "aqui tienes otras opciones" not in r3.lower().replace("í", "i"), (
        f"NUNCA debía ofrecer una reprogramación a partir de un comentario sobre el tiempo: {r3!r}"
    )
    assert "07:30" not in r3 and "08:00" not in r3 and "08:30" not in r3, (
        f"no debía revelar horarios reales de reprogramación: {r3!r}"
    )
