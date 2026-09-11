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
from core.selection import SelectionOption, SelectionProposer, interpret_selection
from guardrails.base import VerificacionDeSeleccion
from memory.conversation_memory import Turn
from state.models import ConversationState

from .appointment_service import AppointmentService
from .institutional_info import INFORMACION_HOSPITAL, InformacionInstitucional
from .models import respuesta_pregunta_sobre_correo

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
# Recado 064 (segunda parte) — dos preguntas reales sobre el HOSPITAL
# en sí (no sobre el trámite de la cita) que ninguna categoría existente
# cubría: "¿dónde queda?" (ubicación) y "¿son buenos?" (calidad de
# atención) — ambas caían, sin esto, a la interpretación de la etapa
# activa (ej. `_interpretar_fecha` tratándolas como un intento fallido
# de elegir fecha), perdiendo la pregunta real del paciente.
#
# Recado 066 — ampliada con preguntas directas de contacto ("cuál es el
# teléfono", "tienen correo"): ahora que SÍ hay teléfono/correo reales
# (`institutional_info.py`), es la misma categoría de "información de
# contacto/ubicación del hospital" — una pregunta directa por el
# teléfono no merece una lista de palabras clave nueva y paralela.
_PREGUNTA_UBICACION_HOSPITAL = (
    "donde queda", "donde esta ubicado", "donde esta el hospital", "cual es la direccion",
    "que direccion", "como llego", "donde es el hospital", "ubicacion del hospital",
    "cual es el telefono", "cual es su telefono", "tienen telefono", "numero de telefono",
    "tienen correo", "cual es el correo", "cual es su correo", "como los contacto",
    "como me comunico", "como puedo comunicarme",
)
_PREGUNTA_CALIDAD_ATENCION = (
    "son buenos", "es bueno el hospital", "buena atencion", "que tal la atencion",
    "vale la pena", "es recomendable", "recomiendan el hospital", "atienden bien",
)


def _texto_informacion_hospital(info: InformacionInstitucional) -> str:
    """Recado 066 — arma el texto de contacto/ubicación institucional
    ÚNICAMENTE a partir de `INFORMACION_HOSPITAL` (`institutional_info.py`,
    fuente única de verdad) — ningún valor se escribe a mano acá.
    Extensible sin duplicar lógica (requisito explícito del pedido): si
    `direccion` todavía no está confirmada (`None`), el texto lo dice
    honestamente en vez de inventarla; en cuanto se confirma (como ya
    ocurrió en este mismo pedido), esta MISMA función la incluye
    automáticamente — ningún llamador necesita cambiar."""
    if info.direccion:
        return (
            f"Estamos ubicados en {info.direccion}. Si necesitas más detalles, también puedes "
            f"llamarnos al {info.telefono_citas} o escribirnos a {info.correo_citas}."
        )
    return (
        f"No tengo una dirección exacta registrada en este canal, pero puedes llamarnos al "
        f"{info.telefono_citas} o escribirnos a {info.correo_citas} para confirmarla."
    )


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
# Recado 053, Parte 2 — "consultar mis citas" (la opción 4 del menú
# institucional, recado 046) solo se reconocía como enrutamiento de
# PRIMER contacto (`gateway.py:_interpretar_opcion_menu`/`classify_
# intent`) — nunca dentro de `HealthBrain`, así que un paciente que lo
# escribiera a mitad de OTRO flujo (ej. atascado en "esperando_servicio")
# nunca lo veía reconocido, quedando en loop pidiéndole el servicio de
# nuevo (hallazgo real de producción). Mismo vocabulario que
# `intent.py:_CONSULTAR` (deliberadamente duplicado entre capas, mismo
# criterio ya documentado para `_SALUDOS`/`_INFORMACION` en este
# archivo) — duck-typed sobre `appointment_service.get_patient_
# appointments`, igual que `buscar_paciente`/`list_services`.
_CONSULTA_CITAS_EXISTENTES = (
    "consultar mi cita", "consultar mis citas", "qué cita tengo", "que cita tengo",
    "cuándo es mi cita", "cuando es mi cita", "tengo alguna cita", "mis citas",
    # Recado 062 — hallazgo real dentro del wizard de código de
    # verificación (gateway.py): forma real usada por un paciente,
    # ninguna variante existente la cubría ni siquiera sin errores de
    # tipeo.
    "cuales tengo reservadas", "qué tengo reservado", "que tengo reservado",
)
# Recado 058 — hallazgo real de producción: tras una reserva exitosa
# ("...Te enviamos un correo de confirmación con todos los detalles."),
# el paciente preguntó "confirmame si me enviastes el email" — el
# sistema no lo reconoció como una pregunta sobre la acción recién
# hecha y cayó al saludo corto (recado 057) + directo a preguntar
# servicio, arrancando una reserva nueva sin que el paciente la
# pidiera. Incluye la variante real "enviastes" (typo coloquial común
# en español, sin conjugación correcta) además de la forma correcta
# "enviaste" — mismo criterio de palabras clave del resto del archivo.
_PREGUNTA_SOBRE_CORREO_ENVIADO = (
    "me enviaste el correo", "me enviastes el correo", "me enviaste el email", "me enviastes el email",
    "enviaste el correo", "enviastes el correo", "enviaste el email", "enviastes el email",
    "llego el correo", "llego el email", "me llego el correo", "me llego el email", "me llego el mail",
    "recibi el correo", "recibi el email",
    "confirmame si me enviaste", "confirmame si me enviastes", "confirmame si me llego",
)
# Recado 058 — hallazgo real de producción: "no gracias ya termine"
# (una despedida real y clara) se interpretó como un intento de nombrar
# un servicio, quedando atascado pidiendo "el nombre tal como aparece
# en la lista". Frases deliberadamente de 3+ palabras (nunca solas como
# "gracias" o "listo") para evitar falsos positivos sobre un mensaje
# que solo agradece de paso sin querer cerrar la conversación. Se
# compara sobre texto SIN puntuación (`_es_despedida`, abajo) — a
# diferencia del resto de las listas de este archivo, una despedida
# real casi siempre trae comas ("no gracias, ya terminé").
#
# Ampliada (mensaje urgente posterior al 058, transcripción real de
# 6+ turnos): "chao"/"chau"/"adios" SÍ se agregan como palabras SUELTAS
# (únicas excepciones a la regla de "3+ palabras" de arriba) — a
# diferencia de "gracias"/"listo", una despedida coloquial en español
# no necesita ningún acompañamiento para ser inequívoca ("Chao" solo,
# como mensaje completo, es 100% una despedida real, nunca un typo de
# otra cosa). Deliberadamente NO se agrega "salir"/"terminar" sueltos
# acá: esos SÍ tienen falsos positivos reales dentro de una conversación
# en curso ("quiero terminar de agendar" significa seguir, no cerrar) —
# esas dos palabras se reconocen en cambio SOLO como la 5ta opción del
# menú (`_MENU_OPCIONES`/`_interpretar_opcion_menu` en gateway.py), un
# contexto sin esa ambigüedad. "q(ue) tengas buen(a) ..." (día/tarde/
# noche) es una construcción de despedida distinta que ninguna frase
# anterior cubría — se agrega en ambas variantes (con/sin la abreviatura
# real "q" en vez de "que", typo coloquial de Telegram, mismo criterio
# que "enviastes" arriba).
_DESPEDIDA = (
    "no gracias ya termine", "ya termine", "eso es todo", "eso seria todo", "eso seria todo gracias",
    "nada mas por ahora", "nada mas gracias", "listo gracias", "listo asi esta bien", "asi esta bien",
    "no necesito nada mas", "ya no necesito mas", "gracias ya no necesito mas",
    "muchas gracias eso es todo", "eso es todo gracias", "eso era todo",
    "chao", "chau", "adios",
    "que tengas buen", "q tengas buen",
)
_RE_PUNTUACION_DESPEDIDA = re.compile(r"[¡!¿?.,;:]")

# Recado 069 — hallazgo real GRAVE, confirmado con evidencia exacta tras
# 2 rondas previas de fixes (recados 057/067) que NO lo cubrían: un
# "gracias" SOLO (sin ningún acompañamiento — no "no gracias ya
# termine", solo "gracias"), "no gracias" solo, o "que descanses" solo,
# NUNCA coincidían con `_DESPEDIDA` (arriba, exige frases de 3+
# palabras salvo "chao"/"chau"/"adios"/"q(ue) tengas buen...") — el
# paciente que se despedía con una de estas formas MUY comunes en
# español coloquial nunca activaba ninguna categoría de cierre, y
# `_enrutar_solicitud_nueva`/`_interpretar_*` lo trataban como mensaje
# ambiguo sin intención, mostrando el MENÚ INSTITUCIONAL COMPLETO —
# exactamente lo que el paciente real reportó ("la despedida sigue sin
# funcionar").
#
# Mismo mecanismo YA probado y en producción para el caso simétrico de
# saludos (`intent.py:_es_solo_saludo`, recado 048), pero por TOKEN en
# vez de frase fija — un paciente real combina estas palabras en
# cualquier orden ("no ya gracias", "ya no gracias", "gracias ya"), y
# una lista de frases fijas nunca cubre todas las combinaciones.
# CADA palabra del mensaje debe estar en `_PALABRAS_DE_CIERRE_SUELTAS`
# (sin excepción — basta una palabra de contenido real para que NO
# coincida: "gracias, ¿a qué hora es la cita?" nunca coincide, "a que
# hora es la cita" no está en el conjunto). Además, al menos una
# palabra debe ser una "ancla" inequívoca (`_ANCLAS_DE_CIERRE`) —
# "no"/"ya"/"que" SUELTOS, sin ninguna ancla, NO cuentan como despedida
# (demasiado ambiguos por sí solos — "no" ya tiene manejo específico
# propio como declinación en varias etapas, `_es_negativo`; "ya"/"que"
# son rellenos, nunca despedidas por sí mismos).
_ANCLAS_DE_CIERRE = frozenset({"gracias", "descanses", "chao", "chau", "adios", "bye", "listo", "vemos"})
_PALABRAS_DE_CIERRE_SUELTAS = _ANCLAS_DE_CIERRE | {"no", "ya", "muchas", "que", "q", "hasta", "luego", "pronto", "nos"}


def _es_solo_despedida(texto_sin_tildes_y_puntuacion: str) -> bool:
    palabras = texto_sin_tildes_y_puntuacion.split()
    if not palabras:
        return False
    if not all(p in _PALABRAS_DE_CIERRE_SUELTAS for p in palabras):
        return False
    return any(p in _ANCLAS_DE_CIERRE for p in palabras)


# Recado 067 — hallazgo real: "salir"/"exit" (recados 062/063, MISMA
# lista antes vivía SOLO en gateway.py, usada por los wizards
# independientes del Brain) NUNCA se reconocían dentro de una
# conversación YA ABIERTA (`_detectar_interrupcion_de_contexto`,
# cualquier etapa: esperando_servicio, esperando_fecha, esperando_horario,
# esperando_decision, esperando_seleccion_reprogramacion) — un paciente
# que escribiera "salir"/"exit" ahí caía al matching específico de esa
# etapa (ej. `_interpretar_servicio` intentando matchear "salir" como
# nombre de servicio), el mismo callejón sin salida ya corregido en los
# wizards. Causa raíz: `_DESPEDIDA` (arriba) EXCLUYE a propósito
# "salir"/"terminar" sueltos (recado 059 — "terminar" tiene falsos
# positivos reales, "quiero TERMINAR de agendar" significa seguir, no
# cerrar) — la única vía que SÍ reconocía "salir"/"exit" era
# `_MENU_OPCIONES` (gateway.py), inalcanzable una vez que hay una
# conversación abierta. Movida acá (antes solo en gateway.py) para que
# `_detectar_interrupcion_de_contexto` la reconozca también — misma
# lista, mismo criterio de coincidencia EXACTA (nunca fuzzy, mismo
# motivo ya documentado en gateway.py: una salida es irreversible sin
# confirmación adicional). Riesgo aceptado y documentado, no nuevo: como
# substring, "salir" podría matchear una frase no relacionada ("necesito
# salir temprano del trabajo, ¿tienen citas después de las 5?") — mismo
# trade-off que los wizards ya aceptaban; se ajusta con evidencia real
# si aparece un caso así, no antes.
_SOLICITUD_DE_SALIR = ("salir", "cancelar esto", "exit", "ya no quiero", "olvidalo", "detente")


def _es_solicitud_de_salir(texto: str) -> bool:
    return any(frase in texto.lower() for frase in _SOLICITUD_DE_SALIR)


def _es_despedida(texto: str) -> bool:
    """`_DESPEDIDA` compara sobre texto SIN puntuación — quita comas y
    signos ANTES de buscar, para que "no gracias, ya terminé" (coma
    real, natural en una despedida) siga matcheando "no gracias ya
    termine".

    Recado 069 — además de `_DESPEDIDA` (frases de 3+ palabras, salvo
    excepciones puntuales), reconoce el mensaje COMPLETO cuando consiste
    ÚNICAMENTE en palabras de cierre cortas ("gracias", "no gracias",
    "que descanses" solos — ver `_es_solo_despedida`) — antes invisibles,
    causa raíz confirmada del hallazgo real "la despedida sigue sin
    funcionar" tras 2 rondas previas de fixes que no lo cubrían."""
    limpio = _RE_PUNTUACION_DESPEDIDA.sub(" ", texto)
    limpio = " ".join(limpio.split())
    limpio_sin_tildes = _sin_tildes(limpio).lower()
    return _contains_any_sin_tildes(limpio, _DESPEDIDA) or _es_solo_despedida(limpio_sin_tildes)


# Extraído a su propia función (mensaje urgente posterior al 058) para
# que `gateway.py` pueda mostrar EXACTAMENTE la misma despedida cálida
# cuando el paciente sale por la 5ta opción del menú numerado (sin
# conversación abierta todavía, ver `_resolver_por_intent` en
# gateway.py) — una única fuente de verdad para el texto, en vez de
# copiarlo literal en dos archivos (mismo criterio de import ya
# establecido para `_lista_numerada`/`_formatear_fecha_humana`).
def _texto_despedida(nombre: Optional[str]) -> str:
    """Recado 069 — texto EXACTO pedido explícitamente por el usuario
    (recados 057/067 usaban una variante más informal, "Aquí estaré si
    necesitas algo más", que podía leerse como disponibilidad
    INMEDIATA — contradice el enfriamiento real de 2 minutos que sigue
    a este mensaje). Un solo mensaje limpio, cierre real: NUNCA la
    pregunta "¿puedo ayudarte en algo más?" antepuesta (`es_cierre`,
    `gateway.py:handle_inbound_message`), NUNCA el menú numerado. "En 2
    minutos" está sincronizado con el mecanismo real
    (`gateway.py:_VENTANA_ENFRIAMIENTO`) — nunca una promesa sin
    mecanismo detrás."""
    if nombre:
        return f"Fue un gusto atenderte, {nombre}. En 2 minutos estaremos disponibles nuevamente si necesitas algo más. ¡Hasta pronto!"
    return "Fue un gusto atenderte. En 2 minutos estaremos disponibles nuevamente si necesitas algo más. ¡Hasta pronto!"
# Recado 053, Parte 3 — pedido explícito del usuario: un mensaje
# emocional/personal real ("me deprime ir al médico", "estoy
# deprimido/a", "esto me tiene angustiada") NO es lo mismo que un typo o
# una palabra sin sentido — merece una respuesta breve de validación
# humana (nunca diagnóstico ni consejo, eso sigue fuera del propósito y
# de OpinionPersonalGuardrail, sin cambios) y volver al contexto de la
# conversación, en vez del fallback genérico de "no te entendí" que
# antes producía un loop real (ver `_responder_expresion_emocional`).
# Mismo criterio de palabras clave del resto del archivo — no NLU real
# (`.ai/RISKS.md` R-13). Deliberadamente SIN ninguna palabra de
# `core.brain.RISK_KEYWORDS_DEMO` ("urgente"/"emergencia"/"ayuda
# inmediata"/"muy grave") — esa detección de riesgo corre en el Core,
# ANTES e INDEPENDIENTE del Brain, y SIEMPRE tiene prioridad absoluta
# (`core/orchestrator.py:handle_message`, sección 6/7 del prompt
# maestro) — un mensaje de riesgo real jamás se trata como "solo
# emocional", sin importar el orden de chequeo aquí.
_EXPRESION_EMOCIONAL = (
    "me deprime", "me deprimo", "estoy deprimido", "estoy deprimida", "me siento deprimido", "me siento deprimida",
    "estoy triste", "me siento triste", "me pone triste",
    "me angustia", "esto me angustia", "estoy angustiado", "estoy angustiada", "me tiene angustiado", "me tiene angustiada",
    "me siento mal", "me siento muy mal", "no tengo ánimo", "no tengo animo", "estoy agotado", "estoy agotada",
    "me siento solo", "me siento sola", "esto me supera", "no doy más", "no doy mas",
)

# Recado 053, Parte 3 — recordatorio BREVE (nunca la presentación
# institucional completa, ni la lista completa de opciones de nuevo —
# solo la PREGUNTA, mismo criterio de brevedad pedido explícitamente)
# de qué se le había preguntado al paciente, usado para volver al
# contexto tras una expresión emocional/personal (`_responder_
# expresion_emocional`). Deliberadamente texto FIJO, corto, por etapa —
# no reconsulta disponibilidad real (a diferencia de `_reanudar_tras_
# interrupcion`, pensado para RETOMAR un flujo que sí cambió de estado;
# aquí nada cambió, solo se reconoce el mensaje y se repite la pregunta
# vigente).
_RECORDATORIO_BREVE_POR_ETAPA = {
    "esperando_decision": "Volviendo a lo de antes — ¿te gustaría que te ayude a agendar tu atención?",
    "esperando_servicio": "Volviendo a lo de antes — ¿me confirmas para cuál servicio te gustaría agendar?",
    "esperando_fecha": "Volviendo a lo de antes — ¿cuál de las fechas que te compartí te queda mejor?",
    "esperando_horario": "Volviendo a lo de antes — ¿cuál de los horarios que te compartí prefieres?",
    "esperando_seleccion_reprogramacion": "Volviendo a lo de antes — ¿cuál de esas opciones para reprogramar te queda mejor?",
}

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


def _es_expresion_emocional(texto: str) -> bool:
    return _contains_any_sin_tildes(texto, _EXPRESION_EMOCIONAL)


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
    "No logré identificar cuál de estos prefieres:\n{opciones}\n¿Me confirmas el nombre tal como aparece en la lista?",
    "Perdona, no reconocí cuál de estos servicios quieres:\n{opciones}\n¿Me lo repites tal cual aparece ahí?",
)
# Recado 070 — hallazgo real, confirmado en varias conversaciones de
# hoy: estas 2 variantes (a diferencia de TODAS las demás de este
# bloque, que ya llevan `{opciones}`) pedían "¿es la 1, la 2 o la 3?"
# SIN repetir la lista — el paciente tenía que recordar de memoria qué
# era cada número. Ahora incluyen `{opciones}`, mismo formato/criterio
# que el resto (número + dato real, nunca solo el número).
_VARIANTES_SELECCION_NO_IDENTIFICADA = (
    "No logré identificar cuál prefieres:\n{opciones}\n¿me confirmas si es la 1, la 2 o la 3?",
    "No estoy seguro de haber entendido cuál elegiste:\n{opciones}\n¿me dices si es la 1, la 2 o la 3?",
)
_VARIANTES_FECHA_NO_IDENTIFICADA = (
    "No logré identificar cuál fecha prefieres:\n{opciones}\n¿me confirmas si es la 1, la 2 o la 3?",
    "Perdona, no reconocí cuál de esas fechas elegiste:\n{opciones}\n¿me dices si es la 1, la 2 o la 3?",
)
# Ambigüedad genuina de servicio (recado 036) — el paciente escribió
# algo que se parece razonablemente a MÁS DE UN servicio real (ej.
# "pequiatria" entre "pediatria" y "psiquiatria"): nunca se elige por
# el paciente, se le muestran solo los candidatos cercanos encontrados
# (no el catálogo completo de nuevo, para reconocer que sí escribió
# algo reconocible).
_VARIANTES_SERVICIO_AMBIGUO = (
    "Creo que podrías referirte a más de uno de estos:\n{opciones}\n¿Cuál de los dos es el que necesitas?",
    "No quiero adivinar entre estos:\n{opciones}\n¿Me confirmas cuál de los dos prefieres?",
)
# Ambigüedad genuina de fecha/horario (recado 051, mismo criterio que
# `_VARIANTES_SERVICIO_AMBIGUO` arriba) — el paciente escribió un día de
# la semana o un número de día/hora que coincide con MÁS DE UNA de las
# opciones ofrecidas (ej. dos fechas ofrecidas caen el mismo día de la
# semana en semanas distintas). Nunca se elige por el paciente.
_VARIANTES_FECHA_AMBIGUA = (
    "Creo que podrías referirte a más de una de estas fechas:\n{opciones}\n¿Cuál de las dos prefieres?",
    "No quiero adivinar entre estas fechas:\n{opciones}\n¿Me confirmas cuál de las dos es?",
)
_VARIANTES_HORARIO_AMBIGUO = (
    "Creo que podrías referirte a más de uno de estos horarios:\n{opciones}\n¿Cuál de los dos prefieres?",
    "No quiero adivinar entre estos horarios:\n{opciones}\n¿Me confirmas cuál de los dos es?",
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


def _lista_numerada(items: List[str]) -> str:
    """Recado 054, pedido explícito del usuario: TODO listado que ZANTIA
    presenta al paciente se muestra como lista numerada, una opción por
    línea (salto de línea REAL) — nunca como texto corrido separado por
    comas/punto y coma. `items` ya viene formado con el texto final de
    cada opción (fecha humana, hora, nombre de servicio, etc. — esta
    función NUNCA decide qué contiene cada línea, solo la numera)."""
    return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))


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


# Reconocimiento flexible de fecha/horario (recado 051, pedido explícito
# del usuario, mismo principio que la tolerancia a errores de tipeo de
# servicio del recado 036): antes de esto, `_interpretar_fecha`/
# `_interpretar_horario` SOLO reconocían el ordinal de la opción
# ("1"/"primera") — un paciente real que repitiera la fecha/hora TAL
# CUAL se la mostraron ("7 de septiembre", "el lunes", "lunes 7", "7
# am") se quedaba sin poder avanzar (bug real confirmado en producción,
# ver recado 051). `_elegir_opcion` (el matching por ordinal) sigue
# intacto y se sigue probando SIEMPRE primero — estas funciones nuevas
# son un fallback adicional, nunca lo reemplazan.
#
# Mismo criterio de "palabras clave, no NLU real" que el resto del
# archivo (`.ai/RISKS.md` R-13): se arma un puñado de formas de texto
# aceptadas por CADA opción real ofrecida (nunca inventadas — siempre
# derivadas de la fecha/hora real que ya se le mostró al paciente) y se
# busca cuál(es) de las opciones ofrecidas coincide con el texto libre.
# Dos niveles de especificidad, del más seguro al más laxo — se detiene
# en el PRIMER nivel que produzca algún candidato (1 = match claro, 2+ =
# ambigüedad genuina, nunca se sigue probando niveles más laxos "por si
# acaso" una vez que un nivel ya produjo candidatos):
#   Nivel 1 (fecha): día del mes + (nombre del mes O día de la semana) —
#     cubre "7 de septiembre", "lunes 7", "lunes 7 de septiembre", "día
#     7 de septiembre". Estructuralmente casi imposible de ambigüar
#     entre las fechas realmente ofrecidas (nunca hay dos fechas reales
#     con el mismo día+mes).
#   Nivel 2 (fecha): día de la semana solo ("lunes") o día del mes solo
#     ("7", "el 7", "día 7") — más laxo, sí puede colisionar si dos
#     fechas ofrecidas cayeran el mismo día de semana o el mismo número
#     de día en meses distintos (raro con la ventana real de hoy, pero
#     posible con una ventana más larga — recado 050 extendió la
#     disponibilidad de prueba a 90 días).
# Mismos dos niveles para horario, con "hora:minuto"/"hora am/pm" como
# nivel 1 y "hora sola" ("7") como nivel 2.
_RE_PALABRA = r"\b{}\b"

# Recado 067 — hallazgo real y GRAVE: un dígito suelto ("2") dentro de
# una oración larga y completamente AJENA a elegir una opción (ej. "en
# 2 minutos", un comentario/feedback del paciente sobre el propio texto
# de ZANTIA) se interpretaba como si el paciente hubiera elegido la 2da
# opción — reproducido con evidencia real: una RESERVA REAL se creó a
# partir de puro feedback ("Aquí en este texto debe decir que finalizó
# la solicitud y que en 2 minutos puede iniciar otro trámite"), sin que
# el paciente pidiera nada. Mismo patrón de fondo que los recados
# 053/056 (dígito como substring de una hora tipo "7:30"), pero ahí el
# fix (`\b...\b`, límite de palabra) fue insuficiente para ESTE caso: el
# dígito SÍ es un token propio, solo que perdido dentro de una oración
# larga y sin ninguna relación con la pregunta de selección.
#
# Límite nuevo: el mensaje completo debe tener, como mucho,
# `_MAX_PALABRAS_ORDINAL_SUELTO` palabras — una respuesta real a "¿cuál
# prefieres?" es corta por naturaleza ("2", "la segunda", "prefiero la
# 2 por favor", "la del medio" — recado 052, 4 palabras); una oración
# de 15 palabras sobre otra cosa nunca es una selección genuina, sin
# importar qué dígitos contenga de pura casualidad. Umbral generoso
# (8 palabras) — cubre cómodamente respuestas reales ya vistas en este
# proyecto sin dejar pasar una oración claramente no relacionada.
#
# Compartida entre `HealthBrain._elegir_opcion` (fecha/horario) y
# `gateway.py:_elegir_opcion_ordinal` (selección de slot al
# reprogramar) — MISMA función, nunca una copia paralela; antes cada
# una tenía su propia implementación del mismo matching (documentado
# como deliberado en su momento, pero eso hizo que este hallazgo
# tuviera que corregirse dos veces si no se centralizaba ahora).
_MAX_PALABRAS_ORDINAL_SUELTO = 8


# Recado 069/070 — ampliada de 3 a 10 posiciones: hasta el 067, el único
# llamador real (fecha/horario/reprogramación) nunca ofrecía más de 3
# opciones a la vez, así que 3 bastaba. La selección de SERVICIO
# (`_interpretar_servicio`, recado 070) reutiliza esta MISMA función
# contra un catálogo real de 5 (hoy) — nunca inventar un mapeo paralelo
# solo para llegar a 5. Cada llamador sigue validando
# `indice < len(opciones)` (ver `_elegir_opcion`/`_elegir_opcion_ordinal`),
# así que ampliar el rango acá es inofensivo para los llamadores que de
# verdad solo ofrecen 3: un "4"/"5" que no aplica simplemente nunca
# cruza esa validación.
_ORDINALES_SUELTOS: tuple = (
    ("1", 0), ("primera", 0),
    ("2", 1), ("segunda", 1),
    ("3", 2), ("tercera", 2),
    ("4", 3), ("cuarta", 3),
    ("5", 4), ("quinta", 4),
    ("6", 5), ("sexta", 5),
    ("7", 6), ("septima", 6),
    ("8", 7), ("octava", 7),
    ("9", 8), ("novena", 8),
    ("10", 9), ("decima", 9),
)


def _indice_ordinal_seguro(texto: str) -> Optional[int]:
    """Devuelve el índice (0-9) de la opción "1"/"primera" ... "10"/
    "décima" reconocida como ordinal SUELTO en `texto` — `None` si no
    hay ninguna coincidencia, o si el mensaje es demasiado largo para
    ser una respuesta directa a una pregunta de selección (ver
    docstring del módulo arriba). `texto` se compara sin tildes
    (`_sin_tildes`) para que "séptima"/"décima" con o sin tilde
    coincidan igual — mismo criterio que el resto del archivo.

    Recado 070 — rango ampliado de 3 a 10 posiciones."""
    if len(texto.split()) > _MAX_PALABRAS_ORDINAL_SUELTO:
        return None
    texto_sin_tildes = _sin_tildes(texto)
    for clave, indice in _ORDINALES_SUELTOS:
        if re.search(_RE_PALABRA.format(re.escape(clave)), texto_sin_tildes):
            return indice
    return None


def _dia_semana_normalizado(fecha_iso: str) -> Optional[str]:
    try:
        fecha = datetime.strptime(fecha_iso, "%Y-%m-%d")
    except ValueError:
        return None
    return _sin_tildes(_DIAS_SEMANA[fecha.weekday()]).lower()


def _mes_normalizado(fecha_iso: str) -> Optional[str]:
    try:
        fecha = datetime.strptime(fecha_iso, "%Y-%m-%d")
    except ValueError:
        return None
    return _sin_tildes(_MESES[fecha.month - 1]).lower()


def _dia_del_mes(fecha_iso: str) -> Optional[str]:
    try:
        fecha = datetime.strptime(fecha_iso, "%Y-%m-%d")
    except ValueError:
        return None
    return str(datetime.strptime(fecha_iso, "%Y-%m-%d").day)


def _fecha_coincide_nivel1(texto_normalizado: str, fecha_iso: str) -> bool:
    """Día del mes + (mes o día de semana) — "7 de septiembre", "lunes
    7", "lunes 7 de septiembre"."""
    dia = _dia_del_mes(fecha_iso)
    if dia is None or not re.search(_RE_PALABRA.format(re.escape(dia)), texto_normalizado):
        return False
    mes = _mes_normalizado(fecha_iso)
    dia_semana = _dia_semana_normalizado(fecha_iso)
    tiene_mes = bool(mes) and mes in texto_normalizado
    tiene_dia_semana = bool(dia_semana) and re.search(_RE_PALABRA.format(re.escape(dia_semana)), texto_normalizado)
    return tiene_mes or bool(tiene_dia_semana)


def _fecha_coincide_nivel2(texto_normalizado: str, fecha_iso: str) -> bool:
    """Día de la semana solo, o día del mes solo."""
    dia_semana = _dia_semana_normalizado(fecha_iso)
    if dia_semana and re.search(_RE_PALABRA.format(re.escape(dia_semana)), texto_normalizado):
        return True
    dia = _dia_del_mes(fecha_iso)
    return bool(dia) and bool(re.search(_RE_PALABRA.format(re.escape(dia)), texto_normalizado))


def _emparejar_fecha_por_texto(texto: str, fechas: List[str]) -> Tuple[Optional[str], List[str]]:
    """Devuelve `(fecha_elegida, candidatos_ambiguos)` — mismo contrato
    que `_emparejar_servicio_por_similitud`: un único candidato ->
    `(fecha, [])`; dos o más (ambigüedad genuina) -> `(None,
    [fechas...])`; ninguno -> `(None, [])`."""
    texto_normalizado = _sin_tildes(texto).lower()
    for nivel in (_fecha_coincide_nivel1, _fecha_coincide_nivel2):
        candidatos = [f for f in fechas if nivel(texto_normalizado, f)]
        if len(candidatos) == 1:
            return candidatos[0], []
        if len(candidatos) >= 2:
            return None, candidatos
    return None, []


def _formas_hora_nivel1(hora_24: str) -> List[str]:
    """`"07:00"` -> formas de texto con precisión de minuto/meridiano:
    "07:00", "7:00", "7:00am", "7:00 am", "7 am", "7am", "7 de la
    mañana" (sin tilde ya en el resultado, comparado contra texto sin
    tilde). Nunca incluye la hora sola sin ningún otro dato (eso es
    nivel 2, más laxo)."""
    try:
        hh_str, mm_str = hora_24.split(":")
        hh, mm = int(hh_str), int(mm_str)
    except (ValueError, AttributeError):
        return [hora_24.lower()]
    hh12 = hh % 12 or 12
    meridiano = "am" if hh < 12 else "pm"
    periodo_idiomatico = "de la manana" if hh < 12 else ("de la tarde" if hh < 19 else "de la noche")
    formas = [
        hora_24.lower(),
        f"{hh}:{mm:02d}",
        f"{hh12}:{mm:02d}{meridiano}",
        f"{hh12}:{mm:02d} {meridiano}",
        f"{hh12}:{mm:02d} {periodo_idiomatico}",
    ]
    if mm == 0:
        formas.extend([f"{hh12}{meridiano}", f"{hh12} {meridiano}", f"{hh12} {periodo_idiomatico}"])
    return formas


def _hora_solo_normalizada(hora_24: str) -> Optional[str]:
    """La hora sola, sin minutos ni meridiano — "07:00"/"07:30" -> "7"
    (nivel 2, más laxo — puede colisionar entre dos opciones de la
    misma hora)."""
    try:
        hh_str, _ = hora_24.split(":")
        hh = int(hh_str)
    except (ValueError, AttributeError):
        return None
    hh12 = hh % 12 or 12
    return str(hh12)


def _horario_coincide_nivel1(texto_normalizado: str, hora_24: str) -> bool:
    # Recado 056 — hallazgo real encontrado al escribir pruebas de este
    # mismo recado: `_sin_tildes` (usado para normalizar `texto_normalizado`
    # antes de llegar aquí) deliberadamente NUNCA toca la "ñ" (mismo
    # criterio documentado en otra parte del archivo: "año"/"ano" son
    # palabras distintas) — pero las formas idiomáticas de este módulo
    # ("de la mañana"/"de la tarde"/"de la noche") están hardcodeadas SIN
    # "ñ" ("manana"). Un paciente real que escriba correctamente "8 de
    # la mañana" (con "ñ", tal como se escribe en español) nunca
    # matcheaba NINGUNA hora por esta discrepancia — normalizar "ñ"->"n"
    # SOLO en esta comparación puntual (nunca en `_sin_tildes` global,
    # que sigue protegiendo "año" en cualquier otro contexto del archivo).
    texto_sin_ene = texto_normalizado.replace("ñ", "n")
    return any(forma in texto_sin_ene for forma in _formas_hora_nivel1(hora_24))


def _horario_coincide_nivel2(texto_normalizado: str, hora_24: str) -> bool:
    hora_sola = _hora_solo_normalizada(hora_24)
    return bool(hora_sola) and bool(re.search(_RE_PALABRA.format(re.escape(hora_sola)), texto_normalizado))


def _emparejar_horario_por_texto(
    texto: str, horas: List[str], mostrar: Optional[List[str]] = None
) -> Tuple[Optional[str], List[str]]:
    """Mismo contrato que `_emparejar_fecha_por_texto`, sobre la lista
    de horas REALES ya ofrecidas (`datos["horas_ofrecidas"]`, paralela a
    `datos["opciones_horario"]` por índice).

    Recado 070 — hallazgo real contra hrmm-backend PRODUCCIÓN: `horas`
    puede tener valores REPETIDOS (dos médicos distintos ofreciendo la
    MISMA hora en consultorios distintos — nunca ocurre con el catálogo
    ficticio de los tests, donde cada hora es única). Antes, cuando el
    texto del paciente era ambiguo entre 2+ horas, los candidatos
    devueltos eran la hora bare ("07:30") — si las 2 opciones reales en
    disputa comparten esa misma hora, el mensaje de aclaración quedaba
    con 2 líneas IDÉNTICAS ("1. 07:30\\n2. 07:30"), inútil para elegir.
    `mostrar` (opcional, paralelo a `horas` por índice — normalmente
    `datos["horas_display_ofrecidas"]`, SIEMPRE con el consultorio) se
    usa para los candidatos devueltos en vez de la hora bare, cuando se
    provee — nunca cambia CUÁLES índices matchean, solo cómo se
    presentan."""
    texto_normalizado = _sin_tildes(texto).lower()
    mostrar_efectivo = mostrar if mostrar is not None else horas
    for nivel in (_horario_coincide_nivel1, _horario_coincide_nivel2):
        indices = [i for i, h in enumerate(horas) if nivel(texto_normalizado, h)]
        if len(indices) == 1:
            return horas[indices[0]], []
        if len(indices) >= 2:
            return None, [mostrar_efectivo[i] for i in indices]
    return None, []


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


# Recado 062 — generalización del MISMO mecanismo de arriba
# (SequenceMatcher + ventanas de tokens, recado 036) para reutilizarlo
# fuera de la elección de servicio: cualquier lista de frases cortas
# conocidas, no solo el catálogo. Encontrado al conectar el wizard de
# código de verificación (gateway.py) al reconocimiento de expresiones
# emocionales/preguntas — un typo real de una sola letra ("tristw" por
# "triste") no calzaba contra ninguna entrada exacta.
#
# Umbral 0.82 (el MISMO ya calibrado y documentado en el recado 036,
# no uno nuevo inventado) — verificado con ejemplos reales de este
# hallazgo: "Estoy tristw" contra "estoy triste" puntúa 0.917; "no me
# llegoo" contra "no me llego" puntúa 0.957; "reenbiame el codigo"
# contra "reenviame" puntúa 0.889; "a q correo lo enviaron" contra "a
# que correo" puntúa 0.909 — todos con margen cómodo sobre 0.82. Un
# código real de 6 dígitos contra cualquier frase de estas listas
# puntúa 0.000 (alfabético vs. numérico), cero riesgo de que un código
# real se confunda con un comando.
_UMBRAL_FUZZY_FRASE = _UMBRAL_FUZZY_SERVICIO


def _mejor_similitud_de_frase(tokens_texto: List[str], frase_normalizada: str) -> float:
    """Mismo algoritmo que `_similitud_servicio` — genérico, sin
    acoplarse a la semántica de "servicio"."""
    palabras = frase_normalizada.split()
    n = len(palabras)
    if len(tokens_texto) < n:
        ventanas = [" ".join(tokens_texto)]
    else:
        ventanas = [" ".join(tokens_texto[i : i + n]) for i in range(len(tokens_texto) - n + 1)]
    return max(
        (SequenceMatcher(None, ventana, frase_normalizada).ratio() for ventana in ventanas),
        default=0.0,
    )


def _contains_any_fuzzy(texto: str, frases: tuple, umbral: float = _UMBRAL_FUZZY_FRASE) -> bool:
    """Como `_contains_any_sin_tildes`, pero tolerante a errores de
    tipeo reales (recado 062) — reutiliza el mismo mecanismo del
    recado 036, generalizado a cualquier lista de frases cortas."""
    tokens = _tokens_sin_puntuacion_de_borde(_sin_tildes(texto).lower())
    return any(
        _mejor_similitud_de_frase(tokens, _sin_tildes(frase).lower()) >= umbral
        for frase in frases
    )


class HealthBrain:
    def __init__(
        self,
        activity_provider: Callable[[], Any],
        appointment_service: AppointmentService,
        selection_proposer: Optional[SelectionProposer] = None,
    ) -> None:
        self._activity_provider = activity_provider
        self._appointment_service = appointment_service
        # Recado 052 — colaborador OPCIONAL (default `None`, cero cambio
        # de comportamiento/cero llamada de red para cualquier
        # construcción existente de `HealthBrain`): mismo criterio de
        # "duck-typing opcional" que `appointment_service.buscar_paciente`
        # (recado 013) — cuando está presente, `_interpretar_fecha`/
        # `_interpretar_horario` lo consultan como ÚLTIMO recurso, solo
        # si su propio matching determinista no encontró NINGÚN
        # candidato. `build_health_brain()` (config.py) solo lo pasa
        # cuando `HEALTH_BRAIN_TYPE=llm` Y `ANTHROPIC_API_KEY` están
        # configuradas — el mismo gate que ya existe para la redacción
        # de texto (recado 038), no uno nuevo.
        self._selection_proposer = selection_proposer

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

        # Recado 067 — auditoría completa de "salir"/despedida: a
        # diferencia de las otras 5 categorías de interrupción de abajo
        # (que si se excluyen a propósito en
        # `_ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO`, para no reinterrumpir
        # un wizard de interrupción ya en curso), la intención de SALIR
        # debe reconocerse SIEMPRE, en CUALQUIER etapa sin excepción —
        # incluidas `esperando_documento_beneficiario`/
        # `esperando_confirmacion_beneficiario`, confirmado con evidencia
        # real que quedaban sin ninguna salida (ni siquiera un
        # escalamiento tras intentos fallidos, a diferencia del wizard
        # de identidad de gateway.py) si el documento nunca calzaba
        # contra `buscar_paciente`. Mismo criterio que `_OLVIDAR` arriba
        # (prioridad máxima, antes que cualquier otra cosa).
        if _es_despedida(texto) or _es_solicitud_de_salir(texto):
            nuevos = {**datos, "etapa": "finalizada", "decision": "DECLINED"}
            nombre = (self._activity.patient_contact or {}).get("nombre")
            return BrainOutput(
                senales_detectadas=["despedida_reconocida"],
                respuesta_propuesta=_texto_despedida(nombre),
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

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
            interrupcion = self._detectar_interrupcion_de_contexto(
                texto, datos, etapa, state.resultado_de_herramientas
            )
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
        self,
        texto: str,
        datos: Dict[str, Any],
        etapa_actual: str,
        resultado_de_herramientas: Optional[Dict[str, Any]] = None,
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
        mensaje a su manera.

        `resultado_de_herramientas` (recado 054, agregado a la firma tras
        el 058): el mismo dict acumulativo de `ConversationState` — se
        usa SOLO en la rama "pregunta sobre correo enviado" para
        responder con el estado REAL del último intento de envío
        (`Appointment.correo_confirmacion_enviado`), nunca con una
        promesa genérica. Default `None` (tratado como `{}`) porque el
        llamador de `gateway.py:_evaluar_ventana_de_gracia` reevalúa este
        método sobre una Activity YA CERRADA leyendo el `ConversationState`
        persistido — que sí tiene el campo, así que en la práctica
        siempre se pasa; el default solo cubre una llamada directa desde
        un test que no lo necesite."""
        resultado_de_herramientas = resultado_de_herramientas or {}
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

        # Recado 064 (segunda parte) — hallazgo real: dos preguntas sobre
        # el hospital en sí, no sobre el trámite, que ninguna categoría
        # de arriba reconocía. Mismo patrón que `_responder_expresion_emocional`
        # (recado 053): `etapa`/`datos` NUNCA cambian, y la respuesta
        # incluye el MISMO recordatorio breve de `_RECORDATORIO_BREVE_POR_ETAPA`
        # para volver naturalmente a lo que se le estaba preguntando —
        # reutilizado tal cual, nunca un texto de recordatorio nuevo y
        # paralelo.
        if _contains_any_sin_tildes(texto, _PREGUNTA_UBICACION_HOSPITAL):
            # Recado 066 — el usuario confirmó teléfono/correo/dirección
            # reales (`institutional_info.py`, única fuente de verdad).
            # `_texto_informacion_hospital` arma el texto SIEMPRE a partir
            # de esos datos, nunca de un valor escrito a mano acá —
            # extensible sin duplicar lógica si algún campo cambia.
            recordatorio = _RECORDATORIO_BREVE_POR_ETAPA.get(etapa_actual, "¿en qué te puedo ayudar?")
            return BrainOutput(
                senales_detectadas=["pregunta_ubicacion_hospital"],
                respuesta_propuesta=f"{_texto_informacion_hospital(INFORMACION_HOSPITAL)} {recordatorio}",
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        if _contains_any_sin_tildes(texto, _PREGUNTA_CALIDAD_ATENCION):
            # Nunca una opinión personal del sistema (mismo principio de
            # `OpinionPersonalGuardrail`, aunque esa regla vive en Core y
            # bloquea temas AJENOS al propósito — acá el tema SÍ es
            # relevante, pero ZANTIA tampoco inventa una calificación que
            # no tiene) — honestidad cálida, nunca evasiva ni robótica.
            recordatorio = _RECORDATORIO_BREVE_POR_ETAPA.get(etapa_actual, "¿en qué te puedo ayudar?")
            return BrainOutput(
                senales_detectadas=["pregunta_calidad_atencion"],
                respuesta_propuesta=(
                    "Es una pregunta válida, pero no tengo información objetiva para darte una opinión "
                    "sobre eso — lo que sí puedo hacer con gusto es ayudarte a agendar tu atención cuando "
                    f"quieras. {recordatorio}"
                ),
                proxima_accion_propuesta="preguntar_intencion",
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

        # Recado 053, Parte 2 — "consultar mis citas" reconocido en
        # CUALQUIER etapa (antes solo funcionaba como enrutamiento de
        # primer contacto en `gateway.py`, nunca dentro de `HealthBrain`
        # — hallazgo real: un paciente atascado en "esperando_servicio"
        # que escribía esto quedaba en loop). `etapa` NO cambia (mismo
        # criterio que INFO_NO_AUTORIZADA/PIDE_INFO arriba) — el
        # paciente sigue exactamente donde estaba después de ver sus
        # citas reales.
        if _contains_any_sin_tildes(texto, _CONSULTA_CITAS_EXISTENTES):
            citas = [
                c for c in self._appointment_service.get_patient_appointments(self._activity.patient_reference)
                if c.status.value in ("CONFIRMED", "RESCHEDULED")
            ]
            if citas:
                # Recado 054 — lista numerada, fecha en el mismo formato
                # humano ya establecido en el resto del archivo (nunca
                # ISO cruda).
                plural = len(citas) != 1
                intro = (
                    f"Aquí tienes tu{'s' if plural else ''} {len(citas)} "
                    f"cita{'s' if plural else ''} activa{'s' if plural else ''}:"
                )
                lista_citas = _lista_numerada([
                    f"{c.service} — {_formatear_fecha_humana(c.date)}, {c.time}, {c.location}" for c in citas
                ])
                respuesta = f"{intro}\n{lista_citas}"
            else:
                respuesta = "Revisé y no tienes ninguna cita activa registrada por este canal por ahora."
            return BrainOutput(
                senales_detectadas=["consulta_citas_existentes"],
                respuesta_propuesta=respuesta,
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        # Recado 058 — pregunta sobre una acción que el sistema ACABA de
        # decir que hizo (hoy, específicamente el correo de confirmación
        # — la única promesa de acción que `agent.py`/`gateway.py`
        # concatenan tras reservar/cancelar/reprogramar, ver recado
        # 054). Respuesta HONESTA basada en el estado REAL: desde que el
        # recado 054 conectó el envío real (`HrmmAppointmentService.
        # enviar_confirmacion_email`), `resultado_de_herramientas` trae
        # el resultado verdadero del ÚLTIMO intento (`book_appointment`
        # es el único tool WRITE que hoy pasa por `interpret()` con este
        # dato disponible — cancelar/reprogramar viven enteramente en
        # `gateway.py`, fuera de este método, ver `_procesar_intento_de_codigo`).
        # `respuesta_pregunta_sobre_correo` (models.py) ya devuelve el
        # texto correcto para los 3 casos (enviado/fallido/nunca
        # intentado) — nunca se reafirma una promesa como hecho
        # confirmado sin evidencia, mismo principio que
        # `NoPrometerContactoGuardrail`. `etapa` no cambia — el paciente
        # sigue disponible para lo que diga después (despedirse, pedir
        # algo nuevo), nunca se reinicia el flujo ni se pregunta servicio.
        if _contains_any_sin_tildes(texto, _PREGUNTA_SOBRE_CORREO_ENVIADO):
            correo_confirmacion_enviado = (
                resultado_de_herramientas.get("book_appointment", {}) or {}
            ).get("correo_confirmacion_enviado")
            return BrainOutput(
                senales_detectadas=["pregunta_sobre_correo_enviado"],
                respuesta_propuesta=respuesta_pregunta_sobre_correo(correo_confirmacion_enviado),
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        # Recado 058 — despedida/cierre de conversación explícito ("no
        # gracias ya termine") reconocido en CUALQUIER etapa — antes se
        # interpretaba como un intento de nombrar un servicio (si
        # ocurría en "esperando_servicio") o caía al fallback genérico
        # de sí/no en cualquier otra etapa, nunca como lo que
        # genuinamente es: el paciente dando la conversación por
        # terminada. Reutiliza el MISMO mecanismo ya existente de
        # "declinar" (`_es_negativo` en `_interpretar_decision`,
        # `datos["decision"] = "DECLINED"` -> `agent.py:
        # _sincronizar_activity` -> `ManagementStatus.DECLINED` ->
        # `gateway.py:_cerrar_si_definitivo` cierra la Activity de
        # verdad) — nunca un mecanismo nuevo y paralelo sin sincronizar
        # (lección explícita del recado 057: código duplicado sin
        # sincronizar es la fuente real de bugs de esta serie).
        # Recado 067 — `_es_solicitud_de_salir` (arriba) agregada a la
        # MISMA condición: "salir"/"exit" ahora cierran la conversación
        # exactamente igual que una despedida en lenguaje natural —
        # mismo texto, mismo cierre real (DECLINED), ninguna rama nueva
        # y paralela.
        if _es_despedida(texto) or _es_solicitud_de_salir(texto):
            nuevos = {**datos, "etapa": "finalizada", "decision": "DECLINED"}
            nombre = (self._activity.patient_contact or {}).get("nombre")
            return BrainOutput(
                senales_detectadas=["despedida_reconocida"],
                respuesta_propuesta=_texto_despedida(nombre),
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        # Recado 053, Parte 3 — expresión emocional/personal real ("me
        # deprime ir al médico") reconocida como su PROPIA categoría —
        # nunca el fallback genérico de "no te entendí" (un typo no es
        # lo mismo que una expresión emocional real, y merece una
        # respuesta distinta: breve validación humana, SIN diagnosticar
        # ni aconsejar — eso sigue fuera del propósito de ZANTIA, ver
        # `OpinionPersonalGuardrail`, sin cambios — y vuelta natural al
        # contexto). Deliberadamente la ÚLTIMA categoría revisada aquí:
        # si el mensaje TAMBIÉN contiene algo más específico y accionable
        # (ej. "es para mi hija" o "cancela mi cita"), esa rama más
        # específica gana — la validación emocional es, a propósito, la
        # red de seguridad más genérica, no la de mayor prioridad.
        if _es_expresion_emocional(texto):
            return self._responder_expresion_emocional(datos, etapa_actual)

        return None

    def _responder_expresion_emocional(self, datos: Dict[str, Any], etapa_actual: str) -> BrainOutput:
        """Recado 053 — validación humana breve (nunca diagnóstico, nunca
        consejo) + recordatorio BREVE de qué se le había preguntado en
        `etapa_actual`, para volver al contexto de forma natural, sin
        repetir la presentación institucional completa (esa vive
        enteramente en `gateway.py`, fuera del alcance de este método) y
        sin reiniciar ni avanzar el flujo (`etapa`/`datos` sin tocar)."""
        recordatorio = _RECORDATORIO_BREVE_POR_ETAPA.get(
            etapa_actual, "¿en qué te puedo ayudar?"
        )
        return BrainOutput(
            senales_detectadas=["expresion_emocional_reconocida"],
            respuesta_propuesta=f"Entiendo, y lamento que te sientas así. {recordatorio}",
            proxima_accion_propuesta="preguntar_intencion",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
        )

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
            # Recado 054 — lista numerada, un servicio por línea (nunca
            # texto corrido separado por comas) — ver `_LISTA_NUMERADA`.
            lista_servicios = _lista_numerada(servicios)
            respuesta = (
                f"Claro, estas son las opciones disponibles:\n{lista_servicios}\n"
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
        ambiguo entre dos o más servicios reales.

        Recado 070 — hallazgo real de producción: el paciente ve la
        lista numerada (`_lista_numerada`, recado 054) y responde con el
        ordinal ("3" para elegir la 3ra opción mostrada), igual que ya
        funciona para fecha/horario/menú/reprogramación — pero esta
        función NUNCA aceptó un ordinal (confirmado con `git log`: desde
        que existe, recado 030, solo hizo match por nombre; el commit
        `d7d4835`, recado 036, documenta explícitamente que fecha/
        horario "no necesitan el mismo tratamiento [de fuzzy matching]
        (selección por ordinal, no por nombre libre)" — la ausencia de
        ordinal acá fue una decisión de diseño original, nunca una
        regresión de un recado posterior). Se revisa el ordinal PRIMERO
        (mismo `_indice_ordinal_seguro` ya usado por `_elegir_opcion`),
        contra el catálogo EXACTO en el mismo orden que se le mostró al
        paciente (`list_services()`, sin reordenar) — si no hay ordinal,
        cae al match por nombre/fuzzy de siempre, sin cambios."""
        listar = getattr(self._appointment_service, "list_services", None)
        servicios = listar() if listar else []
        elegido = None
        if servicios:
            indice = _indice_ordinal_seguro(texto)
            if indice is not None and indice < len(servicios):
                elegido = servicios[indice]
        if elegido is None:
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
                texto_candidatos = _lista_numerada(candidatos_ambiguos)
                variante, nuevos = _elegir_variante(
                    _VARIANTES_SERVICIO_AMBIGUO, datos, "intentos_aclaracion_servicio_ambiguo"
                )
                respuesta = variante.format(opciones=texto_candidatos)
            elif servicios:
                texto_servicios = _lista_numerada(servicios)
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
        lista_fechas = _lista_numerada([_formatear_fecha_humana(f) for f in fechas])
        return BrainOutput(
            respuesta_propuesta=f"Estas son las fechas disponibles:\n{lista_fechas}\n¿Cuál te queda mejor?",
            # "preguntar_dato_faltante" (no "ejecutar_tool"): todavía
            # falta que el paciente elija fecha y horario antes de
            # reservar — la tool que se ejecuta aquí es de lectura
            # (get_availability), no la acción final.
            proxima_accion_propuesta="preguntar_dato_faltante",
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_seleccion_asistida_por_llm(
        self,
        texto: str,
        opciones_valores: List[str],
        formatear: Optional[Callable[[str], str]] = None,
    ) -> Tuple[Optional[str], Optional[VerificacionDeSeleccion]]:
        """Recado 052 — ÚLTIMO recurso, solo cuando el matching
        determinista del propio dominio (ordinal + texto libre
        específico de fecha/hora, recado 051) no encontró NINGÚN
        candidato — ni siquiera ambiguo (una ambigüedad genuina entre 2+
        opciones reales ya es, por sí sola, suficientemente informativa;
        no vale la pena el costo/latencia de una llamada real para
        resolverla, y el mensaje de aclaración que ya existe muestra
        las opciones reales en disputa). Nunca se ejecuta si no hay un
        `SelectionProposer` configurado (`HealthBrain` construido sin
        uno — default seguro con `HEALTH_BRAIN_TYPE=deterministico`,
        o si `ANTHROPIC_API_KEY` falta pese a `HEALTH_BRAIN_TYPE=llm`,
        ver `domains/health/config.py`): en ese caso devuelve
        `(None, None)` de inmediato, sin ningún intento de red — el
        llamador sigue con su propio fallback de aclaración de siempre,
        exactamente como si este mecanismo no existiera.

        `core.selection.interpret_selection` (Core, agnóstico de
        dominio) es quien VERIFICA que la propuesta del LLM corresponda
        EXACTAMENTE a una de `opciones_valores` — este método nunca
        confía en la propuesta por su cuenta. Si se acepta, además arma
        `VerificacionDeSeleccion` para que
        `SeleccionAsistidaPorLLMNoVerificadaGuardrail` (Core) pueda
        volver a verificarlo de forma independiente, como segunda capa."""
        if self._selection_proposer is None:
            return None, None
        opciones = [
            SelectionOption(id=v, text=formatear(v) if formatear else v) for v in opciones_valores
        ]
        resultado = interpret_selection(texto, opciones, self._selection_proposer)
        if resultado.option is None:
            return None, None
        verificacion = VerificacionDeSeleccion(
            opciones_reales_ids=[o.id for o in opciones],
            id_seleccionado_via_llm=resultado.option.id,
        )
        return resultado.option.id, verificacion

    def _interpretar_fecha(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """PASO 2 (respuesta) — el paciente elige una de las fechas ya
        ofrecidas. Primero por ordinal (`_elegir_opcion`, mecanismo de
        siempre, sin cambios); si no matchea, por texto libre (recado
        051: día de semana, día del mes, o la fecha completa tal como
        se mostró — `_emparejar_fecha_por_texto`); si tampoco encuentra
        NADA (ni ambigüedad), como último recurso se consulta un LLM
        asistido y VERIFICADO (recado 052,
        `_interpretar_seleccion_asistida_por_llm`) para lenguaje libre
        que ninguna regla determinista anticipó (ej. "la del medio",
        "esa que dijiste primero"). Nunca inventa ni asume la primera si
        no fue claro, y nunca elige por el paciente si el texto es
        ambiguo entre dos o más fechas reales ofrecidas."""
        fechas = datos.get("fechas_ofrecidas", [])
        elegida = self._elegir_opcion(texto, fechas)
        candidatos_ambiguos: List[str] = []
        if elegida is None:
            elegida, candidatos_ambiguos = _emparejar_fecha_por_texto(texto, fechas)
        verificacion_seleccion: Optional[VerificacionDeSeleccion] = None
        if elegida is None and not candidatos_ambiguos:
            elegida, verificacion_seleccion = self._interpretar_seleccion_asistida_por_llm(
                texto, fechas, _formatear_fecha_humana
            )
        if elegida is None:
            nuevos = datos
            if candidatos_ambiguos:
                texto_candidatos = _lista_numerada([_formatear_fecha_humana(f) for f in candidatos_ambiguos])
                variante, nuevos = _elegir_variante(
                    _VARIANTES_FECHA_AMBIGUA, datos, "intentos_aclaracion_fecha_ambigua"
                )
                respuesta = variante.format(opciones=texto_candidatos)
            else:
                texto_fechas = _lista_numerada([_formatear_fecha_humana(f) for f in fechas])
                variante, nuevos = _elegir_variante(
                    _VARIANTES_FECHA_NO_IDENTIFICADA, datos, "intentos_aclaracion_fecha"
                )
                respuesta = variante.format(opciones=texto_fechas)
            return BrainOutput(
                respuesta_propuesta=respuesta,
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {**datos, "fecha_elegida": elegida}
        salida = self._ofrecer_horarios(nuevos)
        if verificacion_seleccion is not None:
            salida = salida.model_copy(update={"verificacion_de_seleccion": verificacion_seleccion})
        return salida

    def _ofrecer_horarios(self, datos: Dict[str, Any]) -> BrainOutput:
        """PASO 3 — horarios reales para el servicio Y la fecha ya
        elegidos, uno por línea (nunca combinado con la fecha, que ya
        se confirmó en el paso anterior)."""
        servicio = datos["servicio_elegido"]
        fecha = datos["fecha_elegida"]
        # Recado 056 — hallazgo real encontrado al investigar el bug de
        # Odontologia/07:30: `AppointmentService.get_availability` NO
        # garantiza ningún orden (`HrmmAppointmentService.get_availability`
        # devuelve los bloques tal como los entrega hrmm-backend — orden de
        # inserción, no cronológico, confirmado leyendo el JSON real de
        # `/api/agenda/disponibilidad`: para un servicio con VARIOS
        # médicos, los bloques de las 07:00 de cada médico aparecen
        # consecutivos ANTES que los de las 07:30 de cualquiera). Tomar
        # `[:3]` sin ordenar podía mostrarle al paciente 3 horarios que
        # NO son los 3 más próximos reales (ej. las 07:00 de 3 médicos
        # distintos, saltándose las 07:30 de todos ellos) — un defecto de
        # UX real e independiente del hallazgo puntual reportado (no
        # explica por sí solo una reserva en un horario nunca ofrecido,
        # pero es la misma clase de riesgo: mostrar una lista que no
        # refleja fielmente la disponibilidad real). `_ofrecer_fechas`
        # (arriba) ya ordenaba sus fechas — esto alinea `_ofrecer_horarios`
        # con el mismo criterio.
        opciones = sorted(
            (o for o in self._appointment_service.get_availability(servicio) if o.date == fecha),
            key=lambda o: o.time,
        )[:3]
        if not opciones:
            # Caso raro (condición de carrera real: alguien más reservó
            # el último cupo de esa fecha entre el PASO 2 y esta
            # respuesta) — nunca se inventa un horario; se vuelve al
            # PASO 2 con disponibilidad fresca en vez de dejar al
            # paciente sin ninguna salida.
            return self._ofrecer_fechas({**datos, "etapa": "esperando_fecha"})
        fecha_legible = _formatear_fecha_humana(fecha)
        # Recado 054 — lista numerada. Si TODAS las opciones comparten el
        # mismo consultorio (caso real más común: un solo profesional
        # cubre ese servicio+fecha), se menciona UNA vez en la
        # introducción y la lista queda solo con la hora — nunca se repite
        # el mismo dato en cada línea. Si difieren (dos profesionales
        # distintos ofreciendo el mismo servicio ese día), se mantiene el
        # consultorio en cada línea — nunca se inventa un consultorio
        # único que no sea real para todas las opciones.
        ubicaciones = {o.location for o in opciones}
        if len(ubicaciones) == 1:
            ubicacion_unica = next(iter(ubicaciones))
            intro = f"Para el {fecha_legible} tengo estos horarios disponibles en {ubicacion_unica}:"
            lista_horarios = _lista_numerada([o.time for o in opciones])
        else:
            intro = f"Para el {fecha_legible}, estos son los horarios disponibles:"
            lista_horarios = _lista_numerada([f"{o.time} en {o.location}" for o in opciones])
        # Recado 070 (hallazgo real contra hrmm-backend PRODUCCIÓN, no
        # reproducible con el catálogo ficticio de los tests — dos
        # médicos reales del mismo servicio ofrecen la MISMA hora en
        # consultorios distintos): "horas_ofrecidas" (solo la hora, sin
        # consultorio) deja de ser suficiente para distinguir opciones
        # cuando hay horas repetidas ("07:30" y "07:30") — se guarda
        # ADEMÁS `horas_display_ofrecidas`, SIEMPRE con el consultorio
        # incluido (a diferencia de `lista_horarios` arriba, que lo omite
        # cuando es el mismo para todas — acá se necesita SIEMPRE
        # inequívoco, incluso en ese caso, para desambiguar candidatos
        # ambiguos) y el texto YA renderizado de la oferta completa
        # (`texto_horario_ofrecido`), para repetirlo fielmente si hace
        # falta una aclaración más abajo.
        nuevos = {
            **datos,
            "etapa": "esperando_horario",
            "opciones_horario": [o.slot_id for o in opciones],
            # Paralela a "opciones_horario" por índice (recado 051) — la
            # hora REAL tal como se le mostró al paciente, para poder
            # reconocerla si la repite en texto libre en vez de un
            # ordinal (_emparejar_horario_por_texto). Nunca se usa para
            # nada más que comparar contra el texto de la respuesta.
            "horas_ofrecidas": [o.time for o in opciones],
            "horas_display_ofrecidas": [f"{o.time} en {o.location}" for o in opciones],
            "texto_horario_ofrecido": lista_horarios,
        }
        return BrainOutput(
            respuesta_propuesta=f"{intro}\n{lista_horarios}\n¿Cuál prefieres?",
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
        combinada. Primero por ordinal (`_elegir_opcion`, sin cambios);
        si no matchea, por texto libre (recado 051: la hora tal como se
        mostró, o solo la hora sin minutos/meridiano —
        `_emparejar_horario_por_texto` sobre `datos["horas_ofrecidas"]`,
        paralela a `opciones_horario` por índice); si tampoco encuentra
        NADA (ni ambigüedad), como último recurso un LLM asistido y
        VERIFICADO (recado 052) — nunca se elige por el paciente si el
        texto es ambiguo entre dos horarios reales."""
        opciones = datos.get("opciones_horario", [])
        horas = datos.get("horas_ofrecidas", [])
        # Recado 070 — `horas_display_ofrecidas` SIEMPRE trae el
        # consultorio (a diferencia de `horas`, que puede tener valores
        # REPETIDOS entre dos médicos distintos con la misma hora —
        # hallazgo real contra hrmm-backend producción, nunca
        # reproducible con el catálogo ficticio de los tests). Con
        # `len(datos.get(...)) != len(horas)` como red de seguridad
        # (estado viejo de antes de este recado, sin esta clave) cae al
        # mismo `horas` bare de siempre — nunca un `IndexError`.
        horas_display = datos.get("horas_display_ofrecidas") or horas
        elegida = self._elegir_opcion(texto, opciones)
        candidatos_ambiguos: List[str] = []
        if elegida is None and horas:
            hora_elegida, candidatos_ambiguos = _emparejar_horario_por_texto(texto, horas, horas_display)
            if hora_elegida is not None:
                elegida = opciones[horas.index(hora_elegida)]
        verificacion_seleccion: Optional[VerificacionDeSeleccion] = None
        if elegida is None and opciones and not candidatos_ambiguos:
            # Recado 070 — hallazgo real de correctitud, no solo de
            # presentación: antes se pasaba `horas` (bare, con posibles
            # REPETIDOS) como `opciones_valores` — un `id` de selección
            # duplicado rompe la premisa de `core.selection.interpret_selection`
            # (el id debe identificar UNA opción real sin ambigüedad).
            # Ahora se usa `opciones` (los `slot_id` reales, siempre
            # ÚNICOS) como id, con `horas_display` como texto legible
            # para el LLM — `elegida` queda DIRECTAMENTE el slot_id
            # verificado, sin ningún `.index()` de por medio.
            elegida, verificacion_seleccion = self._interpretar_seleccion_asistida_por_llm(
                texto, opciones, lambda slot_id: horas_display[opciones.index(slot_id)]
            )
        if elegida is None:
            nuevos = datos
            if candidatos_ambiguos:
                texto_candidatos = _lista_numerada(candidatos_ambiguos)
                variante, nuevos = _elegir_variante(
                    _VARIANTES_HORARIO_AMBIGUO, datos, "intentos_aclaracion_horario_ambiguo"
                )
                respuesta = variante.format(opciones=texto_candidatos)
            else:
                # Recado 070 — se repite el texto YA renderizado de la
                # oferta original (`texto_horario_ofrecido`, guardado en
                # `_ofrecer_horarios`) en vez de reconstruir la lista
                # desde `horas` bare — garantiza EXACTAMENTE la misma
                # desambiguación (consultorio incluido cuando hace
                # falta) que ya se le mostró al paciente, nunca una
                # versión empobrecida.
                texto_horas = datos.get("texto_horario_ofrecido") or _lista_numerada(horas_display)
                variante, nuevos = _elegir_variante(
                    _VARIANTES_SELECCION_NO_IDENTIFICADA, datos, "intentos_aclaracion_seleccion"
                )
                respuesta = variante.format(opciones=texto_horas)
            return BrainOutput(
                respuesta_propuesta=respuesta,
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
            # lista real, o el matching de texto libre del recado 051,
            # o — recado 052 — un LLM asistido cuya propuesta ya fue
            # VERIFICADA contra `horas` antes de llegar aquí) — nunca la
            # interpretación libre de un LLM SIN verificar.
            confirmacion_estructurada_para_write=True,
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            verificacion_de_seleccion=verificacion_seleccion,
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
        """Recado 053 — hallazgo real de producción, caso Giselle Tornay
        (documento 22669564): "3" es substring literal de "7:30" ("7:"
        + "3" + "0"), así que un `in` simple hacía que CUALQUIER
        respuesta de horario/fecha que contuviera el dígito "1"/"2"/"3"
        en cualquier posición (una hora, un día del mes) se reinterpretara
        como ordinal — el paciente confirmó "7:30" y el sistema reservó
        la TERCERA opción (08:00) real, no la que pidió. Mismo patrón
        exacto que el bug real "programar"/"reprogramar" del recado 046
        (`gateway.py:_interpretar_opcion_menu`), nunca corregido aquí.
        `\\b...\\b` exige que el dígito sea un TOKEN propio (no parte de
        "7:30", "13", "08:00") — sigue reconociendo "3" sola, "opción 3",
        "la 3", exactamente igual que antes para esos casos.

        Recado 067 — delega en `_indice_ordinal_seguro` (módulo, ver su
        docstring): el límite de palabra por sí solo no bastaba —
        "en 2 minutos" dentro de una oración larga y ajena a la
        selección seguía matcheando "2" como ordinal, causando una
        RESERVA REAL creada a partir de puro feedback del paciente."""
        indice = _indice_ordinal_seguro(texto)
        if indice is not None and indice < len(opciones):
            return opciones[indice]
        return None

    # ------------------------------------------------------------------
    def _iniciar_reprogramacion(self, datos: Dict[str, Any]) -> BrainOutput:
        servicio = self._activity.service or "medicina general"
        # Recado 056 — mismo fix de `_ofrecer_horarios`: ordena antes de
        # recortar a 3, nunca depende del orden de `get_availability`.
        opciones = sorted(
            self._appointment_service.get_availability(servicio), key=lambda o: (o.date, o.time)
        )[:3]
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
        # Recado 056 — mismo formato de lista numerada del recado 055,
        # fecha en el mismo formato humano ya establecido en el resto
        # del archivo (nunca ISO cruda). Deliberadamente fuera del
        # alcance original del recado 055 (no era uno de los 4 lugares
        # pedidos) — corregido ahora para consistencia total, mismo
        # patrón de "encontrado al investigar, corregido en el mismo
        # trabajo" del resto de esta sesión.
        lista_opciones = _lista_numerada(
            [f"{_formatear_fecha_humana(o.date)}, {o.time}, {o.location}" for o in opciones]
        )
        # Recado 070 — se guarda el texto YA formateado de la lista (no
        # solo los `slot_id`, que no traen fecha/hora/consultorio
        # legibles) para poder repetirla fielmente si `_interpretar_
        # seleccion_reprogramacion` necesita pedir aclaración más abajo
        # — nunca "¿es la 1, la 2 o la 3?" sin volver a mostrar qué es
        # cada una.
        nuevos = {**nuevos, "texto_opciones_reprogramacion": lista_opciones}
        return BrainOutput(
            senales_detectadas=["reprogramacion_solicitada"],
            respuesta_propuesta=f"Claro que sí, aquí tienes otras opciones:\n{lista_opciones}\n¿Cuál te queda mejor?",
            proxima_accion_propuesta="preguntar_dato_faltante",  # ver comentario equivalente arriba
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_seleccion_reprogramacion(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        opciones = datos.get("opciones_reprogramacion", [])
        elegida = self._elegir_opcion(texto, opciones)
        if elegida is None:
            texto_opciones = datos.get("texto_opciones_reprogramacion", "")
            return BrainOutput(
                respuesta_propuesta=f"No identifiqué cuál opción prefieres:\n{texto_opciones}\n¿me confirmas si es la 1, la 2 o la 3?",
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
