# 047 — Corrección estructural: las 5 categorías de interrupción ahora se revisan en CUALQUIER etapa

**Fecha**: 2026-09-06
**Estado**: Implementado y probado. 337 passed, 4 skipped (329 previas + 8 nuevas). Cero regresiones. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo del repo.

---

## 0. Acciones previas de este mismo trabajo (ya reportadas, reconfirmadas aquí)

- **`CITA-1bbb8bc467` — reconfirmada CANCELLED** con una consulta real nueva (`HrmmAppointmentService.get_appointment`, hrmm-backend real): `status=CANCELLED`, documento `72302972`, Odontologia, 2026-09-07 08:00, Consultorio 4. La cancelación misma (código de verificación `118508`) ya se había ejecutado y confirmado en el turno anterior de esta sesión — esta es una reconfirmación, no una nueva acción.
- **Parte 2 del recado 046 (saludo institucional + menú)** ya estaba commiteada y pusheada antes de este trabajo: `git rev-parse HEAD` y `git ls-remote origin main` coinciden en `f37e24d`. Ningún cambio adicional a la heurística de tratamiento formal (señor/señora) — se mantiene tal como está, por pedido explícito.

---

## 1. El problema (diagnosticado sin corregir en el recado 046)

5 categorías de interrupción — `_PARA_OTRO` (beneficiario), `_INFO_NO_AUTORIZADA`, `_HUMANO`, `_NO_PUEDE_AHORA`, `_PIDE_INFO` — solo se revisaban dentro de `_interpretar_decision`, el manejador de la ETAPA `esperando_decision` (el primer turno de la conversación). Un paciente que las mencionara en cualquier etapa posterior (`esperando_servicio`, `esperando_fecha`, `esperando_horario`, etc.) nunca las activaba — el caso real de producción de hoy ("Odontologia pero es para mi hija", dicho en `esperando_servicio`) es el ejemplo concreto: la reserva terminó a nombre del titular, no de la beneficiaria.

En contraste, `_OLVIDAR`/`_REPROGRAMAR`/`_CANCELAR`/`_CONFIRMA` ya se revisaban en cualquier etapa, al inicio de `interpret()`, antes del dispatch por etapa — ese es el patrón que se generalizó.

## 2. Diseño elegido

### 2.1. Chequeo centralizado, un solo lugar de detección

`domains/health/brain.py:HealthBrain.interpret()` ahora llama a un nuevo método, `_detectar_interrupcion_de_contexto(texto, datos, etapa_actual)`, **inmediatamente después** del chequeo existente de `_OLVIDAR` y **antes** de cualquier dispatch por etapa (incluido el bloque de reprogramar/cancelar/confirmar, y el `if etapa == "..."` de siempre). Si devuelve un `BrainOutput`, ese turno termina ahí — ninguna función de etapa específica (`_interpretar_servicio`, `_interpretar_fecha`, `_interpretar_horario`, `_interpretar_decision`) llega a ejecutarse ese turno. Si devuelve `None`, el flujo normal de la etapa continúa exactamente como antes.

Las 5 categorías se extrajeron **tal cual** (mismo orden de prioridad, mismo texto de respuesta) desde `_interpretar_decision` hacia este método nuevo — cero duplicación: ya no existen en dos lugares, existen en uno solo, alcanzable desde cualquier etapa.

Una excepción explícita: `_ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO = frozenset({"esperando_documento_beneficiario", "esperando_confirmacion_beneficiario"})` — mientras el wizard de beneficiario YA ESTÁ resolviendo una interrupción anterior, no se vuelve a interrumpir con estas 5 categorías (ej. un documento de identidad no debería dispararle "pide info" solo porque contiene ciertos dígitos/palabras por coincidencia).

### 2.2. Beneficiario: retomar sin perder contexto (`etapa_antes_de_beneficiario`)

Mismo patrón que ya usa `_iniciar_olvido`/`etapa_antes_de_olvido` (recado 016): al detectar `_PARA_OTRO` en cualquier etapa, se guarda esa etapa en `datos["etapa_antes_de_beneficiario"]` antes de saltar al wizard. Al confirmar el beneficiario, `_interpretar_confirmacion_beneficiario` llama a un nuevo método, `_reanudar_tras_interrupcion(etapa_a_reanudar, datos)`, que retoma exactamente el punto donde el paciente iba — reutilizando las funciones "ofrecer" YA EXISTENTES (nunca reconstruye una respuesta a mano):

| `etapa_antes_de_beneficiario` | Qué hace `_reanudar_tras_interrupcion` | Por qué |
|---|---|---|
| `esperando_decision` (default) | `_ofrecer_fechas(datos)` | Comportamiento original, sin cambios — el único caso que existía antes de este recado. |
| `esperando_servicio` | `_ofrecer_catalogo_servicios(datos)` (re-pregunta) | El servicio **todavía no se había capturado** en el turno que disparó la interrupción (ver 2.3) — saltar a fechas usaría un default equivocado. |
| `esperando_fecha` | `_ofrecer_fechas(datos)` | El servicio YA estaba elegido (`servicio_elegido` sigue en `datos`, preservado íntegro) — se re-consulta disponibilidad REAL, nunca cacheada. |
| `esperando_horario` | `_ofrecer_horarios(datos)` | Servicio y fecha ya elegidos — se re-consultan horarios reales de esa fecha. |
| `esperando_seleccion_reprogramacion` | `_iniciar_reprogramacion(datos)` | Mismo criterio, para el flujo de reprogramar. |

Además, la respuesta de confirmación antepone un reconocimiento explícito ("¡Listo, quedó registrado para {nombre}!") al texto de la etapa retomada — usando `BrainOutput.model_copy(update=...)` para preservar **todos** los demás campos (`verificaciones_de_datos`, `texto_base_para_comparacion`, `tool_requerida`, etc.) sin reconstruir el objeto a mano.

`_CONSULTAR_SERVICIOS` (petición de catálogo) se dejó **fuera** de esta generalización, tal como pediste explícitamente — pero su lógica se extrajo al nuevo método `_ofrecer_catalogo_servicios` de todos modos, porque `_reanudar_tras_interrupcion` la necesitaba para el caso "esperando_servicio" de arriba (evita duplicar esa lógica en dos lugares en vez de solo mover el problema).

### 2.3. Límite de diseño reconocido explícitamente (no un bug, una decisión)

Cuando el mensaje real combina, en la MISMA frase, tanto la elección de servicio como la declaración de beneficiario ("**Odontologia** pero **es para mi hija**") — que es exactamente el caso real de hoy — el chequeo centralizado intercepta ANTES de que `_interpretar_servicio` alcance a leer "Odontologia". Por diseño (chequeo centralizado que corre ANTES que cualquier función de etapa, tal como pediste), el servicio mencionado en esa misma frase **no se captura** en ese turno — el paciente lo vuelve a decir una vez confirmado el beneficiario (ver test de reproducción exacta, sección 3.1: turno `m4`→re-pregunta, `m5`→"Odontologia" otra vez).

Esto es distinto del caso que describiste como objetivo ("si ya eligió servicio y fecha, y AHÍ menciona 'es para mi hija'") — ahí el servicio se dijo en un turno ANTERIOR, separado, y por eso SÍ se preserva sin pedirlo de nuevo (ver fila `esperando_fecha`/`esperando_horario` de la tabla). La diferencia es si el dato ya estaba en `datos` ANTES de este turno, o si venía en el mismo mensaje que la interrupción — solo el segundo caso pide un paso adicional. Evalué la alternativa (extraer primero el servicio con la lógica de `_interpretar_servicio` y LUEGO pivotar a beneficiario) y la descarté: exigiría duplicar/acoplar lógica de extracción específica de etapa dentro del chequeo centralizado, exactamente lo que pediste evitar ("evitar duplicar la lógica de detección en cada función"). El costo real es un turno adicional (repetir el nombre del servicio) — nunca se pierde ni se inventa un dato.

## 3. Hallazgo adicional encontrado al verificar (corregido en el mismo trabajo)

Al generalizar `_PIDE_INFO`/`_INFO_NO_AUTORIZADA` a etapas posteriores, descubrí que **ambas escalaban la conversación de verdad por error** cuando se disparaban desde una etapa distinta de `esperando_decision` — no por ningún fallo del Brain, sino por una regla del **Core** (`core/orchestrator.py:_determinar_siguiente_fase`): ambas categorías proponen `proxima_accion_propuesta="preguntar_intencion"`, que siempre mapeaba a `FaseActual.IDENTIFICACION_DE_INTENCION` sin importar la fase de origen. Desde una fase más avanzada (ej. `RECOPILACION_DE_DATOS`, la fase real de cualquier etapa "esperando_X"), esa transición **no es válida** según la tabla de `state/machine.py:VALID_TRANSITIONS` — `validate_transition` lanzaba `InvalidTransitionError`, y el manejo de ese error **escalaba la conversación de verdad** (mensaje genérico de escalamiento, `management_status=ESCALATED`), algo que ninguna de las dos categorías pretende hacer.

**Corregido** en `core/orchestrator.py:_determinar_siguiente_fase`: si la fase actual no permite volver a `IDENTIFICACION_DE_INTENCION`, la conversación se queda en su fase actual (auto-bucle, ya válido en la tabla de transiciones para `RECOPILACION_DE_DATOS`/`RAZONAMIENTO_DECISION`) en vez de forzar un retroceso inválido. Es un cambio en el Core (no en el dominio salud) porque el bug es genérico — cualquier Brain de cualquier dominio que proponga "preguntar_intencion" desde una fase avanzada lo habría disparado igual; no es específico de las 5 categorías de este recado, solo que nunca se había ejercitado ese camino hasta ahora.

## 4. Verificación (los 4 puntos pedidos)

Todo en `tests/domains/health/test_interrupciones_en_cualquier_etapa.py` (8 tests nuevos).

1. ✅ **Reproducción exacta del caso real**: `test_para_otro_en_etapa_esperando_servicio_reproduce_caso_real_de_hoy` — mensaje real exacto ("Odontologia pero es para mi hija") dicho en `esperando_servicio` (contra `HrmmAppointmentService` real con catálogo Odontologia + `buscar-paciente`, `FakeHttpClient`). Confirma: activa el wizard de beneficiario, preserva `etapa_antes_de_beneficiario="esperando_servicio"`, retoma pidiendo el servicio de nuevo, y la reserva final usa el documento de la **hija**, nunca el del titular.
2. ✅ **Las otras 4 categorías desde una etapa posterior** (`esperando_horario`): `test_interrupcion_se_detecta_en_etapa_posterior_esperando_horario` (parametrizado ×4) + `test_info_no_autorizada_en_etapa_posterior_no_revela_dato_clinico`. Confirma que `_HUMANO` escala la Activity de verdad (`ManagementStatus.ESCALATED`), `_NO_PUEDE_AHORA` finaliza, `_PIDE_INFO`/`_INFO_NO_AUTORIZADA` responden y **se quedan en `esperando_horario`** (gracias a la corrección de la sección 3) — nunca caen en el fallback de `_interpretar_horario`.
3. ✅ **HealthBrain determinista vs. HealthAnthropicBrain**: `test_interrupcion_de_contexto_funciona_igual_con_llm_activo` y `test_beneficiario_detectado_en_etapa_posterior_funciona_igual_con_llm_activo` — llaman a `.interpret()` directamente en ambos Brains con el mismo estado/mensaje; confirman que `propuesta_de_actualizacion_de_estado`/`tool_requerida` son IDÉNTICOS entre ambos (la decisión nunca cambia), solo el texto se redacta distinto.
4. ✅ **Suite completa**: **337 passed, 4 skipped** (329 previas + 8 nuevas) — cero regresiones, incluido el cambio en `core/orchestrator.py`.

## Archivos tocados

- `domains/health/brain.py`: `_ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO`, `_detectar_interrupcion_de_contexto` (nuevo), `_reanudar_tras_interrupcion` (nuevo), `_ofrecer_catalogo_servicios` (extraído, reutilizado en 2 lugares), `_interpretar_confirmacion_beneficiario` (usa `_reanudar_tras_interrupcion`), `interpret()` (nueva llamada centralizada), `_interpretar_decision` (las 5 ramas removidas, ya no duplicadas).
- `core/orchestrator.py`: `_determinar_siguiente_fase` — corrige el hallazgo de la sección 3.
- Nuevo: `tests/domains/health/test_interrupciones_en_cualquier_etapa.py` (8 tests).

## Pendiente de tu decisión

1. Revisar si quieres que commitee y pushee este trabajo.
2. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo.
3. El log temporal `BRAIN CONSTRUIDO` (recado 044, `domains/health/config.py`) sigue presente — avísame cuándo quitarlo.
