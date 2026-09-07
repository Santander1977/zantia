"""
HealthBrain — Brain de dominio para demanda inducida (prompt 007,
secciones 9-10).

Implementa el mismo Protocol `core.brain.Brain` del Core (sin tocarlo)
— construido con un PROVEEDOR de la Activity (una función sin
argumentos que devuelve la Activity vigente), no con la Activity misma,
porque `Activity` es un modelo pydantic inmutable: cada actualización
de dominio crea una copia nueva (`model_copy`), así que guardar una
referencia fija en el constructor congelaría al Brain con la primera
versión para siempre (p. ej. nunca vería el `appointment_id` una vez
reservado). Corrección encontrada al construir este dominio — ver
recado 007. Tampoco recibe la Activity como parámetro de `interpret()`
(así no hace falta ampliar el contrato del Core: 004, sección 15).

Simplificación deliberada y documentada: para componer una respuesta en
lenguaje natural con opciones REALES (nunca inventadas — sección 13),
este Brain consulta `AppointmentService.get_availability()` (una tool
READ) directamente, además de proponer el `tool_requerida` formal para
que el Core la ejecute y audite igual. Nunca hace lo mismo con una
operación WRITE (reservar/reprogramar/cancelar) — esas SIEMPRE se
proponen solo como `tool_requerida`, nunca se ejecutan desde el Brain
(mismo principio de autoridad del Core: el LLM propone, nunca escribe).
"""
from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.brain import BrainOutput
from memory.conversation_memory import Turn
from state.models import ConversationState

from .appointment_service import AppointmentService

# Normalización de tildes — NUNCA toca "ñ" ("año"/"ano" son palabras
# distintas, eso no es lo que se está corrigiendo aquí). Bug real de
# producción, encontrado en 3 recados seguidos con la misma causa raíz
# (026, 027, 030): un paciente real escribiendo rápido en Telegram omite
# tildes con mucha frecuencia ("que" en vez de "qué", "Si" en vez de
# "Sí", "Cual" en vez de "Cuál") — cualquier comparación por palabras
# clave que EXIJA la tilde falla en silencio contra el español real de
# un paciente. Aplicado de forma ACOTADA (recado 030): solo a las
# comparaciones directamente implicadas en los bugs ya reportados
# (sí/no y catálogo de servicios) — NO se generalizó a todo el archivo
# de una vez (`_PIDE_INFO`, `_HUMANO`, etc. probablemente comparten el
# mismo riesgo, sin reportar todavía — ver recomendación en el recado
# 030 sobre un rediseño más amplio, deliberadamente no implementado en
# esta sesión).
_MAPA_SIN_TILDES = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _sin_tildes(texto: str) -> str:
    return texto.translate(_MAPA_SIN_TILDES)


# "sí"/"no" como PALABRA (límite de palabra `\b`), no como substring
# suelto — sigue evitando el falso positivo original ("asistir",
# "sinceramente") sin la fragilidad de la versión anterior basada en
# tildes/comas/espacios manuales. Aplicado siempre sobre texto YA sin
# tildes (`_sin_tildes`), así que reconoce "sí"/"Sí"/"si" por igual, y
# en CUALQUIER posición del mensaje — no solo como mensaje completo ni
# solo con coma/espacios alrededor. Bug real que esto corrige (recado
# 030): "Si claro ayúdame puedes orientarme mejor" no coincidía con
# NINGÚN patrón de `_ACEPTA` (sin tilde, y "si" es la primera palabra
# sin coma ni espacio previo) — el paciente quedaba sin poder avanzar
# aunque su respuesta era claramente afirmativa.
_RE_PALABRA_SI = re.compile(r"\bsi\b")
_RE_PALABRA_NO = re.compile(r"\bno\b")

# Frases de aceptación/rechazo MÁS ALLÁ de la palabra suelta "sí"/"no"
# — ya sin tildes (se comparan contra texto normalizado).
_ACEPTA_FRASES = ("acepto", "me interesa", "claro que", "dale", "vale", "de acuerdo", "esta bien")
_DECLINA_FRASES = ("no me interesa", "no gracias", "no quiero", "no estoy interesado")
# Pregunta por el catálogo de servicios SIN nombrar uno específico
# (recado 027, bug real: "Programar cuál servicios tienes disponible" no
# se reconocía como esto — caía a `_PROGRAMAR` en `intent.py` por la
# palabra suelta "programar", y una vez dentro de la conversación
# tampoco había ningún patrón aquí que la reconociera, así que quedaba
# rebotando entre la pregunta fija de sí/no y "sin disponibilidad" para
# el servicio por defecto ("medicina general", nunca confirmado por el
# paciente). Mismas frases que `intent.py:_INFORMACION`, deliberadamente
# duplicadas en vez de importadas: `intent.py` clasifica un mensaje
# ENTRANTE sin conversación previa; esto reconoce la misma pregunta
# DENTRO de una conversación ya abierta — capas distintas, incluso si
# hoy el catálogo de frases coincide. Ya SIN tildes (recado 030, mismo
# hallazgo que arriba: "Que tienes disponible para citas" tampoco
# coincidía con nada por la tilde faltante en "qué") — se comparan
# contra texto normalizado.
_CONSULTAR_SERVICIOS = (
    "que servicios tienen", "que servicios tienes", "que servicios ofrecen",
    "cuales servicios", "cual servicios", "cual servicio", "que servicios hay",
    "servicios disponibles", "que tienes disponible", "que tienen disponible",
    "cual tienes", "cuales tienes",
)
# Saludo simple — reconocido con la MISMA prioridad baja que el
# fallback final (recado 030, pedido explícito del usuario: "un saludo
# nuevo debería poder... al menos reconocer que el paciente intentó
# decir algo"): no dispara ninguna lógica nueva de reserva/estado —
# solo cambia el tono de la respuesta cuando ninguna otra rama coincide,
# para que un "Hola" a mitad de una conversación no se sienta ignorado.
_SALUDOS = ("hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "que tal", "hey", "ola")
_HUMANO = ("hablar con alguien", "persona real", "un humano", "un asesor", "quiero hablar con")
_NO_PUEDE_AHORA = ("no puedo ahora", "ahora no puedo", "en otro momento", "llámame después", "más tarde no")
_PIDE_INFO = ("qué es", "más información", "cuéntame más", "por qué me contactan", "explícame", "de qué se trata")
_INFO_NO_AUTORIZADA = ("mi diagnóstico", "diagnostico", "resultado de mis examenes", "resultado de mis exámenes", "qué enfermedad tengo", "qué tengo")
_REPROGRAMAR = ("no puedo asistir", "reprogramar", "cambiar la cita", "otro día", "otra fecha")
_CANCELAR = ("cancelar la cita", "ya no quiero la cita", "cancela mi cita")
_CONFIRMA = ("confirmo", "sí, confirmo", "asistiré", "voy a asistir", "ahí estaré", "ahí voy a estar", "confirmado", "ahí llego")
# Gestión "en nombre de otro paciente" (recado 013, extensión de R-15):
# el titular del canal (ya verificado) declara que la gestión es para
# un beneficiario distinto. Solo relevante con un AppointmentService que
# expone `buscar_paciente` (HrmmAppointmentService) — con
# MockAppointmentService esta frase se ignora, comportamiento idéntico
# al de antes de esta extensión (requisito #5).
_PARA_OTRO = (
    "es para mi mamá", "es para mi mama", "es para mi papá", "es para mi papa",
    "para mi mamá", "para mi mama", "para mi papá", "para mi papa",
    "para mi hijo", "para mi hija", "para mi esposa", "para mi esposo",
    "para otra persona", "no es para mí", "no es para mi",
)
# Olvido de identidad de canal (recado 016, extensión de R-20) — pedido
# explícito del paciente de que se elimine su asociación teléfono↔documento
# (`domains/health/identity_store.py`). Conjunto razonable de frases
# coloquiales en español (requisito #1 del pedido), no exhaustivo — mismo
# criterio que el resto de los conjuntos de este archivo (palabras clave,
# no NLU real, ver `.ai/RISKS.md` R-13).
_OLVIDAR = (
    "olvida mi número", "olvida mi numero", "olvida mi información", "olvida mi informacion",
    "olvida mis datos", "olvídame", "olvidame",
    "borra mi número", "borra mi numero", "borra mi información", "borra mi informacion",
    "borra mis datos",
    "elimina mi información", "elimina mi informacion", "elimina mis datos",
    "no quiero que tengas mis datos", "deja de guardar mis datos",
)

# Recado 047 — etapas que YA son, ellas mismas, parte de un wizard de
# interrupción en curso (documento/confirmación de beneficiario): se
# excluyen del chequeo global de interrupciones de contexto para no
# reinterrumpir un wizard que ya está resolviendo una interrupción
# anterior (ej. el documento que el paciente escribe ahí no debería
# poder disparar, por coincidencia, otra interrupción distinta).
_ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO = frozenset(
    {"esperando_documento_beneficiario", "esperando_confirmacion_beneficiario"}
)


def _contains_any(texto: str, opciones: tuple) -> bool:
    return any(o in texto for o in opciones)


def _contains_any_sin_tildes(texto: str, opciones: tuple) -> bool:
    """Igual que `_contains_any`, pero comparando sobre el texto sin
    tildes (`_sin_tildes`) — `opciones` ya debe venir sin tildes."""
    return _contains_any(_sin_tildes(texto), opciones)


def _es_afirmativo(texto: str) -> bool:
    normalizado = _sin_tildes(texto)
    return bool(_RE_PALABRA_SI.search(normalizado)) or _contains_any(normalizado, _ACEPTA_FRASES)


def _es_negativo(texto: str) -> bool:
    normalizado = _sin_tildes(texto)
    return bool(_RE_PALABRA_NO.search(normalizado)) or _contains_any(normalizado, _DECLINA_FRASES)


def _es_saludo(texto: str) -> bool:
    return _contains_any_sin_tildes(texto, _SALUDOS)


# Variantes de mensajes de aclaración/fallback (recado 034, pedido
# explícito del usuario): un paciente que se equivoca dos veces
# seguidas no debe recibir literalmente la misma frase — igual que un
# humano no se repetiría palabra por palabra. La rotación es
# DETERMINISTA (nunca al azar, consistente con el resto del archivo:
# palabras clave, sin NLU real) — un contador en `datos_recopilados`
# avanza en cada fallback del MISMO tipo dentro de la MISMA
# conversación; `_elegir_variante` solo hace `contador % len(variantes)`.
def _elegir_variante(variantes: tuple, datos: Dict[str, Any], clave_contador: str) -> tuple:
    """Devuelve `(variante_elegida, datos_actualizados)` — nunca muta
    `datos` in-place (mismo criterio del resto del archivo: siempre
    copias nuevas vía `{**datos, ...}`)."""
    contador = datos.get(clave_contador, 0)
    variante = variantes[contador % len(variantes)]
    return variante, {**datos, clave_contador: contador + 1}


# Todas contienen "sí"/"no"/"agendar" (sustancia idéntica — solo cambia
# la redacción) para no romper ninguna garantía de contenido existente.
# La segunda variante reconoce explícitamente que el paciente escribió
# algo (pedido #2 del usuario: "reconocer qué fue lo que el paciente
# dijo antes de repreguntar") sin citar el texto literal (evita
# problemas con mensajes muy largos o con caracteres inesperados).
_VARIANTES_ACLARACION_SI_NO = (
    "No logré entender si es un sí o un no — ¿me confirmas si quieres que te ayude a agendar tu atención?",
    "Vi tu mensaje, pero no me quedó claro si es un sí o un no — ¿podrías confirmármelo con esa palabra, así te ayudo a agendar?",
    "Perdona, no logré identificar si tu respuesta es un sí o un no — ¿me lo confirmas así puedo seguir ayudándote a agendar?",
)
_VARIANTES_SERVICIO_NO_IDENTIFICADO = (
    "No logré identificar cuál de estos prefieres: {opciones}. ¿Me confirmas el nombre tal como aparece en la lista?",
    "Perdona, no reconocí cuál de estos servicios quieres: {opciones}. ¿Me lo repites tal cual aparece ahí?",
)
_VARIANTES_SELECCION_NO_IDENTIFICADA = (
    "No logré identificar cuál prefieres — ¿me confirmas si es la 1, la 2 o la 3?",
    "No estoy seguro de haber entendido cuál elegiste — ¿me dices si es la 1, la 2 o la 3?",
)
_VARIANTES_FECHA_NO_IDENTIFICADA = (
    "No logré identificar cuál fecha prefieres — ¿me confirmas si es la 1, la 2 o la 3?",
    "Perdona, no reconocí cuál de esas fechas elegiste — ¿me dices si es la 1, la 2 o la 3?",
)
# Ambigüedad genuina de servicio (recado 036) — el paciente escribió
# algo que se parece razonablemente a MÁS DE UN servicio real (ej.
# "pequiatria" entre "pediatria" y "psiquiatria"): nunca se elige por
# el paciente, se le muestran solo los candidatos cercanos encontrados
# (no el catálogo completo de nuevo, para reconocer que sí escribió
# algo reconocible).
_VARIANTES_SERVICIO_AMBIGUO = (
    "Creo que podrías referirte a más de uno de estos: {opciones}. ¿Cuál de los dos es el que necesitas?",
    "No quiero adivinar entre estos: {opciones}. ¿Me confirmas cuál de los dos prefieres?",
)

# Nombres en español para formatear una fecha real ("2026-09-07") de
# forma legible ("Lunes 7 de septiembre") — recado 035, Paso 2 del
# asistente de reserva en etapas. Deliberadamente SIN depender de
# `locale.setlocale` (no determinista entre entornos/contenedores,
# depende de qué locales tenga instalados el sistema operativo) — una
# tabla fija es más simple y 100% portable.
_DIAS_SEMANA = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _formatear_fecha_humana(fecha_iso: str) -> str:
    """`"2026-09-07"` -> `"Lunes 7 de septiembre"`. Si `fecha_iso` no
    viene en el formato esperado (nunca debería pasar con datos reales
    de `AvailabilitySlot.date`), se devuelve tal cual — nunca se
    inventa una fecha ni se rompe la conversación por un formato
    inesperado."""
    try:
        fecha = datetime.strptime(fecha_iso, "%Y-%m-%d")
    except ValueError:
        return fecha_iso
    return f"{_DIAS_SEMANA[fecha.weekday()]} {fecha.day} de {_MESES[fecha.month - 1]}"


# Tolerancia a errores de tipeo al elegir un servicio por nombre libre
# (recado 036, pedido explícito del usuario): un paciente real escribe
# "pedeatria", "pediatra", "medisina general", "sicologia" — ninguno
# calza como substring exacto contra el catálogo real, aunque la
# intención sea clara para un humano. Se usa `difflib.SequenceMatcher`
# (librería estándar, sin dependencia nueva — decisión explícita:
# `rapidfuzz` no está instalado en este proyecto, y el pedido permitía
# cualquiera de las dos) en vez de reglas manuales nuevas, que solo
# cubrirían los typos ya vistos y no generalizarían a otros.
#
# UMBRAL elegido: 0.82 (82%) — calibrado con ejemplos reales de esta
# sesión (ver recado 036 para la tabla completa de puntajes): todos los
# typos reales pedidos puntúan >= 0.889 contra su servicio real
# correspondiente, con el siguiente candidato más cercano por debajo de
# 0.6 en todos los casos salvo ambigüedad genuina. Al mismo tiempo,
# 0.82 sigue siendo lo bastante estricto para NO confundir servicios
# genuinamente distintos: "medicina interna" contra el catálogo
# ["medicina general", ...] puntúa 0.812 — por debajo del umbral, así
# que cae al fallback en vez de asumir "medicina general" por error.
_UMBRAL_FUZZY_SERVICIO = 0.82


def _tokens_sin_puntuacion_de_borde(texto: str) -> List[str]:
    return [p for p in (palabra.strip(".,;:!?¿¡") for palabra in texto.split()) if p]


def _similitud_servicio(tokens_texto: List[str], servicio_normalizado: str) -> float:
    """Compara el texto libre del paciente (ya tokenizado) contra UN
    nombre real de servicio, tolerando palabras de más alrededor (ej.
    "necesito una cita de pediatria por favor" contra "pediatria"): se
    prueban todas las ventanas contiguas de tokens del MISMO largo que
    el servicio (1 palabra para "pediatria", 2 para "medicina general",
    etc.) y se toma la mejor similitud de cualquiera de ellas — nunca
    el texto completo contra un servicio corto, que penalizaría por
    longitud sin razón."""
    palabras_servicio = servicio_normalizado.split()
    n = len(palabras_servicio)
    if len(tokens_texto) < n:
        ventanas = [" ".join(tokens_texto)]
    else:
        ventanas = [" ".join(tokens_texto[i : i + n]) for i in range(len(tokens_texto) - n + 1)]
    return max(
        (SequenceMatcher(None, ventana, servicio_normalizado).ratio() for ventana in ventanas),
        default=0.0,
    )


def _emparejar_servicio_por_similitud(texto: str, servicios: List[str]) -> Tuple[Optional[str], List[str]]:
    """Devuelve `(servicio_elegido, candidatos_ambiguos)` — nunca ambos
    a la vez con contenido: un único candidato claro por encima del
    umbral -> `(nombre, [])`; dos o más candidatos reales por encima
    del umbral (ambigüedad genuina) -> `(None, [nombres...])`, nunca se
    elige por el paciente; ninguno por encima del umbral -> `(None,
    [])`, mismo fallback de siempre."""
    tokens = _tokens_sin_puntuacion_de_borde(_sin_tildes(texto).lower())
    puntajes = {
        servicio: _similitud_servicio(tokens, _sin_tildes(servicio).lower())
        for servicio in servicios
    }
    candidatos = sorted(
        (servicio for servicio, puntaje in puntajes.items() if puntaje >= _UMBRAL_FUZZY_SERVICIO),
        key=lambda servicio: puntajes[servicio],
        reverse=True,
    )
    if len(candidatos) == 1:
        return candidatos[0], []
    if len(candidatos) >= 2:
        return None, candidatos
    return None, []


class HealthBrain:
    def __init__(self, activity_provider: Callable[[], Any], appointment_service: AppointmentService) -> None:
        self._activity_provider = activity_provider
        self._appointment_service = appointment_service

    @property
    def _activity(self):
        """Siempre la Activity VIGENTE — nunca una copia congelada del
        momento de construcción (ver docstring del módulo)."""
        return self._activity_provider()

    # ------------------------------------------------------------------
    def interpret(
        self,
        message: str,
        state: ConversationState,
        recent_turns: List[Turn],
    ) -> BrainOutput:
        texto = message.lower().strip()
        datos = dict(state.datos_recopilados)
        etapa = datos.get("etapa", "esperando_decision")

        # Olvido de identidad de canal (recado 016, extensión de R-20):
        # se reconoce en CUALQUIER etapa, con la MISMA prioridad que el
        # Core ya le da a una interrupción global (riesgo/escalamiento,
        # 004 sección 9) — ni siquiera depende de que haya una cita
        # reservada, a diferencia de reprogramar/cancelar/confirmar
        # abajo. `datos_recopilados["etapa"] == "confirmando_olvido"` es
        # un wizard de un solo paso PROPIO (no forma parte de ninguna
        # otra máquina de etapas existente) que se resuelve antes que
        # cualquier otra cosa, para no perder la confirmación pendiente
        # si el paciente escribe algo ambiguo mientras tanto.
        if etapa == "confirmando_olvido":
            return self._interpretar_confirmacion_olvido(texto, datos)
        if _contains_any(texto, _OLVIDAR):
            return self._iniciar_olvido(datos, etapa)

        # Interrupciones de CONTEXTO (recado 047, corrige un hallazgo
        # real de producción con HEALTH_BRAIN_TYPE=llm activo, recado
        # 046): info no autorizada / pedido de humano / "no puedo
        # ahora" / pide info / declaración de beneficiario se
        # reconocían SOLO en la etapa "esperando_decision" (el primer
        # turno) — un paciente que las mencionara en CUALQUIER etapa
        # posterior (ej. "Odontologia PERO ES PARA MI HIJA" al elegir
        # servicio) nunca las activaba, aunque el mensaje completo SÍ
        # llegaba íntegro a esta función (confirmado con evidencia real,
        # ver recado 046 — el hueco nunca fue que el LLM "escondiera"
        # texto del código determinista). Ahora se revisan en CUALQUIER
        # etapa, mismo criterio que `_OLVIDAR` arriba — con la excepción
        # explícita de las etapas que YA son, ellas mismas, parte de un
        # wizard de interrupción en curso (`_ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO`),
        # para no reinterrumpir un wizard que ya está resolviendo una
        # interrupción anterior.
        if etapa not in _ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO:
            interrupcion = self._detectar_interrupcion_de_contexto(texto, datos, etapa)
            if interrupcion is not None:
                return interrupcion

        # Reprogramar/cancelar/confirmar se reconocen en cualquier etapa
        # posterior a una cita ya reservada (equivalente sano a la
        # interrupción global del Core, pero de dominio: secciones
        # 19-23) — independiente de `etapa`, que el Core puede haber
        # reiniciado al reabrir la conversación desde CIERRE (un
        # recordatorio llega días después de la reserva original: 004,
        # sección 9, "un mensaje nuevo reabre el ciclo").
        if self._activity.appointment_id and _contains_any(texto, _REPROGRAMAR):
            return self._iniciar_reprogramacion(datos)
        if self._activity.appointment_id and _contains_any(texto, _CANCELAR):
            return self._cancelar(datos)
        if self._activity.appointment_id and _contains_any(texto, _CONFIRMA):
            return BrainOutput(
                senales_detectadas=["asistencia_confirmada"],
                respuesta_propuesta="¡Perfecto, ahí te esperamos!",
                # marca la etapa para que la capa de dominio (agent.py)
                # pueda devolver management_status a APPOINTMENT_CONFIRMED
                # — `fire_reminder` lo había dejado en REMINDER_72H/24H/8H
                # (sección 6: ambos son management_status válidos, mutuamente
                # excluyentes en el momento, no acumulables).
                propuesta_de_actualizacion_de_estado={
                    "datos_recopilados": {**datos, "etapa": "asistencia_confirmada"}
                },
            )

        if etapa == "esperando_decision":
            return self._interpretar_decision(texto, datos)
        if etapa == "esperando_servicio":
            return self._interpretar_servicio(texto, datos)
        if etapa == "esperando_documento_beneficiario":
            # Usa `message` SIN lowercase (no `texto`): un documento de
            # identidad es un identificador crudo, no una palabra clave
            # — lowercasearlo antes de compararlo contra buscar_paciente
            # podría corromper un documento con letras (encontrado
            # probando este flujo, ver recado 013).
            return self._interpretar_documento_beneficiario(message.strip(), datos)
        if etapa == "esperando_confirmacion_beneficiario":
            return self._interpretar_confirmacion_beneficiario(texto, datos)
        if etapa == "esperando_fecha":
            return self._interpretar_fecha(texto, datos)
        if etapa == "esperando_horario":
            return self._interpretar_horario(texto, datos)
        if etapa == "esperando_seleccion_reprogramacion":
            return self._interpretar_seleccion_reprogramacion(texto, datos)

        # Fallback defensivo: no debería alcanzarse en el flujo normal.
        return BrainOutput(
            respuesta_propuesta="Cuéntame en qué te puedo ayudar.",
            proxima_accion_propuesta="preguntar_intencion",
        )

    # ------------------------------------------------------------------
    def _detectar_interrupcion_de_contexto(
        self, texto: str, datos: Dict[str, Any], etapa_actual: str
    ) -> Optional[BrainOutput]:
        """Recado 047 — extraído de `_interpretar_decision` (donde antes
        vivían, solo alcanzables desde la etapa "esperando_decision") para
        que estas 5 categorías se revisen en CUALQUIER etapa (ver llamada
        en `interpret()`), sin duplicar la lógica de detección en cada
        función de etapa específica (`_interpretar_servicio`,
        `_interpretar_fecha`, `_interpretar_horario`, etc. — ninguna de
        ellas necesitó tocarse). Devuelve `None` si el texto no coincide
        con ninguna — quien llama sigue con el flujo normal de esa etapa.

        Mismo orden de prioridad que tenía `_interpretar_decision` (recado
        030): info no autorizada, humano, no puede ahora, pide info,
        beneficiario — antes de que la etapa específica interprete el
        mensaje a su manera."""
        if _contains_any(texto, _INFO_NO_AUTORIZADA):
            return BrainOutput(
                senales_detectadas=["informacion_no_autorizada"],
                respuesta_propuesta=(
                    "Uy, esa parte no te la puedo compartir por este canal — no puedo darte información "
                    "clínica que no esté autorizada aquí. Si quieres, con gusto pongo tu duda "
                    "en manos del equipo para que te ayuden con eso."
                ),
                proxima_accion_propuesta="preguntar_intencion",
                # `etapa` no cambia (mismo `datos` sin tocar) — el
                # paciente sigue exactamente donde estaba, en CUALQUIER
                # etapa (antes esto solo era cierto para "esperando_decision").
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        if _contains_any(texto, _HUMANO):
            nuevos = {**datos, "etapa": "escalada"}
            return BrainOutput(
                senales_detectadas=["solicita_humano"],
                respuesta_propuesta="Claro que sí, voy a poner tu caso en manos de una persona del equipo.",
                propuesta_de_actualizacion_de_estado={
                    "datos_recopilados": nuevos,
                    "necesidad_de_escalar": True,
                    "motivo_escalamiento": "paciente solicitó hablar con una persona",
                },
            )

        if _contains_any(texto, _NO_PUEDE_AHORA):
            nuevos = {**datos, "etapa": "finalizada", "decision": "NO_PUEDE_AHORA"}
            return BrainOutput(
                respuesta_propuesta="Sin problema, lo intentamos en otro momento — gracias por tu tiempo.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _contains_any(texto, _PIDE_INFO):
            # NUNCA "te contactamos" (mismo hallazgo del recado 026,
            # esta rama se había quedado sin corregir): esa frase está en
            # `guardrails/rules.py:_PROMESAS_PROHIBIDAS` y
            # `NoPrometerContactoGuardrail` la reescribe en silencio por
            # el mensaje genérico de escalamiento.
            motivo = self._activity.reason or self._activity.program or "una atención pendiente"
            return BrainOutput(
                respuesta_propuesta=(
                    f"Con gusto te cuento: esto es sobre {motivo}. La idea es ayudarte a "
                    "programar tu atención cuando te quede cómodo. ¿Revisamos juntos las opciones de horario?"
                ),
                proxima_accion_propuesta="preguntar_intencion",
                # `etapa` no cambia — mismo criterio que INFO_NO_AUTORIZADA
                # arriba.
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        # Gestión para un beneficiario (recado 013, generalizado a
        # cualquier etapa en el recado 047 — hallazgo real de
        # producción, recado 046: "Odontologia pero es para mi hija" al
        # elegir servicio nunca activaba esto). `etapa_antes_de_beneficiario`
        # (mismo patrón ya usado por `_iniciar_olvido`/
        # `etapa_antes_de_olvido`) es lo que le permite a
        # `_interpretar_confirmacion_beneficiario` RETOMAR exactamente
        # donde el paciente iba — nunca reiniciar el flujo completo —
        # sin perder nada de lo ya elegido (`datos` se preserva íntegro
        # vía `{**datos, ...}`, solo se agrega/sobrescribe la etapa).
        if _contains_any(texto, _PARA_OTRO) and getattr(self._appointment_service, "buscar_paciente", None) is not None:
            # Nota (recado 050): cuando este detector se reevalúa desde
            # `gateway.py:_evaluar_ventana_de_gracia` sobre una Activity
            # YA CERRADA con una reserva real ya ejecutada
            # (`self._activity.appointment_id` no es `None`), el
            # llamador puede decidir DESCARTAR esta respuesta y sustituirla
            # por una que remita al flujo de cancelación ya existente y
            # protegido por código de verificación, en vez de arrancar
            # este wizard (que reservaría una SEGUNDA cita sin cancelar
            # la primera). Esa decisión vive deliberadamente en
            # `gateway.py`, no acá: distinguir "esto es sobre una cita
            # NUEVA" de "esto es una corrección sobre la que se acaba de
            # hacer" requiere cruzar esta señal con `classify_intent_or_none`
            # (capa de dominio/gateway, nunca del Brain — ver docstring
            # de `_evaluar_ventana_de_gracia`). Este método sigue
            # devolviendo siempre la misma respuesta de siempre — cero
            # cambio de comportamiento para el camino normal (recado 047).
            nuevos = {
                **datos,
                "etapa": "esperando_documento_beneficiario",
                "etapa_antes_de_beneficiario": etapa_actual,
            }
            return BrainOutput(
                senales_detectadas=["gestion_para_beneficiario_declarada"],
                respuesta_propuesta=(
                    "Con gusto te ayudo con eso — ¿me confirmas el número de documento de identidad "
                    "de la persona para quien es la cita?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        return None

    def _reanudar_tras_interrupcion(self, etapa_a_reanudar: str, datos: Dict[str, Any]) -> BrainOutput:
        """Recado 047 — tras resolver una interrupción que sí necesita
        "retomar" el flujo (hoy, solo la confirmación de beneficiario —
        HUMANO/NO_PUEDE_AHORA terminan la conversación,
        INFO_NO_AUTORIZADA/PIDE_INFO nunca cambian de etapa, así que no
        necesitan esto), vuelve exactamente al punto donde el paciente
        iba. Reutiliza las funciones "ofrecer" YA EXISTENTES (nunca
        reconstruye un mensaje a mano con datos potencialmente
        obsoletos) — cada una vuelve a consultar `AppointmentService`
        con lo YA elegido (`servicio_elegido`/`fecha_elegida`, todavía
        en `datos`), así que la disponibilidad que se muestra sigue
        siendo real, nunca cacheada a ciegas."""
        if etapa_a_reanudar == "esperando_servicio":
            # A diferencia de las demás ramas, aquí el paciente TODAVÍA
            # no había elegido servicio (`servicio_elegido` no está en
            # `datos`) — saltar directo a `_ofrecer_fechas` usaría el
            # default equivocado (`self._activity.service`, ej. "medicina
            # general") en vez de volver a preguntar. Mismo catálogo real
            # que ya se le mostró antes de esta interrupción.
            return self._ofrecer_catalogo_servicios(datos)
        if etapa_a_reanudar == "esperando_fecha":
            return self._ofrecer_fechas(datos)
        if etapa_a_reanudar == "esperando_horario":
            return self._ofrecer_horarios(datos)
        if etapa_a_reanudar == "esperando_seleccion_reprogramacion":
            return self._iniciar_reprogramacion(datos)
        # "esperando_decision" (todavía no se había elegido nada) ->
        # mismo comportamiento de SIEMPRE (el único caso que existía
        # antes del recado 047): el siguiente paso natural es ofrecer
        # fechas reales para el servicio de la Activity.
        return self._ofrecer_fechas(datos)

    def _ofrecer_catalogo_servicios(self, datos: Dict[str, Any]) -> BrainOutput:
        """Extraído de `_interpretar_decision` (recado 047) para
        reutilizarlo también desde `_reanudar_tras_interrupcion` — mismo
        catálogo REAL, nunca inventado, mismo texto."""
        listar = getattr(self._appointment_service, "list_services", None)
        servicios = listar() if listar else []
        if servicios:
            texto_servicios = ", ".join(servicios)
            respuesta = (
                f"Claro, estos son los servicios que tenemos disponibles: {texto_servicios}. "
                "¿Para cuál te gustaría agendar?"
            )
            nuevos = {**datos, "etapa": "esperando_servicio"}
        else:
            respuesta = (
                "Por ahora no tengo el catálogo de servicios a la mano — "
                "¿me cuentas qué tipo de atención necesitas?"
            )
            nuevos = datos
        return BrainOutput(
            senales_detectadas=["consulta_catalogo_servicios"],
            respuesta_propuesta=respuesta,
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _interpretar_decision(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        # Pregunta por el catálogo de servicios, sin nombrar uno
        # específico (recado 027) — se responde con el catálogo REAL
        # (`AppointmentService.list_services()`, duck-typed, nunca
        # inventado). Transiciona a "esperando_servicio" (recado 031,
        # bug real corregido: antes se quedaba en "esperando_decision"
        # y una respuesta nombrando un servicio real, ej. "Medicina
        # general", no coincidía con NINGÚN patrón de esa etapa —
        # terminaba cayendo al fallback genérico de sí/no, como si el
        # paciente no hubiera dicho nada útil) — así la respuesta
        # siguiente se interpreta con `_interpretar_servicio`, el mismo
        # mecanismo que ya usa `gateway.py:_resolver_programar_cita`.
        # Sin catálogo disponible, no hay nada que desambiguar — se
        # queda en la misma etapa, sin cambios.
        if _contains_any_sin_tildes(texto, _CONSULTAR_SERVICIOS):
            return self._ofrecer_catalogo_servicios(datos)

        # Nota (recado 047): la rama de "gestión para beneficiario"
        # (`_PARA_OTRO`) que antes vivía aquí se movió a
        # `_detectar_interrupcion_de_contexto`, llamada desde `interpret()`
        # ANTES de que este método se ejecute — cubre esta etapa
        # igual que antes, y ahora también cualquier otra.

        # Chequeo genérico de "sí"/"no" — DESPUÉS de todas las ramas
        # específicas de arriba (ver comentario de orden al inicio de
        # este método). `_es_negativo` reconoce "no" como palabra suelta
        # en cualquier posición (recado 030) — más amplio que antes a
        # propósito, para no repetir el bug real de "Si claro ayúdame..."
        # (ver `_RE_PALABRA_SI`/`_RE_PALABRA_NO`), aceptando el costo
        # conocido de un falso positivo ocasional (ej. "no sé si quiero")
        # — límite estructural documentado en el recado 030, no resuelto
        # del todo sin NLU real (ver `.ai/RISKS.md` R-13).
        if _es_negativo(texto):
            nuevos = {**datos, "etapa": "finalizada", "decision": "DECLINED"}
            # Nombre real (recado 034) — momento natural de despedida.
            nombre = (self._activity.patient_contact or {}).get("nombre")
            despedida = (
                f"Entiendo perfectamente, {nombre} — gracias por tu tiempo."
                if nombre
                else "Entiendo perfectamente, gracias por tu tiempo."
            )
            return BrainOutput(
                senales_detectadas=["paciente_declina"],
                respuesta_propuesta=f"{despedida} Si más adelante cambias de opinión, aquí voy a estar.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _es_afirmativo(texto):
            return self._ofrecer_fechas(datos)

        # Saludo simple (recado 030) — no dispara ninguna transición de
        # estado nueva, solo reconoce que el paciente escribió algo
        # antes de repetir la pregunta pendiente, para que no se sienta
        # ignorado si saluda a mitad de la conversación.
        saludo = "¡Hola! " if _es_saludo(texto) else ""

        # Redacción deliberadamente NO fija/memorizada (recado 027) y
        # ahora explícita sobre que la respuesta no se entendió como
        # sí/no (recado 030, pedido explícito: no repetir la pregunta
        # original sin ningún reconocimiento de que el paciente intentó
        # decir algo). Sigue siendo la MISMA pregunta cerrada de sí/no
        # (ninguna garantía ni guardrail cambia). Ahora además ROTA
        # entre variantes (recado 034) — dos fallbacks seguidos en la
        # misma conversación no repiten literalmente la misma frase.
        variante, nuevos = _elegir_variante(_VARIANTES_ACLARACION_SI_NO, datos, "intentos_aclaracion_si_no")
        return BrainOutput(
            respuesta_propuesta=f"{saludo}{variante}",
            proxima_accion_propuesta="preguntar_intencion",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _interpretar_servicio(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Segundo turno del flujo "preguntar servicio primero" (recado
        030) — solo se llega aquí cuando `gateway.py:_resolver_programar_cita`
        detectó un catálogo real con MÁS DE UN servicio y, a propósito,
        no asumió ninguno (ver `_determinar_servicio_inicial`). Match
        por nombre real EXACTO/substring contra `list_services()`
        (nunca inventa ni asume el primero de la lista si el paciente no
        fue claro) — comparación sin tildes (recado 030, mismo criterio
        que `_CONSULTAR_SERVICIOS`), para que "odontologia" reconozca
        "Odontología" del catálogo real. Si no hay match exacto, se
        intenta con tolerancia a errores de tipeo (recado 036,
        `_emparejar_servicio_por_similitud`) antes de rendirse al
        fallback — nunca inventa un servicio que no exista en el
        catálogo real, y nunca elige por el paciente si el texto es
        ambiguo entre dos o más servicios reales."""
        listar = getattr(self._appointment_service, "list_services", None)
        servicios = listar() if listar else []
        normalizado = _sin_tildes(texto)
        elegido = next((s for s in servicios if _sin_tildes(s.lower()) in normalizado), None)
        candidatos_ambiguos: List[str] = []
        if elegido is None and servicios:
            # Match exacto/substring (arriba) no encontró nada — antes
            # de rendirse al fallback genérico, se intenta con
            # tolerancia a errores de tipeo (recado 036). Nunca al
            # revés: el match exacto sigue siendo siempre la primera
            # opción, más barato y sin ningún riesgo de falso positivo.
            elegido, candidatos_ambiguos = _emparejar_servicio_por_similitud(texto, servicios)
        if elegido is None:
            nuevos = datos
            if candidatos_ambiguos:
                texto_candidatos = ", ".join(candidatos_ambiguos)
                variante, nuevos = _elegir_variante(
                    _VARIANTES_SERVICIO_AMBIGUO, datos, "intentos_aclaracion_servicio_ambiguo"
                )
                respuesta = variante.format(opciones=texto_candidatos)
            elif servicios:
                texto_servicios = ", ".join(servicios)
                variante, nuevos = _elegir_variante(
                    _VARIANTES_SERVICIO_NO_IDENTIFICADO, datos, "intentos_aclaracion_servicio"
                )
                respuesta = variante.format(opciones=texto_servicios)
            else:
                respuesta = "Por ahora no tengo el catálogo de servicios a la mano — ¿me cuentas qué tipo de atención necesitas?"
            return BrainOutput(
                respuesta_propuesta=respuesta,
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {**datos, "servicio_elegido": elegido}
        return self._ofrecer_fechas(nuevos)

    # ------------------------------------------------------------------
    # Asistente de reserva EN ETAPAS (recado 035, pedido explícito del
    # usuario): antes, una sola lista combinaba fecha+hora+consultorio
    # en un bloque ("1) 2026-09-07 07:00 en Consultorio 2"). Ahora son 3
    # pasos secuenciales — servicio (ya resuelto al llegar acá) -> fecha
    # -> horario — cada uno una lista de una sola cosa por línea, y cada
    # uno consulta disponibilidad REAL (nunca inventada). Reemplaza a
    # `_ofrecer_disponibilidad`/`_interpretar_seleccion` (recados 013 y
    # 027) — mismos llamadores (rama `_ACEPTA` del camino outbound,
    # confirmación de beneficiario, `_interpretar_servicio`).
    # ------------------------------------------------------------------
    def _ofrecer_fechas(self, datos: Dict[str, Any]) -> BrainOutput:
        """PASO 2 — fechas reales con disponibilidad para el servicio ya
        resuelto (`datos.get("servicio_elegido")`, o
        `self._activity.service` para el camino outbound donde ya viene
        fijo — mismo criterio y misma razón que `_ofrecer_disponibilidad`
        tenía antes: nunca "medicina general" a ciegas, recados 027/030).
        Nunca horarios todavía — ese es el PASO 3 (`_ofrecer_horarios`)."""
        servicio = datos.get("servicio_elegido") or self._activity.service or "medicina general"
        opciones = self._appointment_service.get_availability(servicio)
        if not opciones:
            # NUNCA "te contactamos" (recado 026, hallazgo real de
            # producción): esa frase está en `guardrails/rules.py:
            # _PROMESAS_PROHIBIDAS` (lección de Dani, 002) y
            # `NoPrometerContactoGuardrail` la reescribe en silencio por
            # el mensaje genérico de escalamiento — el paciente termina
            # leyendo "voy a registrar tu caso... no puedo garantizar
            # contacto" en vez de la razón real (sin turnos disponibles
            # AHORA), sin que se haya escalado nada de verdad
            # (`necesidad_de_escalar` nunca se puso en True aquí).
            return BrainOutput(
                respuesta_propuesta=(
                    "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio. "
                    "Escríbeme más tarde y lo revisamos de nuevo con gusto."
                ),
                propuesta_de_actualizacion_de_estado={"datos_recopilados": {**datos, "etapa": "finalizada"}},
            )
        # Fechas REALES únicas, ordenadas — nunca más de 3 (mismo tope
        # que el resto del archivo, y `_elegir_opcion` solo reconoce
        # ordinales 1ª/2ª/3ª: mostrar más de las que se pueden elegir
        # sería un bug nuevo, no una mejora).
        fechas = sorted({o.date for o in opciones})[:3]
        nuevos = {
            **datos,
            "etapa": "esperando_fecha",
            "servicio_elegido": servicio,
            "fechas_ofrecidas": fechas,
        }
        texto_fechas = "; ".join(f"{i+1}) {_formatear_fecha_humana(f)}" for i, f in enumerate(fechas))
        return BrainOutput(
            respuesta_propuesta=f"Estas son las fechas disponibles: {texto_fechas}. ¿Cuál te queda mejor?",
            # "preguntar_dato_faltante" (no "ejecutar_tool"): todavía
            # falta que el paciente elija fecha y horario antes de
            # reservar — la tool que se ejecuta aquí es de lectura
            # (get_availability), no la acción final.
            proxima_accion_propuesta="preguntar_dato_faltante",
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_fecha(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """PASO 2 (respuesta) — el paciente elige una de las fechas ya
        ofrecidas (ordinal, mismo mecanismo que el resto del archivo,
        `_elegir_opcion`). Nunca inventa ni asume la primera si no fue
        claro."""
        fechas = datos.get("fechas_ofrecidas", [])
        elegida = self._elegir_opcion(texto, fechas)
        if elegida is None:
            variante, nuevos = _elegir_variante(
                _VARIANTES_FECHA_NO_IDENTIFICADA, datos, "intentos_aclaracion_fecha"
            )
            return BrainOutput(
                respuesta_propuesta=variante,
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {**datos, "fecha_elegida": elegida}
        return self._ofrecer_horarios(nuevos)

    def _ofrecer_horarios(self, datos: Dict[str, Any]) -> BrainOutput:
        """PASO 3 — horarios reales para el servicio Y la fecha ya
        elegidos, uno por línea (nunca combinado con la fecha, que ya
        se confirmó en el paso anterior)."""
        servicio = datos["servicio_elegido"]
        fecha = datos["fecha_elegida"]
        opciones = [o for o in self._appointment_service.get_availability(servicio) if o.date == fecha][:3]
        if not opciones:
            # Caso raro (condición de carrera real: alguien más reservó
            # el último cupo de esa fecha entre el PASO 2 y esta
            # respuesta) — nunca se inventa un horario; se vuelve al
            # PASO 2 con disponibilidad fresca en vez de dejar al
            # paciente sin ninguna salida.
            return self._ofrecer_fechas({**datos, "etapa": "esperando_fecha"})
        nuevos = {
            **datos,
            "etapa": "esperando_horario",
            "opciones_horario": [o.slot_id for o in opciones],
        }
        texto_horarios = "; ".join(f"{i+1}) {o.time} en {o.location}" for i, o in enumerate(opciones))
        fecha_legible = _formatear_fecha_humana(fecha)
        return BrainOutput(
            respuesta_propuesta=(
                f"Para el {fecha_legible}, estos son los horarios disponibles: {texto_horarios}. "
                "¿Cuál prefieres?"
            ),
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_horario(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """PASO 3 (respuesta) — el paciente elige un horario real de los
        ya ofrecidos para la fecha confirmada; resuelve directo al
        `slot_id` real y dispara la reserva. Reemplaza a
        `_interpretar_seleccion` (recados 013/027) — misma lógica de
        reserva (beneficiario, nombre, idempotencia), solo que el
        `slot_id` ya viene acotado a servicio+fecha, no a una lista
        combinada."""
        opciones = datos.get("opciones_horario", [])
        elegida = self._elegir_opcion(texto, opciones)
        if elegida is None:
            variante, nuevos = _elegir_variante(
                _VARIANTES_SELECCION_NO_IDENTIFICADA, datos, "intentos_aclaracion_seleccion"
            )
            return BrainOutput(
                respuesta_propuesta=variante,
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {**datos, "etapa": "reservando", "slot_seleccionado": elegida}
        # Recado 013: si el titular declaró y confirmó un beneficiario,
        # la reserva se hace a nombre del BENEFICIARIO, nunca del
        # titular del canal (requisito #3) — `self._activity.patient_reference`
        # solo se usa cuando no hay beneficiario (comportamiento por
        # defecto, requisito #5, sin cambios frente a antes de esta extensión).
        patient_reference_reserva = datos.get("beneficiario_documento") or self._activity.patient_reference
        # Nombre real (recado 034) — "momento natural" para usarlo, sin
        # repetirlo también en el mensaje de confirmación que
        # `agent.py` concatena a continuación (evita sobreusarlo).
        nombre = (self._activity.patient_contact or {}).get("nombre")
        apertura = f"¡Perfecto, {nombre}!" if nombre else "¡Perfecto!"
        return BrainOutput(
            respuesta_propuesta=f"{apertura} Dame un segundo, voy a dejarlo reservado.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "book_appointment",
                "params": {
                    "slot_id": elegida,
                    "patient_reference": patient_reference_reserva,
                    "idempotency_key": f"{self._activity.activity_id}:booking",
                },
            },
            # Recado 037, Parte 3: confirmación determinista ya ocurrió
            # arriba (`_elegir_opcion` matcheó un ordinal real de una
            # lista real) — nunca la interpretación libre de un LLM.
            confirmacion_estructurada_para_write=True,
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _interpretar_documento_beneficiario(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Segundo paso del flujo de beneficiario (recado 013): valida
        el documento contra `buscar_paciente` (mismo endpoint público
        009, GET /citas/buscar-paciente) ANTES de aceptar el nombre —
        nunca inventa ni continúa si no hay match real."""
        documento = texto.strip()
        buscar = getattr(self._appointment_service, "buscar_paciente", None)
        identidad = buscar(documento) if buscar and documento else None
        if identidad is None:
            return BrainOutput(
                respuesta_propuesta=(
                    "No encontré ningún paciente registrado con ese documento — "
                    "¿puedes revisarlo y escribírmelo de nuevo?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )
        nombre = identidad.get("nombre_paciente") or "esa persona"
        nuevos = {
            **datos,
            "etapa": "esperando_confirmacion_beneficiario",
            "beneficiario_documento_candidato": documento,
            "beneficiario_nombre_candidato": nombre,
        }
        return BrainOutput(
            senales_detectadas=["beneficiario_encontrado"],
            respuesta_propuesta=f"Perfecto, vamos a agendar para {nombre} — ¿es correcto?",
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_confirmacion_beneficiario(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Tercer paso: el titular confirma explícitamente el nombre
        antes de continuar (requisito #2, "para que el titular confirme
        explícitamente... antes de continuar") — cualquier respuesta que
        no sea una aceptación clara vuelve a pedir el documento, nunca
        asume un "sí" implícito."""
        if not _es_afirmativo(texto):
            nuevos = {**datos, "etapa": "esperando_documento_beneficiario"}
            return BrainOutput(
                respuesta_propuesta=(
                    "Entendido, ¿me confirmas cuál es el documento correcto de la "
                    "persona para quien es la cita?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nombre_beneficiario = datos["beneficiario_nombre_candidato"]
        nuevos = {
            **datos,
            "beneficiario_documento": datos["beneficiario_documento_candidato"],
            "beneficiario_nombre": nombre_beneficiario,
        }
        # Recado 047 — antes esto SIEMPRE llamaba a `_ofrecer_fechas`
        # directo, correcto solo porque `_PARA_OTRO` únicamente podía
        # dispararse desde "esperando_decision" (el único punto de
        # entrada de ese momento). Ahora que la interrupción puede venir
        # de CUALQUIER etapa (`_detectar_interrupcion_de_contexto` guarda
        # de dónde en `etapa_antes_de_beneficiario`, mismo patrón que
        # `etapa_antes_de_olvido`), hay que retomar el punto real donde
        # el paciente iba — nunca reiniciar el flujo ni perder lo ya
        # elegido (`servicio_elegido`/`fecha_elegida`, todavía en `datos`).
        etapa_a_reanudar = datos.get("etapa_antes_de_beneficiario", "esperando_decision")
        salida = self._reanudar_tras_interrupcion(etapa_a_reanudar, nuevos)
        # `model_copy(update=...)` (no reconstruir a mano): preserva
        # TODOS los campos de `salida` (incl. `verificaciones_de_datos`/
        # `texto_base_para_comparacion`, recado 037/039) — solo se
        # antepone el reconocimiento del beneficiario al texto real.
        return salida.model_copy(
            update={
                "respuesta_propuesta": f"¡Listo, quedó registrado para {nombre_beneficiario}! {salida.respuesta_propuesta}",
            }
        )

    # ------------------------------------------------------------------
    # `_elegir_opcion` sigue aquí sin cambios — la reutiliza también
    # `_interpretar_seleccion_reprogramacion` (reprogramar una cita YA
    # existente sigue con la lista combinada de antes; el asistente en
    # etapas del recado 035 es específicamente para RESERVAR una cita
    # nueva, alcance explícito del pedido — reprogramar no se tocó).
    def _elegir_opcion(self, texto: str, opciones: List[str]) -> Optional[str]:
        mapa_ordinal = {"1": 0, "primera": 0, "2": 1, "segunda": 1, "3": 2, "tercera": 2}
        for clave, indice in mapa_ordinal.items():
            if clave in texto and indice < len(opciones):
                return opciones[indice]
        return None

    # ------------------------------------------------------------------
    def _iniciar_reprogramacion(self, datos: Dict[str, Any]) -> BrainOutput:
        servicio = self._activity.service or "medicina general"
        opciones = self._appointment_service.get_availability(servicio)[:3]
        nuevos = {
            **datos,
            "etapa": "esperando_seleccion_reprogramacion",
            "opciones_reprogramacion": [o.slot_id for o in opciones],
        }
        if not opciones:
            # Ver comentario equivalente en `_ofrecer_disponibilidad`
            # (recado 026) — misma razón, nunca "te contactamos".
            return BrainOutput(
                senales_detectadas=["reprogramacion_solicitada"],
                respuesta_propuesta=(
                    "Lamento decirte que por ahora no tengo otros horarios disponibles para ese servicio. "
                    "Escríbeme más tarde y lo revisamos de nuevo con gusto."
                ),
                propuesta_de_actualizacion_de_estado={"datos_recopilados": {**datos, "etapa": "finalizada"}},
            )
        texto_opciones = "; ".join(
            f"{i+1}) {o.date} {o.time} en {o.location}" for i, o in enumerate(opciones)
        )
        return BrainOutput(
            senales_detectadas=["reprogramacion_solicitada"],
            respuesta_propuesta=f"Claro que sí, aquí tienes otras opciones: {texto_opciones}. ¿Cuál te queda mejor?",
            proxima_accion_propuesta="preguntar_dato_faltante",  # ver comentario equivalente arriba
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_seleccion_reprogramacion(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        opciones = datos.get("opciones_reprogramacion", [])
        elegida = self._elegir_opcion(texto, opciones)
        if elegida is None:
            return BrainOutput(
                respuesta_propuesta="¿Me confirmas cuál opción prefieres — la 1, la 2 o la 3?",
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )
        nuevos = {**datos, "etapa": "reprogramando"}
        return BrainOutput(
            respuesta_propuesta="Listo, voy a reprogramar tu cita — dame un momento.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "reschedule_appointment",
                "params": {
                    "appointment_id": self._activity.appointment_id,
                    "new_slot_id": elegida,
                    "idempotency_key": f"{self._activity.activity_id}:reschedule:{elegida}",
                },
            },
            # Recado 037, Parte 3: ordinal real matcheado arriba —
            # confirmación determinista, nunca interpretación libre.
            confirmacion_estructurada_para_write=True,
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _cancelar(self, datos: Dict[str, Any]) -> BrainOutput:
        nuevos = {**datos, "etapa": "cancelando"}
        return BrainOutput(
            senales_detectadas=["cancelacion_solicitada"],
            respuesta_propuesta="Entendido, voy a cancelar tu cita ahora mismo.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "cancel_appointment",
                "params": {"appointment_id": self._activity.appointment_id},
            },
            # Recado 037, Parte 3: `_CANCELAR` ya exigió una frase
            # imperativa exacta ("cancela mi cita", etc. — código
            # determinista, nunca interpretación libre). Alcanzable
            # SOLO con MockAppointmentService — el paciente real nunca
            # llega aquí, siempre pasa por el sub-flujo real de código
            # de verificación (gateway.py:_procesar_intento_de_codigo,
            # fuera del Core/Orchestrator, ver recado 037). Documentado
            # como diferencia deliberada frente al patrón "ordinal
            # elegido" del resto de este archivo, no un descuido.
            confirmacion_estructurada_para_write=True,
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    # Olvido de identidad de canal (recado 016, extensión de R-20).
    # Wizard de 2 pasos, análogo en espíritu al de beneficiario (013)
    # pero deliberadamente SIN tocar ninguno de sus campos/etapas
    # (requisito #5: no debe interferir con la gestión de beneficiario).
    # Nunca propone `tool_requerida`: el borrado real no es una tool del
    # Protocol `AppointmentService` — lo ejecuta `gateway.py` (que sí
    # tiene acceso a `identity_store`) al ver `etapa == "olvido_confirmado"`,
    # ver `_procesar_olvido_si_corresponde`. Este Brain solo PROPONE.
    # ------------------------------------------------------------------
    def _iniciar_olvido(self, datos: Dict[str, Any], etapa_anterior: str) -> BrainOutput:
        nuevos = {**datos, "etapa": "confirmando_olvido", "etapa_antes_de_olvido": etapa_anterior}
        return BrainOutput(
            senales_detectadas=["olvido_de_identidad_solicitado"],
            respuesta_propuesta=(
                "Entendido — ¿confirmas que quieres que olvide tu número? "
                "Ten en cuenta que vas a tener que verificarte de nuevo la próxima vez que escribas."
            ),
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_confirmacion_olvido(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Solo una aceptación CLARA (mismo vocabulario `_ACEPTA` ya
        usado en el resto de este archivo) confirma el borrado —
        cualquier otra respuesta (declina, ambigua, otro tema) cancela
        la solicitud SIN borrar nada (requisito #3: "nunca borres sin
        una confirmación clara") y restaura la etapa en la que estaba
        el paciente antes de pedir el olvido, para no perder su lugar
        en la conversación."""
        etapa_anterior = datos.get("etapa_antes_de_olvido", "esperando_decision")
        if not _es_afirmativo(texto):
            nuevos = {k: v for k, v in datos.items() if k != "etapa_antes_de_olvido"}
            nuevos["etapa"] = etapa_anterior
            return BrainOutput(
                senales_detectadas=["olvido_de_identidad_cancelado"],
                respuesta_propuesta="Entendido, no voy a borrar nada — sigamos. ¿En qué más te ayudo?",
                # "preguntar_dato_faltante" (no "preguntar_intencion"): la
                # etapa restaurada puede venir de una fase_actual distinta
                # de IDENTIFICACION_DE_INTENCION (ej. RECOPILACION_DE_DATOS,
                # si el olvido se pidió a mitad de "esperando_seleccion")
                # — "preguntar_intencion" solo es una transición VÁLIDA
                # desde ciertas fases (state/machine.py:VALID_TRANSITIONS),
                # y usarla aquí sin condición disparaba una escalación real
                # por "error de transición" (bug encontrado con un test de
                # esta misma extensión, recado 016). "preguntar_dato_faltante"
                # es válida desde cualquier fase donde este wizard puede
                # interrumpirse.
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {k: v for k, v in datos.items() if k != "etapa_antes_de_olvido"}
        nuevos["etapa"] = "olvido_confirmado"
        return BrainOutput(
            senales_detectadas=["olvido_de_identidad_confirmado"],
            respuesta_propuesta="Listo, olvidé tu número — la próxima vez tendrás que verificarte de nuevo.",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )
