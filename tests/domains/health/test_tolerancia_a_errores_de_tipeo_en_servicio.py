"""
Sexto hallazgo real de la misma conversación de Telegram (recado 036,
continúa 026/027/030/031/034/035): con catálogo real de más de un
servicio, `HealthBrain._interpretar_servicio` (recado 030/031) exigía
un match EXACTO o por substring contra el nombre real del catálogo
(normalizado sin tildes, recado 030) — un paciente real que escribe con
errores de tipeo ("pedeatria", "pediatra", "medisina general",
"sicologia", "urgencia" en singular contra "Urgencias" real) no
calzaba con nada, y caía siempre al mensaje de "no logré identificar
cuál de estos prefieres", aunque la intención fuera clara para un
humano.

Corrección (`_emparejar_servicio_por_similitud`, `brain.py`): si el
match exacto/substring no encuentra nada, se compara el texto del
paciente contra cada nombre del CATÁLOGO VIGENTE (siempre recibido
como parámetro, nunca escrito en el código — ver
`test_matching_siempre_recibe_el_catalogo_como_parametro_nunca_fijo`
más abajo) con `difflib.SequenceMatcher` (librería estándar — decisión
explícita: no se agregó `rapidfuzz` como dependencia nueva) sobre
ventanas contiguas de palabras del mismo largo que el nombre del
servicio (tolera palabras de más alrededor, ej. "necesito una cita de
pediatria por favor"). Umbral elegido: 0.82 (ver docstring de
`_UMBRAL_FUZZY_SERVICIO` en `brain.py` para la tabla completa de
puntajes reales que llevó a este número). Si DOS O MÁS nombres del
catálogo vigente puntúan por encima del umbral (ambigüedad genuina),
nunca se elige por el paciente — se le muestran solo esos candidatos
cercanos, no el catálogo completo de nuevo desde cero. Si NINGÚN
servicio puntúa por encima del umbral, se usa el mismo fallback de
siempre (con las variantes rotativas del recado 034) — nunca se
inventa un servicio que no exista en el catálogo real.

Corrección de una imprecisión propia detectada por el usuario al
revisar el recado 036: el catálogo real confirmado hoy contra
hrmm-backend tiene 5 servicios (Medicina General, Odontologia,
Pediatria, Psicologia, Urgencias) — "Psiquiatria" NO es uno de ellos.
El ejemplo de ambigüedad genuina de más abajo usa un catálogo FICTICIO
de prueba (mismo patrón que otros archivos de este proyecto, ej.
`_AppointmentServiceDosServicios` en `test_tildes_y_servicio_inicial.py`)
para ejercitar el camino de código en aislamiento — nunca fue, ni se
presenta aquí como, un hallazgo sobre el catálogo real. Contra el
catálogo real de 5 confirmado hoy, un barrido de typos plausibles no
produjo ninguna ambigüedad genuina (ver
`test_catalogo_real_de_5_servicios_no_produce_ambiguedad_falsa`).
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.brain import _emparejar_servicio_por_similitud


class _CatalogoRealDeCincoServicios(MockAppointmentService):
    """El catálogo REAL confirmado hoy contra hrmm-backend (recado 031 +
    confirmación explícita del usuario en el recado 036): Medicina
    General, Odontologia, Pediatria, Psicologia, Urgencias — sin
    "psiquiatria" ni ningún sexto servicio inventado."""

    def _seed_fictional_data(self) -> None:
        super()._seed_fictional_data()
        self._catalogo_servicios = [
            "Medicina General", "Odontologia", "Pediatria", "Psicologia", "Urgencias",
        ]
        for nombre, slot_id in (
            ("Medicina General", "MG-1"), ("Odontologia", "ODO-1"), ("Pediatria", "PED-1"),
            ("Psicologia", "PSI-1"), ("Urgencias", "URG-1"),
        ):
            self._slots[slot_id] = AvailabilitySlot(
                slot_id=slot_id, service=nombre, professional="Dr. Ruiz",
                location="Sede Norte", date="2026-09-10", time="09:00",
            )


def _gateway_catalogo_real():
    return build_health_gateway(
        MockActivitySource(), _CatalogoRealDeCincoServicios(),
        ReminderManager(), MockActivityResultSink(),
    )


class _CatalogoHipoteticoConAmbiguedad(MockAppointmentService):
    """IMPORTANTE: catálogo FICTICIO de prueba, con dos nombres de
    servicio inventados y parecidos entre sí a propósito — NO refleja
    el catálogo real confirmado hoy contra hrmm-backend ("psiquiatria"
    NO es uno de los 5 servicios reales, ver docstring del módulo). Se
    usa únicamente para ejercitar en aislamiento el camino de código de
    "ambigüedad genuina" de `_emparejar_servicio_por_similitud" — mismo
    patrón ya establecido en este archivo de tests (ej.
    `_AppointmentServiceDosServicios` en `test_tildes_y_servicio_inicial.py`
    también inventa un catálogo de prueba, nunca el real)."""

    def _seed_fictional_data(self) -> None:
        super()._seed_fictional_data()
        self._catalogo_servicios = ["pediatria", "psiquiatria"]
        self._slots["PED-1"] = AvailabilitySlot(
            slot_id="PED-1", service="pediatria", professional="Dr. Ruiz",
            location="Sede Norte", date="2026-09-10", time="09:00",
        )
        self._slots["PSQ-1"] = AvailabilitySlot(
            slot_id="PSQ-1", service="psiquiatria", professional="Dra. Nieto",
            location="Sede Norte", date="2026-09-10", time="10:00",
        )


def _gateway_ambiguo():
    return build_health_gateway(
        MockActivitySource(), _CatalogoHipoteticoConAmbiguedad(),
        ReminderManager(), MockActivityResultSink(),
    )


def _preguntar_servicio_y_responder(gateway, pref, respuesta_paciente):
    handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    return handle_inbound_message(gateway, pref, "telegram", "m2", respuesta_paciente)


# ---------------------------------------------------------------------
# 0. El matching SIEMPRE recibe el catálogo vigente como parámetro —
#    nunca hay un nombre de servicio escrito dentro de `brain.py`.
#    Prueba directa de la función, sin pasar por todo el flujo de
#    conversación, para que quede inequívoco.
# ---------------------------------------------------------------------
def test_matching_siempre_recibe_el_catalogo_como_parametro_nunca_fijo():
    """Con el MISMO texto de entrada, cambiar el catálogo recibido
    cambia el resultado — prueba directa de que no hay ningún nombre
    de servicio hardcodeado en la función de matching."""
    elegido_a, _ = _emparejar_servicio_por_similitud("pediatria", ["Pediatria", "Odontologia"])
    assert elegido_a == "Pediatria"

    elegido_b, ambiguos_b = _emparejar_servicio_por_similitud("pediatria", ["Otra cosa", "Algo mas"])
    assert elegido_b is None and ambiguos_b == []


def test_catalogo_real_de_5_servicios_no_produce_ambiguedad_falsa():
    """Barrido de typos plausibles contra el catálogo REAL de 5
    confirmado hoy — ninguno debe producir ambigüedad genuina entre dos
    servicios reales distintos (los 5 nombres reales son lo bastante
    distintos entre sí). Documentado explícitamente en el recado 036:
    esto es evidencia de que HOY no hay este caso, no una garantía
    permanente si el catálogo real cambia en el futuro."""
    servicios_reales = ["Medicina General", "Odontologia", "Pediatria", "Psicologia", "Urgencias"]
    typos_plausibles = [
        "pediatria", "pedeatria", "pediatra", "odontologia", "odontologa", "odontologo",
        "psicologia", "sicologia", "psicologo", "urgencia", "urgencias", "medicina general",
        "medisina general",
    ]
    for texto in typos_plausibles:
        _, ambiguos = _emparejar_servicio_por_similitud(texto, servicios_reales)
        assert ambiguos == [], f"{texto!r} produjo ambigüedad falsa contra el catálogo real: {ambiguos}"


# ---------------------------------------------------------------------
# 1. Typos reales pedidos explícitamente, contra el catálogo REAL de 5
#    — cada uno debe matchear al servicio real correspondiente y
#    avanzar a fechas.
# ---------------------------------------------------------------------
def test_pedeatria_matchea_pediatria():
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-1", "pedeatria")
    assert "fechas disponibles" in r2.lower()


def test_pediatra_matchea_pediatria():
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-2", "pediatra")
    assert "fechas disponibles" in r2.lower()


def test_urgencia_singular_matchea_urgencias():
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-3", "urgencia")
    assert "fechas disponibles" in r2.lower()


def test_medisina_general_matchea_medicina_general():
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-4", "medisina general")
    assert "fechas disponibles" in r2.lower()


def test_sicologia_matchea_psicologia():
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-5", "sicologia")
    assert "fechas disponibles" in r2.lower()


def test_typo_con_palabras_extra_alrededor_tambien_matchea():
    """El paciente no solo escribe el nombre del servicio: lo rodea de
    frases reales completas — la ventana de comparación debe tolerarlo,
    no solo un typo aislado sin nada más."""
    r2 = _preguntar_servicio_y_responder(
        _gateway_catalogo_real(), "TG-036-6", "necesito una cita de pedeatria por favor"
    )
    assert "fechas disponibles" in r2.lower()


# ---------------------------------------------------------------------
# 2. Ambigüedad genuina — nunca se elige por el paciente. Usa el
#    catálogo FICTICIO de prueba (ver docstring de
#    `_CatalogoHipoteticoConAmbiguedad`) porque el catálogo real de hoy
#    no produce este caso (confirmado arriba) — el mecanismo debe
#    funcionar igual el día que sí ocurra.
# ---------------------------------------------------------------------
def test_ambiguedad_genuina_pide_confirmar_mostrando_solo_los_candidatos_cercanos():
    r2 = _preguntar_servicio_y_responder(_gateway_ambiguo(), "TG-036-7", "pequiatria")
    assert "fechas disponibles" not in r2.lower(), (
        "un texto ambiguo entre dos nombres del catálogo nunca debe elegir uno por el paciente"
    )
    assert "pediatria" in r2.lower() and "psiquiatria" in r2.lower()


def test_ambiguedad_genuina_no_cae_en_el_fallback_generico():
    """Distinción explícita: el mensaje de ambigüedad NO es el mismo
    que el fallback de 'no logré identificar' — reconoce que el
    paciente sí escribió algo cercano a dos opciones reales."""
    r2 = _preguntar_servicio_y_responder(_gateway_ambiguo(), "TG-036-8", "pequiatria")
    assert "no logré identificar" not in r2.lower()


def test_ambiguedad_rota_entre_variantes_igual_que_el_resto_del_archivo():
    """Mismo criterio del recado 034: dos aclaraciones seguidas del
    MISMO tipo, en la MISMA conversación, no repiten literalmente la
    misma frase."""
    gateway = _gateway_ambiguo()
    pref = "TG-036-9"
    handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    r1 = handle_inbound_message(gateway, pref, "telegram", "m2", "pequiatria")
    r2 = handle_inbound_message(gateway, pref, "telegram", "m3", "pequiatria")
    assert r1 != r2


# ---------------------------------------------------------------------
# 3. Texto que no se parece a ningún servicio real — sigue usando el
#    fallback normal, nunca inventa un match falso. Contra el catálogo
#    REAL de 5.
# ---------------------------------------------------------------------
def test_texto_no_relacionado_sigue_usando_el_fallback_normal():
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-10", "no se, cualquiera")
    assert "no logré identificar" in r2.lower()
    assert "medicina general" in r2.lower() and "pediatria" in r2.lower()


def test_servicio_genuinamente_distinto_no_se_confunde_por_similitud_parcial():
    """'medicina interna' se PARECE a 'Medicina General' (comparten la
    primera palabra) pero es un servicio real distinto — no debe cruzar
    el umbral por esa similitud parcial (puntúa 0.812, el umbral es
    0.82: por debajo, cae al fallback en vez de asumir el servicio
    equivocado)."""
    r2 = _preguntar_servicio_y_responder(_gateway_catalogo_real(), "TG-036-11", "medicina interna")
    assert "no logré identificar" in r2.lower()


# ---------------------------------------------------------------------
# 4. Requisito #5 del pedido: confirmar si el mismo problema aplica a
#    selección de fecha/horario antes de decidir si extender fuzzy
#    matching ahí también. NO aplica: ambas etapas seleccionan por
#    ORDINAL (1/primera, 2/segunda, 3/tercera — `_elegir_opcion`,
#    brain.py), nunca por el nombre libre de la fecha/hora en sí. No
#    hay ningún nombre de catálogo contra el cual el paciente pueda
#    escribir un typo — el patrón de bug de este recado no existe ahí.
#    Este test lo confirma con evidencia, en vez de asumirlo.
# ---------------------------------------------------------------------
def test_seleccion_de_fecha_es_por_ordinal_no_por_nombre_libre_no_aplica_fuzzy():
    gateway = _gateway_catalogo_real()
    pref = "TG-036-12"
    handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    handle_inbound_message(gateway, pref, "telegram", "m2", "pediatria")
    # Ni siquiera un typo del ORDINAL tiene sentido: "1"/"primera" son
    # las únicas formas reconocidas, no hay un "nombre" de fecha real
    # contra el cual comparar con tolerancia a errores.
    r3 = handle_inbound_message(gateway, pref, "telegram", "m3", "primera")
    assert "no logré identificar" not in r3.lower()
