# RECADO PARA CHATGPT

Fecha: 2026-09-28
Proyecto: ZANTIA (repo `icaco`, `/Users/enzoalfonso/Orangutan/icaco`, rama `main`, HEAD `30872a4`, árbol limpio al iniciar)
Tema: Especificación para extraer a un paquete reutilizable los patrones de IA del Core (selección verificada, estado temporizado, guardrails, orquestador)
Objetivo de la investigación: Que quien reimplemente estos patrones en un paquete independiente no tenga que adivinar nada: interfaz pública, reglas y su origen en errores reales, tests que sirven de ejemplo, qué está atado al proyecto, dependencias a abstraer y orden de extracción.

Tiempo empleado: ~4 minutos de reloj del sistema (inicio 13:16:48, fin 13:20:43).
Modo: SOLO LECTURA. No se modificó código, no se hizo commit y no se ejecutó nada contra servicios reales. Solo se corrió `pytest` en local sin `ANTHROPIC_API_KEY` ni `ZANTIA_RUN_REAL_*` (los tests de red real quedaron saltados).
Datos personales y credenciales: ninguno reproducido. Los nombres de tests se citan; los fixtures no se copian.

---

## Resumen ejecutivo

- HECHO: los cuatro elementos existen y están cubiertos por tests. Suite completa: **633 passed, 17 skipped** (1.44 s). Subconjunto relevante a este recado: **123 passed, 5 skipped**. Los skipped son todos tests de red real contra Anthropic/HRMM, deshabilitados por defecto.
- HECHO: la regla que organiza todo es **"el LLM propone, el código verifica contra datos reales, el orquestador decide"**. Se aplica en tres capas independientes:
  1. `interpret_selection` solo acepta un id que exista literalmente en las opciones reales.
  2. `SeleccionAsistidaPorLLMNoVerificadaGuardrail` vuelve a verificarlo.
  3. `ConfirmacionEstructuradaRequeridaParaWriteGuardrail` bloquea por defecto cualquier tool WRITE que no traiga la declaración explícita de confirmación determinista.
- HECHO: `core/selection.py` y `core/timed_state.py` son casi 100% genéricos y se pueden extraer ya. Los guardrails son **genéricos en mecanismo pero atados al idioma español** (y uno a "cita"). El orquestador está acoplado a `ConversationState`, a la máquina de estados y a varios stores del proyecto.
- HALLAZGO NUEVO (CONFIRMADO por lectura de código, no cubierto por ningún test): cuando el veredicto consolidado es **MODIFY**, el orquestador **sigue ejecutando la tool propuesta, incluida una WRITE**. Solo reemplaza el texto. Esto hay que decidirlo explícitamente en el paquete (ver "Problemas encontrados").
- RECOMENDACIÓN: extraer primero `selection` y `timed_state`, con el paquete de guardrails "de verificación" (DatoInventado, SelecciónNoVerificada, ConfirmaciónEstructurada, TipoDePreguntaAlterada, más el engine) en la misma primera entrega. El orquestador va al final.

---

## Hallazgos

### A. `core/selection.py`: interpretación asistida por un modelo, verificada

#### A.1 Interfaz pública [CONFIRMADO]

```python
@dataclass(frozen=True)
class SelectionOption:
    id: str      # identificador determinista del dominio (fecha ISO, slot_id, código de menú...)
    text: str    # lo único que ve el LLM; forma legible mostrada al usuario

@dataclass(frozen=True)
class SelectionResult:
    option: Optional[SelectionOption]
    source: str  # "llm" | "none"

class SelectionProposer(Protocol):
    def propose(self, free_text: str, options: List[SelectionOption]) -> Optional[str]: ...
    # devuelve un id o None; PUEDE lanzar excepción

def interpret_selection(free_text: str,
                        options: List[SelectionOption],
                        proposer: Optional[SelectionProposer]) -> SelectionResult

class AnthropicSelectionProposer:            # implementación real
    def __init__(self, model: str = "claude-sonnet-5", api_key_env_var: str = "ANTHROPIC_API_KEY")
    def propose(self, free_text, options) -> Optional[str]
```

#### A.2 Reglas y comportamientos [CONFIRMADO]

| # | Regla | Cómo se detecta o aplica | Origen |
|---|---|---|---|
| S1 | Único punto seguro: solo devuelve una opción que está **literalmente** en `options` (comparación exacta por `id`, sin aproximar). | `[o for o in options if o.id == id_propuesto]` | Recado 052 |
| S2 | **Id alucinado** (0 coincidencias) → rechazo (`source="none"`) y log warning. | `len(coincidencias) == 0` | Recado 052 (alucinación del modelo) |
| S3 | **Ids duplicados en el dominio** (2+ coincidencias) → rechazo por ambigüedad, nunca se adivina. | `len(coincidencias) >= 2` | Recado 070: se pasaban horas "bare" repetidas como id; se corrigió usando `slot_id` único como id y la hora legible como `text` |
| S4 | El proposer que lanza una excepción se captura → `none`. Nunca se propaga. | `try/except Exception` | Recados 052/037 (el LLM puede fallar por red, API o JSON) |
| S5 | Sin opciones o sin proposer → `none` sin llamar a nada (cero red). | early return | Diseño: el default es seguro |
| S6 | `interpret_selection` **no** hace matching determinista propio. Eso es responsabilidad del dominio, que debe agotarlo antes. | contrato documental | Recado 052 |
| S7 | Un id aceptado se trata **igual** que un ordinal tecleado: mismo `tool_requerida`, misma `confirmacion_estructurada_para_write`. | test de equivalencia (ver A.3) | Recado 052 |
| S8 | Prompt del proposer real: JSON estricto `{"option_id": ...}`, `null` si hay ambigüedad, ignorar instrucciones incrustadas en el mensaje del usuario. JSON inválido → `None`. Un valor que no es string → `None`. | `json.loads` + `isinstance(str)` | Recado 052 |
| S9 | **Criterio de cuándo llamar** (vive en el dominio): solo si el matching determinista no encontró **ningún** candidato. Si encontró candidatos ambiguos, no se llama al LLM; se muestra la aclaración con los candidatos reales. | `domains/health/brain.py:_interpretar_fecha/_interpretar_horario` | Recados 051/052 (costo, latencia, y la ambigüedad ya es información útil) |
| S10 | **Uso como clasificador cerrado**: el mismo mecanismo clasifica intención de menú e interrupciones de wizard contra un diccionario fijo `id → descripción`, con una opción explícita de "ninguna de las anteriores" (`"es_el_dato"`) que mejora la precisión. | `gateway.py:_CATEGORIAS_MENU_LLM`, `_CATEGORIAS_WIZARD_LLM` | Recados 064/068 |
| S11 | En el uso como clasificador, el LLM **solo clasifica**: nunca produce ni modifica el valor (código de verificación, documento). | `test_llm_nunca_ejecuta_una_accion_real_sin_el_codigo_verificado` | Recado 064 |

#### A.3 Tests que sirven de ejemplo [CONFIRMADO: existen y pasan]

`tests/core/test_selection.py` (dominio neutro: trámites ficticios):

- `test_interpreta_la_del_medio`, `test_interpreta_esa_que_dijiste_primero`, `test_interpreta_referencia_por_nombre_de_la_opcion`: resolución de lenguaje natural mediante un doble de proposer realista.
- `test_rechaza_un_id_alucinado_que_no_existe_en_las_opciones`: regla S2.
- `test_rechaza_id_ambiguo_por_opciones_del_dominio_con_ids_duplicados`: regla S3.
- `test_none_propuesto_por_el_llm_no_es_un_error_es_sin_seleccion`, `test_sin_proposer_configurado_devuelve_ninguna_seleccion_sin_fallar`, `test_proposer_que_falla_se_captura_y_devuelve_ninguna_seleccion`, `test_sin_opciones_ofrecidas_devuelve_ninguna_seleccion_sin_llamar_al_proposer`: reglas S4 y S5.
- Dobles reutilizables: `_ProposerFijo` (contrato), `_ProposerQueFalla` (red/API), `_ProposerRealistaLenguajeNatural` (simula al LLM sin vocabulario de dominio).

`tests/domains/health/test_seleccion_asistida_por_llm.py` (dominio de salud; útil como patrón de integración, sin copiar fixtures):

- `test_no_avanza_si_el_llm_alucina_una_opcion_que_no_fue_ofrecida`, `test_no_avanza_ni_reserva_si_el_llm_alucina_un_horario`: la alucinación nunca llega a una WRITE.
- `test_ordinal_y_texto_exacto_del_recado_051_nunca_llaman_al_proposer`: regla S9 (el determinista va primero).
- `test_seleccion_via_llm_produce_decision_identica_a_elegir_por_ordinal`: regla S7. Es **el test más valioso para el paquete**, porque prueba equivalencia de decisión y no solo el resultado.
- `test_de_extremo_a_extremo_por_el_orchestrator_y_guardrails_reales`: la segunda capa no bloquea selecciones legítimas.

`tests/domains/health/test_interpretacion_asistida_generalizada.py`: uso como clasificador (S10 y S11). Se destacan `test_menu_rechaza_propuesta_alucinada_del_llm`, `test_llm_nunca_ejecuta_una_accion_real_sin_el_codigo_verificado` y `test_llm_nunca_confirma_identidad_sin_el_codigo_real`. Los `test_real_*` solo corren con `ZANTIA_RUN_REAL_LLM_TESTS=1`.

---

### B. `core/timed_state.py`: estado con timestamp real y ventana configurable

#### B.1 Interfaz pública [CONFIRMADO]

```python
class ModoVentana(str, Enum): BLOQUEO = "bloqueo"; ABIERTA = "abierta"   # solo metadata, nunca leída por el store

@dataclass(frozen=True)
class VentanaDeTiempo:
    duracion: timedelta
    modo: Optional[ModoVentana] = None
    nombre: str = ""

class TimedStateStore:
    registrar(clave: str, payload: Any = None, *, ahora: Optional[datetime] = None) -> None   # reemplaza TODO, timestamp incluido
    actualizar_payload(clave: str, payload: Any) -> bool       # preserva el momento; False si no existe (nunca crea)
    obtener_payload(clave: str) -> Optional[Any]
    momento_de(clave: str) -> Optional[datetime]
    existe(clave: str) -> bool ; __contains__
    limpiar(clave: str) -> None
    transcurrido(clave, *, ahora=None) -> Optional[timedelta]   # None ≠ timedelta(0)
    dentro_de_ventana(clave, ventana, *, ahora=None) -> bool    # False si no hay entrada O si venció
    tiempo_restante(clave, ventana, *, ahora=None) -> Optional[timedelta]  # nunca negativo (clamp a 0)
```

#### B.2 Reglas y comportamientos [CONFIRMADO]

- T1: el tiempo restante se **calcula en el momento de la consulta** contra el timestamp guardado. Nunca hay un cronómetro que se actualiza solo. Origen: recado 069, el mensaje de enfriamiento con tiempo restante real.
- T2: **varias ventanas anidadas sobre el mismo timestamp**. En producción conviven un enfriamiento de 2 min (BLOQUEO) dentro de un saludo corto de 30 min (sin modo). Origen: recados 057 y 067.
- T3: `ABIERTA` se soporta estructuralmente con `actualizar_payload`: se acumula contenido sin extender el plazo. No hay ningún uso real todavía; está pensado para el dominio futuro de seguridad ciudadana (`.ai/CORE_REUSABLE_PATTERNS.md`).
- T4: el redondeo para mostrar el tiempo al usuario es responsabilidad del dominio. En salud se usa `int(segundos) + 1`, para no decir nunca "0 segundos" mientras el bloqueo sigue activo (`gateway.py:748-750`).
- T5: el reloj es UTC-aware (`datetime.now(timezone.utc)`). `ahora=` existe solo para tests.
- T6 (error real que motivó endurecer el uso): el enfriamiento **no se armaba** en uno de los caminos, una despedida sin conversación abierta (recados 070/071). El store no podía detectarlo: fue un fallo del llamador. La lección para el paquete es documentar "registrar en TODOS los caminos de cierre" y probarlo con tests de regresión por camino.

#### B.3 Tests de ejemplo [CONFIRMADO]

`tests/core/test_timed_state.py`:

- `test_bloqueo_informa_tiempo_restante_real_mientras_dura_la_ventana`
- `test_bloqueo_tiempo_restante_disminuye_con_tiempo_real_transcurrido`
- `test_bloqueo_deja_de_aplicar_pasada_la_ventana`
- `test_transcurrido_y_dentro_de_ventana_none_si_nunca_se_registro`
- `test_registrar_reemplaza_por_completo_una_entrada_existente`
- `test_modo_abierta_acepta_contenido_nuevo_sin_reiniciar_la_ventana`
- `test_modo_abierta_ventana_vencida_ya_no_deberia_aceptar_mas_contenido`
- `test_actualizar_payload_no_crea_una_entrada_nueva_implicitamente`
- `test_limpiar_borra_la_entrada`

Regresión de uso (dominio): `tests/domains/health/corpus_regresion/test_recado070_despedida_sin_conversacion_no_armaba_enfriamiento.py` (dos tests, uno por camino) y `test_auditoria_salida_y_cierre_formal.py::test_enfriamiento_informa_tiempo_restante_real`, `::test_reserva_confirmada_nunca_activa_el_enfriamiento`.

---

### C. Guardrails (`guardrails/base.py`, `engine.py`, `rules.py`)

#### C.1 Interfaz pública [CONFIRMADO]

```python
class GuardrailDecision(str, Enum): ALLOW, MODIFY, BLOCK, ESCALATE

@dataclass class VerificacionDeDatos:       nombre_categoria: str; patron: str (regex, re.findall); valores_permitidos: List[str]
@dataclass class VerificacionDeSeleccion:   opciones_reales_ids: List[str]; id_seleccionado_via_llm: Optional[str] = None

@dataclass class GuardrailContext:
    state: ConversationState                  # ← acoplamiento al modelo del proyecto
    proposed_state_changes: Dict[str, Any]
    proposed_tool: Optional[str]
    proposed_response: str
    mensaje_entrante: str = ""
    verificaciones_de_datos: List[VerificacionDeDatos] = []
    confirmacion_estructurada_para_write: bool = False
    texto_base_para_comparacion: Optional[str] = None
    verificacion_de_seleccion: Optional[VerificacionDeSeleccion] = None

@dataclass class GuardrailResult:
    decision; reason: str; modified_response: Optional[str] = None
    forced_state_changes: Dict[str, Any] = {}; guardrail_name: str = ""

class Guardrail(Protocol): name: str; def evaluate(self, context) -> GuardrailResult

class GuardrailEngine:
    __init__(rules: List[Guardrail]); evaluate(context) -> GuardrailResult

def reglas_core_por_defecto(tool_categories: Dict[str, ToolCategory]) -> List[Guardrail]   # fuente única del orden
```

Semántica del engine:

- Evalúa **todas** las reglas, sin cortocircuito.
- La decisión final es la de mayor severidad: ESCALATE > BLOCK > MODIFY > ALLOW.
- `modified_response`: gana el **último** MODIFY en orden de registro. Se toma aunque la decisión ganadora sea BLOCK o ESCALATE, pero en esos casos el orquestador lo ignora.
- `forced_state_changes` se fusionan de todas las reglas, con `dict.update` en orden.
- `reason` concatena `[nombre] razón` de todas las reglas.

#### C.2 Reglas concretas, su error de origen y cómo detectan

| Regla | Decisión | Detecta | Error real / origen |
|---|---|---|---|
| `SenalDeUrgenciaNoSePuedeBajarGuardrail` | ESCALATE | `state.senal_de_urgencia is True` y la propuesta la pone en `False` | Diseño 004 §2.2: solo una regla determinista puede tocar la urgencia |
| `ConsentimientoRequeridoParaWriteGuardrail` | BLOCK | tool WRITE sin `consentimiento_datos` (del estado o de la propuesta) | Diseño 004 §17 |
| `NoPrometerContactoGuardrail` | MODIFY | frases de promesa de contacto ("te llamamos", "en breve te"...) | Lección de un agente previo que lo prohibía solo por prompt (recado 002) |
| `DatoInventadoGuardrail` | BLOCK | cada match de `patron` en la respuesta debe estar en `valores_permitidos`, **sin distinguir mayúsculas** | Recado 037. **Recado 041**: el LLM escribía los días en minúscula y el patrón no encontraba ninguna candidata, así que el guardrail quedaba mudo; se corrigió con `(?i)` en el patrón y normalización de la comparación. **Recado 043**: fechas elípticas ("sábado 5, domingo 6 o lunes 7 de septiembre") quedaban invisibles; se agregó la forma corta al patrón **y** a los permitidos, porque de lo contrario habría bloqueado fechas reales. **Recado 066**: se extendió a teléfono, correo y dirección, para detectar el caso "un dígito cambiado" |
| `TipoDePreguntaAlteradaGuardrail` | MODIFY → restaura el texto base | el texto base era una pregunta de selección ("¿Cuál…?" o ≥2 marcadores numerados) y la respuesta ya no lo es | **Recado 038/039, caso 2 real**: el LLM convirtió "¿Cuál prefieres?" en "¿Confirmamos esa cita?". No inventó datos, pero rompía la interpretación del turno siguiente. **Recado 054**: el formato de lista cambió a `1.` con salto de línea y se agregó la alternativa al regex |
| `ConfirmacionEstructuradaRequeridaParaWriteGuardrail` | BLOCK | tool WRITE y `confirmacion_estructurada_para_write` en False | Recado 037: convierte la disciplina de cada Brain en un contrato auditable, **fail-safe por defecto** |
| `FueraDeAlcanceGuardrail` | MODIFY | frases de manipulación en el **mensaje entrante** (ES y EN) | Recado 037 |
| `OpinionPersonalGuardrail` | MODIFY | marcadores de opinión en primera persona en la **respuesta**, agnósticos del tema | **Recado 042, caso 6**: presión cortés sostenida sin frases de manipulación explícitas; faltaba una capa de código. Se verificó que no bloquea la empatía hacia el paciente ("lamento que te sientas así") |
| `SeleccionAsistidaPorLLMNoVerificadaGuardrail` | BLOCK | `id_seleccionado_via_llm` ∉ `opciones_reales_ids` | Recado 052: segunda capa independiente de S1 |

La **confirmación estructurada antes de una escritura** funciona de punta a punta así [CONFIRMADO]:

1. El Brain determinista solo pone `confirmacion_estructurada_para_write=True` cuando la selección vino de un ordinal real, de un match determinista de texto o de un LLM **ya verificado**. Por ejemplo, `domains/health/brain.py:1958`, `2141` y `2165` (reserva, cancelación y reprogramación).
2. En el Brain de ejemplo del Core (`FakeBrain`) hay un turno explícito "¿Confirmas…? Responde sí o no" con reconocimiento `\bs[ií]\b`.
3. El guardrail bloquea si falta la declaración.
4. `HealthAnthropicBrain` copia `tool_requerida` y `confirmacion_estructurada_para_write` **sin tocarlos**: el LLM redactor solo cambia el texto.

#### C.3 Tests de ejemplo [CONFIRMADO]

- `tests/guardrails/test_guardrails.py`: `test_bloquea_write_sin_consentimiento`, `test_permite_write_con_consentimiento`, `test_permite_read_sin_consentimiento`, `test_escala_si_se_intenta_bajar_senal_de_urgencia`, `test_modifica_respuesta_con_promesa_prohibida`.
- `tests/guardrails/test_guardrails_pre_llm.py`: `test_dato_inventado_*` (4 tests, incluido `..._permite_por_defecto_sin_verificaciones_declaradas`, que es el default seguro), `test_bloquea_tool_write_sin_confirmacion_estructurada`, `test_permite_tool_write_con_confirmacion_estructurada`, `test_no_bloquea_tool_read_aunque_falte_confirmacion`, `test_no_bloquea_sin_tool_propuesta`, `test_redirige_intento_de_manipulacion_ignora_instrucciones`, `test_reconoce_variante_en_ingles_del_intento_de_manipulacion`, `test_permite_mensaje_entrante_normal`.
- `tests/guardrails/test_tipo_de_pregunta_alterada.py`: `test_caso_2_real_queda_bloqueado_y_se_restaura_el_texto_base` (reproduce el error real), `test_caso_1_real_reformulacion_valida_no_se_bloquea` (sin falso positivo), `test_sin_texto_base_para_comparacion_nunca_interfiere`, `test_texto_base_sin_pregunta_de_seleccion_no_interfiere`, `test_pregunta_de_seleccion_preservada_con_lista_numerada_en_ambos`.
- `tests/guardrails/test_opinion_personal.py`: `test_bloquea_una_opinion_politica_forzada`, `test_bloquea_otras_formas_de_opinion_personal`, `test_no_bloquea_el_reconocimiento_empatico_real_del_recado_042`, `test_no_bloquea_respuestas_normales_sin_ninguna_opinion`.
- `tests/guardrails/test_seleccion_llm_guardrail.py`: 4 tests (bloquea el alucinado, permite el verificado, permite si no hubo LLM, permite si no hay verificación).
- `tests/domains/health/test_confirmacion_estructurada_write.py`: los 3 caminos WRITE del dominio declaran confirmación, más la reserva real que pasa.
- `tests/domains/health/test_llm_brain.py`: dobles `_DrafterQueParafrasea`, `_DrafterQueAlucina`, `_DrafterQueFalla`, `_DrafterQueOpinaDePolitica` y `_DrafterQueCambiaTipoDePregunta`. Tests: `test_redacta_el_texto_pero_preserva_la_decision_determinista`, `test_si_el_drafter_falla_usa_el_texto_determinista_sin_romper`, `test_construir_verificaciones_categoria_vacia_si_no_aparece_en_el_base` (una categoría vacía bloquea cualquier valor inventado de esa categoría) y los de extremo a extremo `test_guardrail_bloquea_una_alucinacion_del_llm_de_extremo_a_extremo`, `test_guardrail_de_tipo_de_pregunta_restaura_el_texto_base_reproduciendo_caso_2`.

---

### D. Orquestador (`core/orchestrator.py`)

#### D.1 Interfaz pública [CONFIRMADO]

```python
class Orchestrator:
    __init__(state_store: StateStore, memory: ConversationMemoryProtocol, brain: Brain,
             tool_registry: ToolRegistry, event_log: EventLogProtocol,
             guardrail_engine: Optional[GuardrailEngine] = None)   # default: reglas_core_por_defecto(...)
    handle_message(conversation_id: str, canal: str, message_id: str, text: str) -> OrchestratorResult
    # propiedades de solo lectura: tools, events, brain, store

@dataclass class OrchestratorResult: response: str; state: ConversationState; escalated: bool

def detect_risk_keywords(text: str) -> bool

# Contrato del Brain (core/brain.py)
class Brain(Protocol): def interpret(message, state, recent_turns) -> BrainOutput
class BrainOutput(BaseModel): intencion, nivel_de_confianza ("BAJO|MEDIO|ALTO"), proxima_accion_propuesta,
    propuesta_de_actualizacion_de_estado, tool_requerida ({"name","params"}), respuesta_propuesta,
    senales_detectadas, verificaciones_de_datos, confirmacion_estructurada_para_write,
    texto_base_para_comparacion, verificacion_de_seleccion
```

#### D.2 Pipeline de `handle_message`, en orden [CONFIRMADO]

1. **Deduplicación** por `conversation_id:message_id`, en memoria de proceso: se devuelve la respuesta ya dada.
2. Se obtiene o crea el estado y se guarda el turno del usuario en memoria.
3. En estado terminal (escalado) se responde con un mensaje fijo y **no se reprocesa**.
4. En `CIERRE` se reabre el ciclo: se limpian los datos del objetivo, pero **no** el riesgo ni el consentimiento.
5. **El riesgo se detecta ANTES de llamar al Brain**. Origen (recado 037, parte 4): si el Brain LLM lanzaba una excepción, un mensaje urgente se perdía.
6. Si el Brain lanza una excepción, se escala: urgente si hubo riesgo, estándar si no. Queda auditado en el EventLog.
7. Si hay riesgo, se fuerzan `senal_de_urgencia`, `nivel_de_riesgo=ALTO` y `necesidad_de_escalar` sobre la propuesta.
8. Se arma `GuardrailContext` con **todos** los campos de verificación del `BrainOutput`, se evalúa y se registra `GUARDRAIL_DECISION`.
9. ESCALATE → escalar urgente. BLOCK → responder "No puedo continuar…" **sin avanzar el estado**.
10. La respuesta final es `modified_response or respuesta_propuesta`, y se fusionan los `forced_state_changes`.
11. Prioridad de interrupciones: RIESGO > ESCALAMIENTO SOLICITADO > (dato faltante / acción / conversación).
12. Se ejecuta la tool:
    - Si la tool no existe o lanza `ToolError`, se **escala de verdad**, con transición de fase. Origen (prompt 007): antes devolvía `escalated=True` sin transicionar.
    - Si `success=False`, **se reemplaza el texto optimista del Brain** por "No pude completar esa acción…". Origen (recado 007): no declarar confirmado lo que el sistema no confirmó.
13. Siguiente fase y `validate_transition`. Una transición inválida escala. Excepción documentada (**recado 047**): `preguntar_intencion` desde una fase avanzada antes escalaba la conversación por una pregunta inocua; ahora hace un auto-bucle en la fase actual.
14. Guardado con **concurrencia optimista y un reintento** (`expected_version`).
15. Se registra el turno del agente y se cachea la respuesta para la deduplicación.

Frases fijas de escalamiento: **no prometen contacto ni tiempo** (lección del recado 002).

#### D.3 Tests de ejemplo [CONFIRMADO]

- `tests/core/test_orchestrator_e2e.py`: `test_conversacion_normal_de_extremo_a_extremo`, `test_interrupcion_prioritaria_por_riesgo`, `test_riesgo_gana_sobre_cualquier_otra_intencion_simultanea`, `test_conversacion_no_se_reprocesa_tras_escalado_urgente`.
- `tests/core/test_riesgo_independiente_del_brain.py`: `test_mensaje_de_riesgo_escala_urgente_aunque_el_brain_falle`, `test_mensaje_sin_riesgo_escala_estandar_si_el_brain_falla_en_vez_de_crashear`, `test_fallo_del_brain_queda_auditado_en_eventlog` (doble `_BrainQueSiempreFalla`).

---

## Arquitectura / estructura encontrada

```
Canal (Telegram/Chatwoot/web) → service/app.py (FastAPI)
  → domains/health/gateway.py  (HealthGateway: identidad, wizards, menú, TimedStateStore, SelectionProposer como clasificador)
    → core/orchestrator.py  (autoridad única de escritura de estado)
         ├─ core/brain.py: Brain Protocol / BrainOutput
         │     └─ domains/health/llm_brain.py: HealthAnthropicBrain = HealthBrain determinista + ResponseDrafter (LLM solo redacta)
         │           └─ domains/health/brain.py: matching determinista → interpret_selection (último recurso)
         ├─ guardrails/ (engine + 9 reglas)
         ├─ tools/ (ToolRegistry, ToolCategory READ/WRITE/NOTIFY)
         ├─ state/ (ConversationState, machine, StateStore con versión)
         ├─ memory/ (ConversationMemory)
         └─ observability/ (EventLog)
```

El LLM aparece en **tres roles**, todos con el mismo principio:

| Rol | Clase | Qué puede hacer | Verificación |
|---|---|---|---|
| Selector | `AnthropicSelectionProposer` | proponer un id | S1–S3 + guardrail de selección |
| Clasificador | el mismo proposer con un diccionario de categorías | proponer una categoría | S1–S3 (sin segunda capa: no escribe nada) |
| Redactor | `AnthropicResponseDrafter` | reescribir el texto | DatoInventado + TipoDePreguntaAlterada + OpinionPersonal + NoPrometerContacto |

Nunca decide tools, WRITE, estado ni urgencia. `AnthropicBrain` (Core) existe pero **no se usa en producción**: es un Brain LLM completo documentado como pendiente de prueba en vivo desde el recado 006.

Activación: `HEALTH_BRAIN_TYPE=llm` + `ANTHROPIC_API_KEY`. Si falta la clave, se degrada **en silencio con un warning** al modo determinista y nunca falla al arrancar (`domains/health/config.py:130-150`).

---

## Archivos importantes

- `/Users/enzoalfonso/Orangutan/icaco/core/selection.py` (200 líneas)
- `/Users/enzoalfonso/Orangutan/icaco/core/timed_state.py` (208)
- `/Users/enzoalfonso/Orangutan/icaco/guardrails/base.py` (104), `engine.py`, `rules.py` (500)
- `/Users/enzoalfonso/Orangutan/icaco/core/orchestrator.py` (416), `core/brain.py` (250)
- `/Users/enzoalfonso/Orangutan/icaco/domains/health/llm_brain.py` (314): redactor y construcción de `VerificacionDeDatos`
- `/Users/enzoalfonso/Orangutan/icaco/domains/health/brain.py:1673-1715` (`_interpretar_seleccion_asistida_por_llm`), `:1720+` (fecha), `:1870-1960` (horario → WRITE)
- `/Users/enzoalfonso/Orangutan/icaco/domains/health/gateway.py:341-380` (ventanas), `:745-750` (enfriamiento), `:1062-1101` (menú vía LLM), `:1945-1985` (wizard vía LLM)
- `/Users/enzoalfonso/Orangutan/icaco/domains/health/config.py:130-150` (gate de activación)
- `/Users/enzoalfonso/Orangutan/icaco/.ai/CORE_REUSABLE_PATTERNS.md`: documento previo sobre lo que hereda un dominio futuro (timed_state + diseño ABIERTA)
- Recados previos directamente relacionados: 037, 038, 039, 052, 076 (y 041, 042, 043, 054, 064, 066, 070, citados en el código)

---

## Decisiones o conclusiones

### 4. Qué está atado al proyecto y qué es genérico

| Elemento | Genérico | Atado a ZANTIA |
|---|---|---|
| `selection.py` | Todo el contrato (`SelectionOption`, `SelectionResult`, `SelectionProposer`, `interpret_selection`) | `AnthropicSelectionProposer`: proveedor, modelo por defecto `"claude-sonnet-5"`, nombre de la variable de entorno, prompt en español, logger `"zantia.core"` |
| `timed_state.py` | Todo | Solo docstrings y comentarios que citan recados y gateway; nombres en español (`registrar`, `limpiar`...) |
| `guardrails/base.py` + `engine.py` | Engine, decisiones, `VerificacionDeDatos`, `VerificacionDeSeleccion`, `Guardrail` Protocol | `GuardrailContext.state: ConversationState` (modelo pydantic del proyecto). Los nombres de campos de estado que leen las reglas (`senal_de_urgencia`, `consentimiento_datos`) son del proyecto |
| Reglas de mecanismo | `DatoInventado`, `SeleccionNoVerificada`, `ConfirmacionEstructurada`, `Consentimiento`, `SenalDeUrgencia` | La comparación de categoría de tool usa `categoria.value == "WRITE"` (duck typing sobre `ToolCategory`) |
| Reglas de lenguaje | La **forma** (lista de frases o marcadores → MODIFY) | **Idioma español**: `¿cuál`, frases de manipulación (más algunas en inglés), marcadores de opinión, promesas prohibidas. **Dominio salud dentro del Core**: `_MENSAJE_REDIRECCION_FUERA_DE_ALCANCE` dice "Solo puedo ayudarte con la gestión de tu cita" |
| Patrones de `VerificacionDeDatos` | El mecanismo | Todos los regex viven en `domains/health/llm_brain.py`: fechas en español, teléfono con formato `NNN-NNNNNNN`, dirección colombiana "Carrera 17 # 57-119" |
| Orquestador | El pipeline (orden de prioridades, riesgo antes del Brain, BLOCK sin avance, reemplazo del texto optimista ante un fallo de tool, concurrencia optimista, deduplicación) | `ConversationState`/`FaseActual`/`Modo`/`VALID_TRANSITIONS` (la máquina de estados del proyecto), `RISK_KEYWORDS_DEMO` (placeholder en español, **no clínico**), mensajes fijos en español, nombres de `proxima_accion_propuesta` ("preguntar_intencion", "preguntar_dato_faltante", "ejecutar_tool") |
| Canal | Nada del Core depende del canal | Canal y identidad viven en `gateway.py`/`channels/`, fuera de estos 4 elementos |

### 5. Dependencias externas y qué habría que abstraer

| Dependencia | Dónde | Abstracción propuesta [PROPUESTO] |
|---|---|---|
| `anthropic` SDK (import perezoso) | `AnthropicSelectionProposer`, `AnthropicResponseDrafter`, `AnthropicBrain` | Mantener `SelectionProposer`/`ResponseDrafter` como Protocol en el núcleo y mover los adaptadores a un extra opcional (`pkg[anthropic]`). Parametrizar el prompt, `max_tokens` y el **timeout** (hoy no se pasa ninguno) |
| `os.environ` para la API key | adaptadores | Inyectar el cliente o la key por constructor; el env var solo en la capa de composición |
| `pydantic` v2 | `BrainOutput`, `ConversationState` | El núcleo puede usar `dataclasses` sin dependencias. Pydantic queda solo si se exporta `BrainOutput` |
| `ConversationState` | `GuardrailContext`, orquestador | Protocol mínimo (`senal_de_urgencia`, `consentimiento_datos`) o `Mapping[str, Any]` |
| `ToolCategory`/`ToolRegistry` | reglas WRITE, orquestador | Inyectar un callable `es_write(tool_name) -> bool` en vez de un diccionario de enums |
| `StateStore`, `ConversationMemoryProtocol`, `EventLogProtocol`, máquina de estados | orquestador | Ya son Protocols en parte. La máquina de estados habría que volverla inyectable (tabla de transiciones y fases terminales) |
| Reloj (`datetime.now(timezone.utc)`) | timed_state | Inyectar `clock: Callable[[], datetime]` en el constructor, en lugar del kwarg `ahora=` en cada método (conservando `ahora=` por compatibilidad) |
| Almacenamiento en memoria de proceso | timed_state, dedup del orquestador | Interfaz `TimedStateBackend`, con backend en memoria por defecto (R-11 ya documenta la limitación) |
| `logging` con nombres `zantia.*` | todos | Usar `logging.getLogger(__name__)` |
| Listas de frases en español | 4 reglas | Pasarlas por constructor (`frases=`, `mensaje_redireccion=`), con paquetes de idioma `es` como default opcional |

### 6. Propuesta de orden de extracción [PROPUESTO / RECOMENDACIÓN]

1. **Primero: `selection` + `timed_state` + los guardrails de verificación con su engine.** Los guardrails de esta entrega son `DatoInventado`, `SeleccionAsistidaPorLLMNoVerificada`, `ConfirmacionEstructuradaRequeridaParaWrite` y `TipoDePreguntaAlterada` (con el detector de pregunta parametrizable). Motivos:
   - Tienen cero o casi cero acoplamiento: `selection` y `timed_state` no importan nada del proyecto.
   - Son el valor diferencial real ("el LLM nunca actúa sin verificación").
   - Traen tests neutros ya escritos (`test_selection.py`, `test_timed_state.py`, `test_guardrails_pre_llm.py`, `test_seleccion_llm_guardrail.py`) que se pueden portar casi sin cambios.
   - Para que los guardrails queden desacoplados basta con cambiar `GuardrailContext.state` por un Protocol mínimo.
2. **Segundo: adaptador Anthropic opcional** (`pkg[anthropic]`) con proposer y drafter, prompt parametrizable, timeout y cliente inyectable. Incluir los helpers genéricos para construir `VerificacionDeDatos` a partir de un "texto base" (la técnica de `_construir_verificaciones_de_datos`: extraer del texto determinista, siempre todas las categorías aunque estén vacías). Los regex concretos van como ejemplo, no en el núcleo.
3. **Tercero: reglas de lenguaje** (FueraDeAlcance, OpinionPersonal, NoPrometerContacto), con frases y mensaje inyectables y un paquete de idioma `es`. El mensaje de redirección debe dejar de mencionar "cita".
4. **Último: el orquestador.** Es el más acoplado: estado, máquina de estados, stores, memoria, eventos y tools. Conviene extraerlo solo cuando exista un segundo dominio real (por ejemplo seguridad ciudadana) que confirme qué partes del pipeline son de verdad comunes. Antes de eso, conviene resolver la decisión MODIFY + tool descrita abajo.

Motivo del orden: se va de menor a mayor acoplamiento y de mayor a menor ratio valor/riesgo. Además respeta `.claude/rules/aislamiento-entre-proyectos.md`: se publica como paquete versionado y no se copia a mano entre proyectos.

---

## Problemas encontrados

1. **MODIFY no detiene la ejecución de tools, incluidas las WRITE** [CONFIRMADO por lectura de `core/orchestrator.py`, sin test que lo cubra].
   - Si el veredicto consolidado es MODIFY (por ejemplo, `FueraDeAlcanceGuardrail` detecta "ignora tus instrucciones" en el mensaje entrante), el flujo sigue: se ejecuta `brain_output.tool_requerida` y la respuesta final pasa a ser el texto de redirección.
   - Escenario teórico: el usuario manda en un solo mensaje una selección válida y una frase de manipulación. El Brain determinista propone una WRITE con confirmación estructurada. La WRITE **se ejecuta**, pero el usuario recibe "Solo puedo ayudarte con la gestión de tu cita…", sin enterarse de que se reservó.
   - [INFERIDO] Es alcanzable en el dominio de salud si el matching de ordinal acepta un mensaje que además contenga la frase. No se reprodujo, porque era solo lectura.
   - El paquete debe decidirlo de forma explícita: o MODIFY con tool WRITE pasa a BLOCK, o la respuesta modificada debe conservar la confirmación del resultado.
2. **Regla del Core con vocabulario de dominio**: `_MENSAJE_REDIRECCION_FUERA_DE_ALCANCE` menciona "tu cita" dentro de `guardrails/rules.py` (Core). Tensiona la regla de agnosticismo de dominio del propio proyecto.
3. **`TimedStateStore` nunca se purga en producción** [CONFIRMADO: `gateway.py` solo llama a `registrar`, `obtener_payload`, `dentro_de_ventana` y `tiempo_restante`, nunca a `limpiar`]. [INFERIDO] Las entradas crecen sin límite por `patient_reference` durante la vida del proceso. Hoy el impacto es bajo (un proceso que se reinicia en cada deploy), pero el paquete debería ofrecer una expiración o un `purgar_vencidas(ventana_max)`.
4. **Sin thread-safety** en `TimedStateStore` ni en la deduplicación del orquestador (un `dict` sin lock). [INFERIDO] Es aceptable con un solo worker, pero es un riesgo si el paquete se usa con varios hilos.
5. **Adaptadores Anthropic sin timeout explícito** y con un cliente nuevo en cada llamada. Además, `free_text` se interpola entre comillas sin escapar. El riesgo de inyección está mitigado por S1 (el resultado se verifica igual), pero conviene documentarlo.
6. **`DatoInventadoGuardrail` usa `re.findall`**: un patrón con grupos de captura devolvería tuplas o grupos en vez del match completo. El código de salud lo sabe (usa solo `(?:...)`), pero el contrato del paquete debe **exigir patrones sin grupos de captura** o usar `finditer(...).group(0)`.
7. La clasificación de menú y wizard vía LLM (gateway) **no pasa por la segunda capa de guardrail** porque ocurre fuera del orquestador. Es aceptable porque solo clasifica y no escribe (S11), pero hay que documentarlo como una diferencia de garantía.

## Riesgos

- Extraer el orquestador demasiado pronto fijaría como "genérica" una máquina de estados que solo validó un dominio.
- Portar los guardrails de lenguaje sin parametrizar el idioma produciría falsos negativos silenciosos en otro idioma. Es el mismo tipo de hueco que el recado 041 (el guardrail "mudo").
- Al traducir `DatoInventadoGuardrail` a otro dominio, si el patrón no reconoce el formato real que usa el LLM, la regla **nunca dispara** y no avisa. El paquete debería traer un test-plantilla del tipo "el patrón encuentra al menos una candidata en el texto base".

## Recomendaciones

- RECOMENDACIÓN: portar tal cual al paquete, como suite de conformidad, los tests neutros de `tests/core/test_selection.py`, `tests/core/test_timed_state.py`, `tests/guardrails/*`, más una versión neutralizada de `test_seleccion_via_llm_produce_decision_identica_a_elegir_por_ordinal`.
- RECOMENDACIÓN: añadir en el paquete un test que falla hoy para el problema 1 (MODIFY + WRITE) y decidir la semántica antes de publicar el orquestador.
- RECOMENDACIÓN: registrar la extracción como decisión en `.ai/DECISIONS.md`/`docs/decisions/`, con el formato obligatorio del proyecto, cuando se ejecute (no en este recado, que es solo lectura).

## Información que debe conocer ChatGPT

- El proyecto etiqueta sus afirmaciones como `[CONFIRMADO]`/`[INFERIDO]`/`[PROPUESTO]`/`[DESCONOCIDO]`, y este recado lo respeta.
- Todos los tests citados pasan hoy en local (633 passed, 17 skipped en la suite completa). Ninguno se ejecutó contra la API real de Anthropic ni contra el backend HRMM.
- En producción, el LLM **solo redacta, selecciona y clasifica**. Ninguna decisión de escritura depende de él sin verificación determinista.
- `AnthropicBrain` (un Brain 100% LLM) existe en el código, pero **no se usa** y nunca se probó en vivo.
- No se contradice ningún recado previo. Este amplía el 052 (selection) y el 076 (timed_state) con la especificación orientada a paquete, y agrega los problemas 1, 3, 4 y 6, que no estaban documentados en esos recados.

## Preguntas pendientes

1. ¿El paquete se publica en un registro privado o como repo git versionado? Afecta cómo lo consumirían ZANTIA y otros proyectos de Orangutan.
2. ¿Los nombres de la API pública se mantienen en español (`registrar`, `dentro_de_ventana`) o se pasan a inglés? Si se cambian, hace falta un período de convivencia (`.claude/rules/contratos-api.md`).
3. ¿Qué semántica se quiere para MODIFY cuando hay una tool WRITE propuesta: bloquear o ejecutar y avisar?
4. ¿Qué idiomas debe soportar el paquete desde el día 1?
5. [DESCONOCIDO] Si algún otro proyecto de Orangutan ya consume o copió alguno de estos módulos. No se verificó fuera de este repo.

---

Cierre: 2026-09-28 13:20:43. Tiempo total medido: ~4 minutos (lectura de 10 módulos, inventario de 12 archivos de tests, 2 corridas locales de pytest y redacción).
