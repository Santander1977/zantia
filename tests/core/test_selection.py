"""
Recado 052 — mecanismo GENÉRICO (agnóstico de dominio) para interpretar,
con ayuda de un LLM, en qué opción de una lista de opciones REALES ya
ofrecidas pensó el usuario, con verificación estructural: la propuesta
del LLM NUNCA se acepta salvo que corresponda EXACTAMENTE (por `id`) a
una de las opciones entregadas.

Ejemplos deliberadamente NO relacionados con salud (un "trámite"
genérico) para dejar explícito que `core/selection.py` no sabe nada de
fechas/horarios/citas — mismo criterio ya usado en
`tests/guardrails/test_guardrails_pre_llm.py`.
"""
from core.selection import SelectionOption, SelectionResult, interpret_selection


def _opciones():
    return [
        SelectionOption(id="TRAMITE-A", text="Solicitud de certificado"),
        SelectionOption(id="TRAMITE-B", text="Renovación de documento"),
        SelectionOption(id="TRAMITE-C", text="Reclamo de servicio"),
    ]


class _ProposerFijo:
    """Doble de prueba simple: siempre propone el mismo id, sin mirar
    el texto — suficiente para probar el CONTRATO de verificación."""

    def __init__(self, id_propuesto):
        self._id = id_propuesto

    def propose(self, free_text, options):
        return self._id


class _ProposerQueFalla:
    def propose(self, free_text, options):
        raise RuntimeError("fallo simulado de red/API")


class _ProposerRealistaLenguajeNatural:
    """Simula un LLM real interpretando frases naturales variadas —
    reconoce, por posición/orden mencionado, cuál opción de la lista
    quiso decir el usuario (igual que interpretaría un LLM real dada la
    lista completa), sin ningún vocabulario de dominio."""

    def propose(self, free_text, options):
        texto = free_text.lower()
        if "medio" in texto:
            return options[1].id if len(options) >= 2 else None
        if "primera" in texto or "primero" in texto:
            return options[0].id
        if "ultima" in texto or "última" in texto or "tercera" in texto:
            return options[-1].id
        # "esa que dijiste primero" / "el certificado" -> matchea por texto
        for o in options:
            if o.text.split()[0].lower() in texto:
                return o.id
        return None


# ---------------------------------------------------------------------
# 1. Interpretación exitosa con lenguaje natural variado.
# ---------------------------------------------------------------------
def test_interpreta_la_del_medio():
    resultado = interpret_selection("la del medio", _opciones(), _ProposerRealistaLenguajeNatural())
    assert resultado.option == _opciones()[1]
    assert resultado.source == "llm"


def test_interpreta_esa_que_dijiste_primero():
    resultado = interpret_selection("esa que dijiste primero", _opciones(), _ProposerRealistaLenguajeNatural())
    assert resultado.option == _opciones()[0]
    assert resultado.source == "llm"


def test_interpreta_referencia_por_nombre_de_la_opcion():
    resultado = interpret_selection(
        "quiero la renovación", _opciones(), _ProposerRealistaLenguajeNatural()
    )
    assert resultado.option.id == "TRAMITE-B"


# ---------------------------------------------------------------------
# 2. Nunca se acepta una propuesta que no corresponde a una opción real
#    (alucinación forzada) — el contrato central de este módulo.
# ---------------------------------------------------------------------
def test_rechaza_un_id_alucinado_que_no_existe_en_las_opciones():
    proposer = _ProposerFijo("TRAMITE-INVENTADO-999")
    resultado = interpret_selection("cualquier cosa", _opciones(), proposer)
    assert resultado == SelectionResult(None, "none")


def test_rechaza_id_ambiguo_por_opciones_del_dominio_con_ids_duplicados():
    """Caso límite: si el propio dominio ofreciera dos opciones con el
    MISMO id (nunca debería pasar, pero el mecanismo no debe adivinar
    ni reventar) — se rechaza igual que una alucinación."""
    opciones_duplicadas = [
        SelectionOption(id="X", text="Primera"),
        SelectionOption(id="X", text="Segunda, con el mismo id por error"),
    ]
    proposer = _ProposerFijo("X")
    resultado = interpret_selection("cualquier cosa", opciones_duplicadas, proposer)
    assert resultado == SelectionResult(None, "none")


def test_none_propuesto_por_el_llm_no_es_un_error_es_sin_seleccion():
    proposer = _ProposerFijo(None)
    resultado = interpret_selection("no sé cuál", _opciones(), proposer)
    assert resultado == SelectionResult(None, "none")


# ---------------------------------------------------------------------
# 3. Fallback correcto cuando no hay LLM disponible o falla — nunca
#    lanza una excepción sin manejar, nunca deja al llamador sin respuesta.
# ---------------------------------------------------------------------
def test_sin_proposer_configurado_devuelve_ninguna_seleccion_sin_fallar():
    resultado = interpret_selection("la del medio", _opciones(), None)
    assert resultado == SelectionResult(None, "none")


def test_proposer_que_falla_se_captura_y_devuelve_ninguna_seleccion():
    resultado = interpret_selection("la del medio", _opciones(), _ProposerQueFalla())
    assert resultado == SelectionResult(None, "none")


def test_sin_opciones_ofrecidas_devuelve_ninguna_seleccion_sin_llamar_al_proposer():
    llamado = []

    class _ProposerQueNoDeberiaLlamarse:
        def propose(self, free_text, options):
            llamado.append(True)
            return "lo que sea"

    resultado = interpret_selection("hola", [], _ProposerQueNoDeberiaLlamarse())
    assert resultado == SelectionResult(None, "none")
    assert llamado == []
