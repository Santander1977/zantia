# 062 — Callejón sin salida en el wizard de código de verificación (cancelar/reprogramar)

**Fecha**: 2026-09-10
**Estado**: Corregido y probado. Decisión de fondo (LLM asistido) evaluada y documentada, NO implementada — pedido explícito de solo documentar la recomendación.

**Nota de transparencia**: dijiste "transcripción completa adjunta", pero ningún contenido de transcripción llegó a este contexto — solo el texto de tu mensaje con las frases citadas textualmente dentro de la descripción del hallazgo ("¿a cuál email enviaron?", "reenviarme otro", "Salir", "Exit", y por separado "Estoy tristw"/"cuales tengo reservadas"). Reproduje el bug y los tests de regresión con esas frases exactas — nunca inventé una transcripción de 5 mensajes que no tengo. Si la transcripción real tiene mensajes adicionales que no quedaron cubiertos aquí, compártelos y agrego los que falten.

---

## 1. Causa raíz — `[CONFIRMADO]`, leyendo el código real

El wizard de código de verificación (`domains/health/gateway.py`, sección "Sub-flujo de verificación por código", línea ~1340) es, por diseño explícito desde su creación (recados 009/012), **deliberadamente independiente de `ConversationState`/`Orchestrator`/`HealthBrain`** — vive con su propio estado en `HealthGateway._pending_verifications`, sin pasar por ninguna máquina de estados.

`handle_inbound_message` (línea 560-561) lo intercepta ANTES que cualquier otra cosa:
```python
if patient_reference in gateway._pending_verifications:
    return _procesar_intento_de_codigo(gateway, patient_reference, text)
```
Esto ocurre antes de `find_open_context`, antes de `HealthBrain`, antes de `_es_despedida`, antes de `_detectar_interrupcion_de_contexto` (brain.py, recados 047/053) — el mismo detector centralizado que ya resolvió el patrón idéntico de bug en los recados 049/050 (Activity real) y 057/059-060 (menú sin conversación abierta), **nunca llegaba a ver ningún mensaje una vez que el paciente entraba a este wizard**.

Dentro de `_procesar_intento_de_codigo` (antes de este fix): en la etapa `esperando_codigo`, **cualquier texto** se enviaba tal cual como `codigo` a `cancel_appointment_verified`/`reschedule_appointment_verified` contra hrmm-backend; si el backend respondía "inválido"/"vencido" (que respondía siempre, para cualquier texto que no fuera el código real), el paciente recibía `_MENSAJE_CODIGO_INVALIDO` — sin importar si había escrito una pregunta, un pedido de reenvío, o "salir". Confirmado con un test de control ANTES de corregir (reproducido localmente, ver sección 4): "¿a cuál email enviaron?" llegaba a ejecutarse como intento de código real.

**Hallazgo relacionado, mismo patrón exacto, NO corregido (fuera del alcance explícito de este pedido)**: `_gestionar_identificacion`/`_procesar_codigo_de_identificacion` (el wizard de identidad de canal, recados 012/014, línea ~1615) tiene la MISMA estructura — independiente del Brain, mismo `stage == "esperando_codigo"` que trata cualquier texto como intento de código. No lo toqué porque tu pedido fue específicamente sobre "el sub-flujo de cancelar/reprogramar" — señalado explícitamente para que decidas si también hace falta ahí.

## 2. Corrección implementada

Detector nuevo y pequeño, dedicado a este wizard (`_detectar_interrupcion_wizard_codigo`, `domains/health/gateway.py`) — **no** reutiliza `_detectar_interrupcion_de_contexto` tal cual (esa función está atada a `ConversationState`/`resultado_de_herramientas`, que este wizard nunca tiene por diseño); se llama al inicio de `_procesar_intento_de_codigo`, antes de cualquier interpretación de código/ordinal:

- **"salir" / "cancelar esto" / "exit"** (+ "ya no quiero", "olvidalo", "detente") → aborta de verdad: `del gateway._pending_verifications[patient_reference]` (sin estado residual — mismo cuidado explícito que pediste, tras el bug de `_saludo_mostrado` de hace un momento) y devuelve el menú principal. Coincidencia **exacta**, deliberadamente NO fuzzy: una salida es irreversible sin confirmación adicional — mejor un falso negativo (corregible con un segundo mensaje) que un falso positivo que aborte un código real en curso.
- **"reenviar" / "no me llegó" / variantes** → reenvío REAL (`_reenviar_codigo`, llama de nuevo a `send_verification_code`), actualiza `correo_parcial` guardado, permanece en el wizard.
- **"¿a qué correo?" / variantes** → responde con el correo enmascarado YA conocido (antes se calculaba en el envío inicial y se descartaba — ahora se guarda en `pendiente["correo_parcial"]`), sin llamar de nuevo al backend.
- **Consulta de citas existentes** (reutiliza `_CONSULTA_CITAS_EXISTENTES` de `brain.py`, con la frase real nueva "cuales tengo reservadas" agregada ahí — beneficia también al flujo normal de `HealthBrain`) → responde con el listado real (`_listar_citas_activas`, extraída de `_resolver_consulta` para no triplicar el mismo texto), permanece en el wizard.
- **Expresión emocional** (`_EXPRESION_EMOCIONAL` de `brain.py`) → acompañamiento breve, permanece en el wizard.
- Las últimas 4 categorías solo aplican en la etapa `esperando_codigo` (ya se envió un código real); "salir" aplica en CUALQUIER etapa, incluida `esperando_seleccion` (reprogramar, antes de elegir horario).

**Tolerancia a errores de tipeo** (requisito 3): nuevo mecanismo genérico `_contains_any_fuzzy`/`_mejor_similitud_de_frase` en `brain.py` — generaliza el MISMO algoritmo ya calibrado del recado 036 (`SequenceMatcher` + ventanas de tokens, umbral 0.82, sin inventar uno nuevo) para cualquier lista de frases, no solo el catálogo de servicios. Verificado empíricamente antes de escribir código (no supuesto):

| Texto real | Frase candidata | Similitud |
|---|---|---|
| "Estoy tristw" | "estoy triste" | 0.917 |
| "no me llegoo" | "no me llego" | 0.957 |
| "reenbiame el codigo" | "reenviame" | 0.889 |
| "a q correo lo enviaron" | "a que correo" | 0.909 |
| "654321" (código real) | cualquier frase de estas listas | 0.000 |

El último renglón es la garantía anti-falso-positivo: un código real (numérico) nunca puntúa por encima del umbral contra ninguna frase (alfabética) — cero riesgo de que un código real se interprete como un comando.

## 3. Hallazgo lateral corregido en el camino

`_enviar_codigo_y_pausar` calculaba `correo_parcial` (el correo enmascarado) SOLO para el texto de la respuesta inicial y lo descartaba — no había forma de responder "¿a qué correo?" más tarde sin volver a llamar al backend. Ahora se guarda en `pendiente["correo_parcial"]` desde el envío inicial, y se actualiza en cada reenvío.

## 4. Verificación

Tests nuevos en `tests/domains/health/test_hrmm_gateway_verification.py`:
- `test_wizard_no_queda_atrapado_reproduce_los_mensajes_reales_reportados` — las 4 frases citadas textualmente en tu pedido ("¿a cuál email enviaron?", "reenviarme otro", "Salir", "Exit") reciben respuesta apropiada, ninguna cae en "código inválido"; confirma el reenvío real (2 llamadas a `POST /api/agenda/verificacion/enviar`) y el correo enmascarado en la respuesta.
- `test_salir_del_wizard_no_deja_estado_residual_y_permite_reintentar_limpio` — "salir" muestra el menú, `_pending_verifications` queda vacío, `find_open_context` es `None`, y un reintento posterior ("cancelar mi cita" de nuevo) arranca un wizard limpio desde cero (vuelve a pedir código), sin ningún resto del intento anterior.
- `test_wizard_reconoce_expresiones_con_errores_de_tipeo` — "Estoy tristw" y "cuales tengo reservadas" se reconocen (empatía / listado real), sin abortar el wizard.
- `test_codigo_real_de_6_digitos_sigue_funcionando_sin_confundirse_con_un_comando` — control anti-regresión: un código real de 6 dígitos sigue ejecutando la cancelación normalmente.

**Suite completa**: `494 passed, 9 skipped` (490 previas + 4 nuevas). Cero regresiones.

**Sin commitear** — a la espera de tu aprobación (regla del proyecto).

## 5. Decisión de fondo evaluada: ¿LLM asistido (recado 052) para este wizard?

Formato de decisión arquitectónica pedido por las reglas del proyecto:

- **Decisión propuesta `[PROPUESTO, NO implementado]`**: extender `core/selection.py` (mecanismo de interpretación de selección asistida por LLM, siempre verificada contra un conjunto real de opciones, recado 052) para que este wizard consulte un LLM como ÚLTIMO RECURSO — después del matching determinista/fuzzy ya construido, antes de tratar el mensaje como intento de código — clasificando contra un conjunto FIJO y pequeño de opciones reales: `{SALIR, REENVIAR, PREGUNTA_CORREO, CONSULTA_CITAS, ES_UN_CODIGO}`.
- **Motivo**: el patrón "agregar una regla nueva cada vez que aparece un caso real" ya se repitió en, al menos, los recados 026, 036, 041, 043, 047, 048, 058, 059-060, y ahora 062 — cada vez cubre los casos YA VISTOS, nunca generaliza a la siguiente forma real que un paciente escriba. `interpret_selection` ya tiene exactamente la garantía de seguridad que este wizard necesita (nunca acepta la propuesta del LLM a ciegas — la verifica contra IDs reales; sin `SelectionProposer` configurado o ante cualquier falla, cae al mismo fallback determinista de siempre).
- **Alternativas**: (a) seguir el patrón actual (reglas/fuzzy nuevas cada vez que se reporta un caso — lo que se hizo HOY); (b) la propuesta de arriba (LLM como último recurso, verificado).
- **Ventajas de (b)**: generaliza a formas de escritura nunca vistas ("no me dejó ver el correo, ¿cuál era?", con typos, con rodeos) sin tocar código cada vez; reutiliza un mecanismo YA construido, probado (recado 052) y con la garantía anti-alucinación ya resuelta — no es una integración de LLM nueva desde cero.
- **Desventajas de (b)**: agrega latencia/costo de red a mensajes dentro de este wizard (aunque solo como último recurso, tras fallar el matching determinista — el 6-dígitos exacto normal nunca lo tocaría); introduce una dependencia de LLM en un componente que fue diseñado EXPLÍCITAMENTE como independiente del Brain/LLM desde el recado 009/012 ("no requiere razonamiento") — es un cambio de postura arquitectónica, no una extensión menor; `HEALTH_BRAIN_TYPE` (el LLM del dominio salud) sigue sin activarse en ningún entorno real hoy (recados 040/042/046) — este wizard pasaría a depender de una capacidad que todavía no está en producción en ningún otro punto del sistema.
- **Riesgo**: bajo en el mecanismo en sí (la verificación contra IDs reales ya existe y está probada), medio en el cambio de postura arquitectónica (requiere decidir explícitamente que este wizard deja de ser "sin razonamiento").
- **Impacto**: acotado a este wizard si se implementa como último recurso opt-in (no afecta el resto del sistema); relevante para la promesa de "conversacional, no bot cerrado" que mencionaste — resolvería la clase COMPLETA de casos no anticipados, no solo los de hoy.
- **Estado**: `PROPUESTO`, no implementado. Recomiendo evaluarlo como una decisión propia en `docs/decisions/` cuando decidas retomarlo — no lo implementé en este trabajo porque pediste explícitamente solo la recomendación documentada, y porque activar una dependencia de LLM en un componente diseñado para no tenerla merece su propia conversación explícita, no colarse como efecto colateral de un bug fix.

**Mi recomendación concreta**: vale la pena, pero después de decidir (a) si `HEALTH_BRAIN_TYPE` se activa en algún punto de producción en general (hoy no lo está en ningún lado) y (b) si aceptas el trade-off de latencia/costo en este wizard específico. Mientras tanto, el fix determinista/fuzzy de hoy cierra el callejón sin salida real para todos los casos conocidos — no es un parche temporal descartable, es una base sólida sobre la que un "último recurso" con LLM podría apoyarse más adelante sin rehacer nada.
