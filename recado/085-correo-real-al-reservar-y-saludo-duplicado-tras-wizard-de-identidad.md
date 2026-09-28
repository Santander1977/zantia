# 085 — Fix: correo de confirmación real nunca se disparaba (R-21), saludo institucional duplicado tras el wizard de identidad, y 2 variantes reales de "consultar mis citas"

**Fecha**: 2026-09-15
**Tipo**: corrección real, probada (código + tests unitarios/integración + 1 prueba real contra hrmm-backend), **NO desplegada** — a la espera de confirmación explícita para commitear/pushear/redesplegar.
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Origen**: transcripción REAL de producción (documento `72302972`, hoy 2026-09-15) con 3 hallazgos reportados por el usuario, más un pedido de seguimiento explícito para el hallazgo 1 (R-21) con contexto ya confirmado por la sesión de HRMM.
**Continúa**: recado `084` (misma investigación, sesión anterior — esta sesión corrigió el diagnóstico de uno de sus hallazgos, ver sección 2).

## 0. Clasificación de afirmaciones (regla `discovery-antes-de-modificar.md`)

Todo lo de este recado es `[CONFIRMADO]` — leyendo código real de AMBOS repos (`icaco`/ZANTIA y `hrmm`/backend, en modo solo lectura) y reproduciendo antes/después con `pytest`, incluida **una llamada real contra hrmm-backend de producción** (sección 1.4). Ningún dato se asumió sin verificar.

## 1. Hallazgo 1 (R-21) — el correo de confirmación de la reserva nunca se enviaba

### Causa raíz real (no era n8n/Task Runner)

La hipótesis inicial del usuario (mismo problema de Task Runner del código de verificación, workflow `enviar_confirmacion_email` distinto de `enviar_codigo_recuperacion`) **se descartó con evidencia**: el problema era estructural, del lado de ZANTIA, y afectaba a **el 100% de las reservas hechas por chat, siempre** — nunca un fallo intermitente de infraestructura.

Cadena completa, confirmada leyendo código real:

1. `tools.py:BookAppointmentTool.run()` llamaba a `book_appointment(slot_id, patient_reference, idempotency_key)` — **sin `correo`**.
2. `HrmmAppointmentService.book_appointment`'s único otro origen de correo, `contacto.get("correo")`, dependía de `register_patient_contact` — que **nunca se llama desde ningún camino real** (confirmado con `grep` en todo el árbol: cero call-sites fuera de su propia definición y de tests).
3. El wizard de identidad (`_gestionar_identificacion`/`buscar_paciente`) es el único momento donde ZANTIA consulta datos del paciente antes de reservar — pero `GET /api/agenda/citas/buscar-paciente` devuelve `PacienteBuscado` (schema real de `hrmm`, leído en `backend/app/schemas/agenda.py:115`): **solo `nombre_paciente`/`telefono`, deliberadamente sin `correo`** (endpoint público, sin auth, usado por el navegador del portal — privacidad).
4. Resultado: `correo_efectivo` en `book_appointment` era `None` para TODA reserva por chat, siempre — `_intentar_enviar_confirmacion` devolvía `None` (nunca intentado) sin hacer ninguna llamada de red.

### Punto 3 del pedido del usuario — NO bloqueante, sin necesidad de coordinar con HRMM

El correo real SÍ está disponible para ZANTIA, por un camino distinto: `Cita` (schema completo de `hrmm`, `backend/app/schemas/agenda.py:60`) **sí incluye `correo: Optional[str]`**, y `GET /api/agenda/citas` (trusted, `verificar_secreto_confianza`) es el MISMO endpoint que `get_patient_appointments` ya usa. Es la MISMA técnica que `hrmm-backend` usa internamente en `enviar_codigo_verificacion` (`next((c.correo for c in citas if c.correo), None)`, confirmado leyendo `backend/app/api/agenda.py:247-248`) — replicada del lado de ZANTIA, sobre un endpoint que ya tenía permiso de llamar. **Nunca hizo falta pedirle nada a la sesión de HRMM.**

Límite conocido y aceptado: si el paciente nunca tuvo NINGUNA cita previa con correo en archivo, esta técnica no encuentra nada — pero ese es exactamente el mismo caso límite que ya existe hoy en `enviar_codigo_verificacion` (un paciente así tampoco puede completar la verificación de identidad por este canal). No es una regresión ni un caso nuevo sin cubrir.

### Punto 4 — dónde vive el correo: `identity_store`, junto al `nombre` (mismo patrón, recado 034)

Decisión tomada según lo sugerido por el usuario: se persiste UNA SOLA VEZ, en `identity_store.marcar_verificado`, en el mismo momento y con el mismo criterio que ya existía para `nombre`. Evita consultar `correo_conocido` en cada reserva.

### La corrección (7 archivos)

- **`domains/health/hrmm_appointment_service.py`** — `correo_conocido(documento_paciente)` (nuevo, duck-typed): `GET /api/agenda/citas` crudo, extrae `correo` de cualquier cita existente. `book_appointment` ahora también **incluye `correo` en el body de `POST /api/agenda/citas`** (antes solo se usaba para el segundo paso, `enviar-confirmacion` — la cita en sí quedaba con `correo: null` en la base real incluso cuando la confirmación SÍ se lograba enviar; exactamente el síntoma de `CITA-2cb295f690`).
- **`domains/health/identity_store.py`** — `IdentidadCanal.correo` (nuevo campo, `Optional`), columna `correo` en SQLite con migración defensiva (mismo patrón que `nombre`, recado 034), `marcar_verificado(..., correo=None)`.
- **`domains/health/gateway.py`** — `_iniciar_verificacion_de_identidad` ahora llama `correo_conocido` (duck-typed, tras enviar el código) y lo carga en `_pending_identity["correo_candidato"]`; `_procesar_codigo_de_identificacion` lo persiste junto con `nombre` al confirmar el código. `_correo_conocido`/`_contacto_conocido` (nuevos helpers) arman `Activity.patient_contact` con `nombre` Y `correo` en los 3 puntos donde antes solo se incluía `nombre`.
- **`domains/health/brain.py`** — `tool_requerida["params"]` de `book_appointment` ahora incluye `"correo": (self._activity.patient_contact or {}).get("correo")`.
- **`domains/health/tools.py`** — `BookAppointmentTool.run` lee `params.get("correo")` y lo pasa a `book_appointment`.
- **`domains/health/appointment_service.py`** — `correo: Optional[str] = None` agregado al Protocol `book_appointment` (documentando una firma que `HrmmAppointmentService` ya tenía sin reflejarse ahí) y a `MockAppointmentService.book_appointment` (acepta e ignora — nunca simula envío real).

### Verificación

**1. Correo disponible tras verificar identidad** (`test_identidad_persistente.py::test_correo_real_se_captura_y_persiste_tras_verificar_identidad`): wizard completo con una cita previa con correo en archivo → `identity_store.get(telefono).correo` queda poblado.

**2. `book_appointment` incluye el correo en el payload real** (`test_identidad_persistente.py::test_book_appointment_incluye_el_correo_conocido_en_el_payload_real` — flujo COMPLETO: wizard → reservar → payload capturado; y `test_hrmm_appointment_service.py::test_book_appointment_incluye_correo_en_el_payload_de_creacion` — unitario, más rápido de debuguear). Además 3 tests unitarios de `correo_conocido` (encuentra correo entre citas previas, `None` sin citas, `None` si hrmm-backend falla — best-effort, nunca rompe el wizard).

**3. Prueba real contra hrmm-backend** (`test_hrmm_appointment_service.py::test_book_appointment_persiste_el_correo_real_contra_hrmm_backend_real`, gateada por `ZANTIA_RUN_REAL_HRMM_TESTS=1`, **SÍ ejecutada en esta sesión** — a diferencia del test interactivo equivalente del recado 059, este es 100% automático: no necesita revisar un inbox en vivo, solo confirma el payload persistido vía `GET /citas/{id}` crudo, y limpia con `PATCH /citas/{id}` (trusted, mismo secreto, sin pasar por el sub-flujo de código de verificación — esa exigencia es para acciones iniciadas por el paciente, no para limpieza de datos de prueba propios):

```
documento = ZANTIA-TEST-085-<epoch>, correo = zantia-test-085-<epoch>@example.com
book_appointment(slot_real, documento, idem_key, correo=correo_prueba) -> CITA-<real>
GET /api/agenda/citas/CITA-<real> -> correo == correo_prueba  ✅ (a diferencia de CITA-2cb295f690: correo=null)
cita.correo_confirmacion_enviado is True  ✅ (hrmm-backend confirmó el envío real)
PATCH /api/agenda/citas/CITA-<real> {"estado":"cancelada"} -> 200  ✅ (limpieza confirmada)
```

**4. Suite completa**: sin regresiones (ver sección 4 de este recado).

## 2. Hallazgo 2 — "consultame las citas del ultimo mes" con saludo institucional PEGADO/duplicado

### Corrección del diagnóstico de la sesión anterior (recado 084)

El recado 084 investigó esta frase SIN la transcripción completa (el usuario había pegado un placeholder sin reemplazar) y concluyó que la causa era una brecha de clasificación de intención (la frase no calzaba con `_CONSULTAR`/`_interpretar_opcion_menu`) — cierto, pero **no la causa del síntoma reportado** ("saludo pegado"). Con la transcripción completa de esta sesión, la causa real es otra, y **más grave**: el bug ocurre para CUALQUIER frase en ese punto exacto de la conversación, incluida la forma canónica "consultar mis citas" — confirmado reproduciendo ambas.

### Causa raíz real

`handle_inbound_message` (`gateway.py`) usa `_saludo_mostrado` (un set) para no repetir el guion institucional completo ("Soy Andrés...", menú de 5 opciones) más de una vez por conversación. Pero esa marca **solo se escribía en la rama alcanzada DESPUÉS de que la identidad ya está resuelta** (línea ~862). La rama del gate de identidad (documento + código, líneas ~816-853) SÍ muestra el saludo completo (recado 046, antepuesto a la pregunta de documento) — pero **nunca marcaba `_saludo_mostrado`**. Reproducido exacto: `hola` → documento → código → CUALQUIER mensaje real (`"consultame las citas del ultimo mes"` o `"consultar mis citas"`, ambos fallan igual) → el guion institucional completo vuelve a aparecer, pegado con el separador `\n\n` correcto (recado 080, **nunca roto** — el bug nunca fue la falta de separador) a la respuesta real.

### La corrección

`gateway.py`, 1 línea funcional: `gateway._saludo_mostrado.add(patient_reference)` en el mismo punto donde se muestra el saludo completo dentro del gate de identidad, antes del `return f"{_saludo_primer_contacto(None)}\n\n{respuesta_identificacion}"`.

### Hallazgo adicional en la misma transcripción

El turno SIGUIENTE del usuario real, "consultas las citas mias del ultimo mes" (forma conjugada distinta + posesivo después del sustantivo), tampoco calzaba con ninguna lista determinista — agregado a `intent.py:_CONSULTAR`/`brain.py:_CONSULTA_CITAS_EXISTENTES` (`"consultas las citas mias"`, `"las citas mias"`), mismo criterio de duplicación ya documentado en ambos archivos.

### Verificación

`tests/domains/health/corpus_regresion/test_recado085_saludo_duplicado_tras_wizard_de_identidad.py` (3 tests, reproduce el wizard real completo vía `HrmmAppointmentService`/`FakeHttpClient`): (1) la frase EXACTA reportada ya no repite el saludo; (2) la forma canónica "consultar mis citas" TAMPOCO lo repetía antes del fix (confirma que la causa no era de clasificación); (3) la segunda frase real de la transcripción también se reconoce y tampoco repite el saludo.

## 3. Hallazgo 3 — "ok enviame un email" no reconocido tras la reserva

**Confirmado: la categoría sigue existiendo** (`brain.py:_PREGUNTA_SOBRE_CORREO_ENVIADO`, recado 058, conectada vía `_detectar_interrupcion_de_contexto` — reutilizada tanto dentro de una conversación abierta como en la ventana de gracia de un turno tras un cierre, `gateway.py:_evaluar_ventana_de_gracia`). El fix de la sesión anterior (recado 084 — agregar formas de PEDIDO como "enviame un email"/"enviame el correo", distintas de las formas de PREGUNTA que ya existían) **sigue vigente e intacto** en el código — confirmado re-verificando el árbol de trabajo al inicio de esta sesión.

Verificación ADICIONAL de esta sesión, con el flujo REAL completo (wizard de identidad vía `HrmmAppointmentService` + reserva + correo real ya conectado por el hallazgo 1): tras reservar, "ok enviame un email" ahora responde **"Sí — te enviamos la confirmación por correo, deberías tenerla en tu bandeja."** — honesto y correcto, porque el hallazgo 1 de este mismo recado hizo que `correo_confirmacion_enviado` sea `True` de verdad (antes de ese fix, aun reconociendo la frase, la respuesta honesta habría sido "no tenemos un correo tuyo registrado" — técnicamente correcta pero inútil, porque el correo nunca se intentaba). Los 2 hallazgos de este recado se refuerzan mutuamente.

## 4. Archivos tocados (además de los del recado 084, ya en el árbol de trabajo sin commitear)

- `domains/health/hrmm_appointment_service.py`, `domains/health/identity_store.py`, `domains/health/gateway.py`, `domains/health/brain.py`, `domains/health/tools.py`, `domains/health/appointment_service.py` — hallazgos 1 y 2.
- `domains/health/intent.py`, `domains/health/brain.py` — 2 frases nuevas (hallazgo 2, adicional).
- `tests/domains/health/test_identidad_persistente.py` — 2 tests nuevos (hallazgo 1).
- `tests/domains/health/test_hrmm_appointment_service.py` — 5 tests nuevos, incluida 1 prueba real (hallazgo 1).
- `tests/domains/health/test_saludo_institucional.py` — 1 caso de fixture actualizado (nueva llamada real a `GET /api/agenda/citas` durante el wizard).
- `tests/domains/health/corpus_regresion/test_recado085_saludo_duplicado_tras_wizard_de_identidad.py` (nuevo, 3 tests) — hallazgo 2.

## 5. Verificación de la suite completa

`.venv/bin/pytest -q`: **625 passed + 16 skipped**, cero regresiones (16 skipped = 15 previos + 1 la prueba real gateada, que SÍ se ejecutó por separado con `ZANTIA_RUN_REAL_HRMM_TESTS=1` y pasó — ver sección 1.4).

## 6. Siguiente paso

Reportar al usuario los 3 hallazgos con su causa raíz real, incluida la corrección explícita del diagnóstico del recado 084 (hallazgo 2 — el bug real era estructural del gate de identidad, no de clasificación de frases). Pedir autorización explícita para commitear/pushear/redesplegar — nada de esto se aplicó a producción todavía.
