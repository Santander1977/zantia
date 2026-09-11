"""
Recado 070 — reproduce, de extremo a extremo, la transcripción real
reportada por el usuario:

    Sistema ofrece: "1. Medicina General 2. Odontologia 3. Pediatria
    4. Psicologia 5. Urgencias"
    Paciente responde: "3" (debía ser Pediatria) -> NO reconocido,
    repite el menú.
    Paciente responde: "2" (debía ser Odontologia) -> NO reconocido
    otra vez.

Causa raíz confirmada con `git log -p` sobre `domains/health/brain.py`:
`_interpretar_servicio` (recado 030) NUNCA aceptó un ordinal — desde su
creación solo hizo match por nombre real (exacto/substring), y el
commit `d7d4835` (recado 036, tolerancia a errores de tipeo) documenta
EXPLÍCITAMENTE que la selección de fecha/horario "no necesita el mismo
tratamiento [de fuzzy matching] (selección por ordinal, no por nombre
libre)" — confirmando que la ausencia de un camino equivalente por
ordinal en la selección de SERVICIO fue una decisión de diseño
original del recado 030/036, nunca una regresión introducida por un
recado posterior (068/069 no tocaron `_interpretar_servicio`).

Corrección: `_interpretar_servicio` ahora revisa el ordinal PRIMERO
(reutilizando `_indice_ordinal_seguro`, la MISMA función ya usada por
fecha/horario/reprogramación/menú — ampliada de 3 a 10 posiciones para
cubrir el catálogo real de 5 servicios) contra el catálogo EXACTO en el
mismo orden mostrado al paciente; si no hay ordinal, cae al match por
nombre/fuzzy de siempre (recado 036), sin cambios.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService


class _CatalogoRealDeCincoServicios(MockAppointmentService):
    """Mismo catálogo real de 5 servicios confirmado en el recado 036
    (`Medicina General, Odontologia, Pediatria, Psicologia, Urgencias`),
    en el MISMO orden en que se le mostró al paciente real — con una
    fecha/hora real distinta por servicio para poder confirmar, sin
    ambigüedad, cuál servicio quedó realmente elegido."""

    def _seed_fictional_data(self) -> None:
        # Deliberadamente SIN `super()._seed_fictional_data()`: la base
        # siembra sus propios slots ficticios de "medicina general"
        # (2026-09-05/06/07) que colisionarían (mismo `.lower()`) con el
        # catálogo real de este test y contaminarían qué fecha se ofrece
        # primero — este test necesita una fecha ÚNICA por servicio para
        # confirmar sin ambigüedad cuál quedó seleccionado.
        self._catalogo_servicios = [
            "Medicina General", "Odontologia", "Pediatria", "Psicologia", "Urgencias",
        ]
        for nombre, slot_id, fecha in (
            ("Medicina General", "MG-1", "2026-09-14"),
            ("Odontologia", "ODO-1", "2026-09-15"),
            ("Pediatria", "PED-1", "2026-09-16"),
            ("Psicologia", "PSI-1", "2026-09-17"),
            ("Urgencias", "URG-1", "2026-09-18"),
        ):
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service=nombre, professional="Dr. Ruiz",
                location="Sede Norte", date=fecha, time="09:00",
            )


def _gateway():
    return build_health_gateway(
        MockActivitySource(), _CatalogoRealDeCincoServicios(),
        ReminderManager(), MockActivityResultSink(),
    )


# ---------------------------------------------------------------------
# 1. Reproducción EXACTA de la transcripción real reportada.
# ---------------------------------------------------------------------
def test_reproduce_transcripcion_real_elegir_3_para_pediatria():
    gateway = _gateway()
    ref = "PAC-070-REAL-1"
    r1 = handle_inbound_message(gateway, ref, "telegram", "m1", "necesito una cita")
    assert "1. medicina general" in r1.lower() and "3. pediatria" in r1.lower()

    r2 = handle_inbound_message(gateway, ref, "telegram", "m2", "3")
    assert "no logré identificar" not in r2.lower(), f"quedó atrapado repitiendo el menú: {r2!r}"
    assert "1. medicina general" not in r2.lower(), f"no debía repetir el catálogo: {r2!r}"
    assert "16 de septiembre" in r2.lower(), f"debía ofrecer la fecha real de Pediatria: {r2!r}"


def test_reproduce_transcripcion_real_elegir_2_para_odontologia():
    gateway = _gateway()
    ref = "PAC-070-REAL-2"
    handle_inbound_message(gateway, ref, "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, ref, "telegram", "m2", "2")
    assert "no logré identificar" not in r2.lower(), f"quedó atrapado repitiendo el menú: {r2!r}"
    assert "15 de septiembre" in r2.lower(), f"debía ofrecer la fecha real de Odontologia: {r2!r}"


# ---------------------------------------------------------------------
# 2. Los 5 ordinales del catálogo real, cada uno al servicio correcto.
# ---------------------------------------------------------------------
def test_los_5_ordinales_numericos_seleccionan_el_servicio_correcto():
    esperado_por_ordinal = {
        "1": "14 de septiembre", "2": "15 de septiembre", "3": "16 de septiembre",
        "4": "17 de septiembre", "5": "18 de septiembre",
    }
    for ordinal, fecha_esperada in esperado_por_ordinal.items():
        gateway = _gateway()
        ref = f"PAC-070-ORD-{ordinal}"
        handle_inbound_message(gateway, ref, "telegram", "m1", "necesito una cita")
        r2 = handle_inbound_message(gateway, ref, "telegram", "m2", ordinal)
        assert fecha_esperada in r2.lower(), f"ordinal {ordinal!r} no seleccionó el servicio esperado: {r2!r}"


def test_ordinales_por_palabra_tambien_funcionan():
    esperado_por_palabra = {
        "la primera": "14 de septiembre", "segunda": "15 de septiembre",
        "la tercera por favor": "16 de septiembre", "cuarta": "17 de septiembre",
        "quinta": "18 de septiembre",
    }
    for texto, fecha_esperada in esperado_por_palabra.items():
        gateway = _gateway()
        ref = f"PAC-070-PAL-{hash(texto)}"
        handle_inbound_message(gateway, ref, "telegram", "m1", "necesito una cita")
        r2 = handle_inbound_message(gateway, ref, "telegram", "m2", texto)
        assert fecha_esperada in r2.lower(), f"{texto!r} no seleccionó el servicio esperado: {r2!r}"


# ---------------------------------------------------------------------
# 3. Control: el fuzzy matching por nombre (recado 036) sigue intacto.
# ---------------------------------------------------------------------
def test_fuzzy_matching_por_nombre_sigue_funcionando_sin_regresion():
    gateway = _gateway()
    ref = "PAC-070-FUZZY"
    handle_inbound_message(gateway, ref, "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, ref, "telegram", "m2", "pedeatria")
    assert "16 de septiembre" in r2.lower(), f"el fuzzy matching por nombre dejó de funcionar: {r2!r}"


def test_ordinal_fuera_de_rango_cae_al_fallback_normal_nunca_crashea():
    """El catálogo real tiene 5 — un "9"/"10" no debe romper nada ni
    elegir un servicio inexistente, cae al mismo fallback de siempre."""
    gateway = _gateway()
    ref = "PAC-070-FUERA-DE-RANGO"
    handle_inbound_message(gateway, ref, "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, ref, "telegram", "m2", "9")
    assert "no logré identificar" in r2.lower()
