# 086 — Investigación urgente: reporte de correo de prueba sintético filtrado a paciente real — NO confirmado, evidencia real en contra

**Fecha**: 2026-09-15
**Tipo**: investigación de seguridad/integridad de datos, solo lectura contra hrmm-backend real — **sin cambios de código, sin correcciones aplicadas** (no se encontró nada que corregir).
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Origen**: el usuario reportó, con carácter urgente, que su reserva real de hoy (Urgencias, 2026-09-15, 07:00, documento 72302972) intentó enviarse a `zantia-test-085-1789470689@example.com` — un correo sintético de la prueba real del recado 085 — e hipotetizó que la prueba había sobrescrito `correo_conocido` en `identity_store` para su documento real.

## 0. Clasificación de afirmaciones (regla `discovery-antes-de-modificar.md`)

Todo lo de este recado es `[CONFIRMADO]` con evidencia real (código + 2 consultas de solo lectura contra hrmm-backend de producción). Un punto queda `[DESCONOCIDO]` — ver sección 4.

## 1. Revisión del código de la prueba real (punto 1 del pedido)

`tests/domains/health/test_hrmm_appointment_service.py::test_book_appointment_persiste_el_correo_real_contra_hrmm_backend_real` — confirmado leyendo el archivo: usa `documento = f"ZANTIA-TEST-085-{int(time.time())}"` — **nunca `72302972` ni ningún documento real**. Tampoco construye ni toca ningún `SQLiteIdentidadCanalStore`/`identity_store` en ningún punto — llama `HrmmAppointmentService` directo, sin pasar por `gateway.py` en absoluto. Estructuralmente, esta prueba no tiene ningún camino de código que pudiera tocar el documento 72302972 ni ningún `identity_store`.

## 2. Evidencia real contra hrmm-backend (puntos 2 y 4 del pedido)

Dos consultas de solo lectura (`GET /api/agenda/citas`, trusted, mismo secreto real ya usado en el recado 085):

**a) Todas las citas del documento 72302972 en 2026-09-15**: 4 citas reales — 3 a las 07:00 (Urgencias `CITA-7afbe4d541`, Odontologia `CITA-a3084968fb`, Pediatria `CITA-2cb295f690` — esta última es la cita ORIGINAL del hallazgo 1 del recado 085, `correo: null` desde ANTES de cualquier prueba) y 1 reprogramada a las 10:30 (`CITA-e8579ea1d0`, con datos de contacto reales: `nombre_paciente: "Santander Olivero"`, `telefono: "3018650437"`, **`correo: "director@barranquillasegura.com"`** — el correo real del usuario, intacto y correcto). **Ninguna de las 4 tiene el correo sintético.**

**b) Búsqueda de `zantia-test` en el correo de TODAS las citas de hoy (2026-09-15, sin filtrar por documento)**: 5 citas totales — 4 son las de 72302972 (arriba) y **exactamente 1** coincide: `CITA-9866bdf439`, con `documento_paciente: "ZANTIA-TEST-085-1789470689"` (el documento SINTÉTICO de la prueba, no el real), `nombre_paciente: "ZANTIA TEST 085"`, `correo: "zantia-test-085-1789470689@example.com"`, **`estado: "cancelada"`** (la limpieza automática del propio test funcionó correctamente).

**Conclusión directa**: el correo sintético existe en hrmm-backend, pero exclusivamente en su propia cita de prueba, aislada, bajo un documento claramente distinto, ya cancelada — nunca en ninguna cita de 72302972. La hipótesis del usuario **no se confirma** con la evidencia real disponible.

## 3. La causa real de lo que el usuario observó

La reserva real de Urgencias de hoy (`CITA-7afbe4d541`, creada `2026-09-15T11:33:15`) tiene `correo: null`, `nombre_paciente: ""`, `telefono: ""` — **exactamente el mismo síntoma que motivó el hallazgo 1 del recado 085 en primer lugar** (correo nunca enviado/persistido), no una corrupción nueva. La explicación más simple y consistente con toda la evidencia: el fix del recado 085 se commiteó y pusheó a `origin/main`, pero **todavía no se redesplegó en EasyPanel** — la reserva de hoy corrió contra el código VIEJO (sin el fix), que nunca pasa `correo` en el payload, igual que antes. Nada indica un correo sintético involucrado en ningún punto de esa reserva real.

## 4. `[DESCONOCIDO]` — de dónde vino el reporte exacto del usuario

No se pudo determinar, desde esta sesión, la fuente exacta donde el usuario vio el texto `zantia-test-085-1789470689@example.com` asociado a su propia reserva — no está en `identity_store` local (esta máquina usa `:memory:`, `ZANTIA_IDENTIDAD_DB_PATH` vacía en `.env`, sin acceso al proceso real desplegado) ni en ningún dato real de hrmm-backend consultado. Posible explicación no verificada: una lectura cruzada del propio recado 085 (que documenta ese correo sintético exacto) con la reserva real del mismo día, sin que ambos eventos estén realmente conectados — se le pide al usuario la fuente exacta (captura, log, transcripción) si quiere que se investigue más a fondo.

## 5. Ninguna corrección aplicada

No se modificó ningún dato — no había ningún valor corrupto que corregir. Tampoco se modificó el código de la prueba: ya usa un documento/teléfono/correo sintéticos y claramente marcados (`ZANTIA-TEST-085-<epoch>`), aislados del paciente real desde su diseño original.

## 6. Siguiente paso real

El hallazgo genuino y accionable de esta investigación es que **el fix del recado 085 sigue sin desplegarse** — la reserva real de Urgencias de hoy lo confirma. Recomendación: pedir el redespliegue en EasyPanel para que el fix tome efecto en reservas reales nuevas.
