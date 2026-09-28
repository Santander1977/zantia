# 087 — Backfill de correo para identidades ya verificadas, mensaje final con tipo de gestión, y cierre de la falsa alarma del correo de prueba en "Enviados"

**Fecha**: 2026-09-15
**Tipo**: corrección real, probada (código + tests unitarios/integración + 2 pruebas reales contra hrmm-backend), **NO desplegada** — a la espera de confirmación explícita para commitear/pushear/redesplegar.
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Continúa**: recado `086` (investigación urgente inicial — confirmó que la reserva real del usuario tras el redeploy del 085 seguía con `correo: null`, e infirió correctamente, sin poder confirmarlo todavía, que la causa era una identidad ya verificada de ANTES del 085/086 que nunca vuelve a pasar por el wizard).

## 0. Clasificación de afirmaciones (regla `discovery-antes-de-modificar.md`)

Todo lo de este recado es `[CONFIRMADO]` con evidencia real (código + reproducciones + 2 pruebas reales contra hrmm-backend de producción, ambas ejecutadas en esta sesión).

## 1. Falsa alarma resuelta — correo de prueba visto en "Enviados"

Durante esta misma sesión, el usuario reportó con carácter urgente haber encontrado un correo real en su propia bandeja con destinatario sintético (`zantia-test-086-...@example.com`), sospechando una fuga entre datos de prueba y su documento real (72302972). Investigación con evidencia directa:

- El código de las 2 pruebas reales de este recado usa exclusivamente `ZANTIA-TEST-086-<epoch>` (documento) y `zantia-test-086-<epoch>@example.com` (correo) — nunca `72302972` ni `director@barranquillasegura.com`, en ningún rol.
- Barrido de TODAS las citas de hoy con `correo` conteniendo `"zantia-test-086"`: exactamente 3, las 3 bajo documentos sintéticos propios (`ZANTIA-TEST-086-1789473573`, `ZANTIA-TEST-086-1789473601`), las 3 ya `cancelada`.
- Las 32 citas reales de 72302972: `correo` siempre `None` o el correo real correcto (`director@barranquillasegura.com`) — cero contaminación.
- Confirmado leyendo el código real de `hrmm-backend`: el payload hacia `/enviar-confirmacion` solo lleva `email` (destinatario) — no existe ningún campo de remitente que ZANTIA pueda fijar; el "From" real lo decide el workflow de n8n, fuera del alcance de cualquier prueba de este repo.

**Causa real, confirmada por el usuario tras revisar su correo**: `director@barranquillasegura.com` es el remitente configurado del workflow de n8n en este entorno de prueba — coincide con ser también el correo real/de sesión del usuario. Los envíos reales de prueba (autorizados explícitamente, recados 085/086) aparecen en su carpeta "Enviados" con el destinatario sintético — comportamiento esperado de una prueba real contra un remitente compartido, nunca una fuga de datos.

## 2. El backfill — implementación completa

### Causa raíz (confirmada en el recado 086, resuelta acá)

`_correo_conocido` (recado 085) solo lee `identity_store` — nunca escribe salvo dentro de `_procesar_codigo_de_identificacion` (el wizard completo). Una identidad ya `VERIFICADO` y vigente (`registro.vigente()`, hasta 180 días) nunca vuelve a pasar por el wizard — así que una fila persistida ANTES de que el recado 085 empezara a capturar `correo` queda con `correo: NULL` para siempre, sin importar si el código ya desplegado captura correo correctamente para identidades NUEVAS.

### La corrección

- **`domains/health/identity_store.py`** — nuevo método `actualizar_correo(telefono, correo)` (Protocol + implementación SQLite): actualiza SOLO la columna `correo` de una fila que YA existe. Deliberadamente DISTINTO de `marcar_verificado` — nunca toca `estado`/`verificado_en` (no reinicia la ventana de retención de 180 días solo porque el paciente reservó algo), nunca crea una fila nueva.
- **`domains/health/gateway.py:_correo_conocido`** — si el registro existe pero `correo` está vacío, intenta obtenerlo AHORA (mismo `correo_conocido` duck-typed del recado 085 — `GET /api/agenda/citas`, trusted) y, si lo encuentra, lo persiste vía `actualizar_correo`. Transparente para el paciente: ni una pregunta ni un paso conversacional de más — solo una llamada de red adicional en el momento en que el correo realmente hace falta (reservar/cancelar/reprogramar). Cubre a CUALQUIER identidad ya persistida sin correo, no solo la de un paciente puntual.
- **`domains/health/gateway.py:_procesar_intento_de_codigo`** — hallazgo adicional real: el sub-flujo verificado de cancelar/reprogramar (el que usa producción con `HrmmAppointmentService`, ya que cancelar/reprogramar SIEMPRE exigen código) tenía `correo_conocido = None` **hardcodeado**, con un comentario desactualizado del recado 054/058 que nunca se actualizó tras el 085 — cancelar/reprogramar por este camino NUNCA disparaban el correo real, ni siquiera con el fix del 085 ya desplegado. Corregido: ahora llama `_correo_conocido(gateway, patient_reference)` (con el backfill incluido).

## 3. Parte 2 — el mensaje final nombra la gestión real

`sufijo_confirmacion_correo` (recado 054/058) ahora exige un parámetro `tipo_gestion: str` — mismo criterio ya establecido para `verbo` ("confirmado"/"reprogramado") en `agent.py`. Texto nuevo:

- Éxito: `" El correo de {tipo_gestion} fue enviado a tu correo."`
- Fallo: `" Intentamos enviarte el correo de {tipo_gestion}, pero no pudimos verificar que llegara — si no te llega, avísame y lo revisamos con el equipo."`
- Sin intento: `""` (sin cambios — omitir es más honesto que inventar).

**Confirmado que la lógica condicional YA existía y era compartida** (pedido explícito del usuario de revisar esto antes de duplicar código): `sufijo_confirmacion_correo` ya era una única función reutilizada por `agent.py` (reservar/reprogramar vía Mock o vía Hrmm-sin-verificación) y por `gateway.py` (cancelar/reprogramar vía el sub-flujo verificado) — solo hacía falta agregarle el parámetro `tipo_gestion` y pasarlo correcto en cada uno de los 2 call sites reales, nunca 3 versiones distintas.

- `domains/health/agent.py`: `tipo_gestion = "reserva" if just_booked else "reprogramación"`.
- `domains/health/gateway.py` (sub-flujo verificado): `tipo_gestion = "cancelación" if pendiente["action"] == "cancelar" else "reprogramación"`.

## 4. Verificación

### 4.1 Unitarios/integración (todo con `FakeHttpClient`, sin red real)
- `identity_store`: `actualizar_correo` solo toca la columna correo (nunca `estado`/`verificado_en`/`nombre`); no-op si la fila no existe.
- `sufijo_confirmacion_correo`: nombra la gestión real en éxito y en fallo; cadena vacía sin intento — para las 3 gestiones.
- `test_identidad_persistente.py`: reproduce EXACTO el hallazgo real — identidad `marcar_verificado` SIN correo, paciente reconocido de una (`"reservar"` directo, sin wizard) → backfill encuentra el correo real entre sus citas previas, lo persiste, y el mensaje final dice *"El correo de reserva fue enviado a tu correo."*
- `test_hrmm_gateway_verification.py`: mismo patrón para **cancelar** y **reprogramar** vía el sub-flujo verificado (el camino real de producción) — ambos ahora disparan el correo real y nombran su gestión.

### 4.2 Pruebas reales contra hrmm-backend (2, ambas ejecutadas en esta sesión, `ZANTIA_RUN_REAL_HRMM_TESTS=1`)

1. **Combinada backfill + mensaje** (`test_backfill_de_correo_y_mensaje_con_tipo_gestion_contra_hrmm_backend_real`): documento/correo 100% sintéticos (`ZANTIA-TEST-086-<epoch>`) — crea cita A con correo real en archivo, simula una identidad "ya verificada de antes del 085/086" en un `identity_store` LOCAL (nunca toca la base real), confirma que el backfill encuentra y persiste el correo real, reserva cita B usando ese correo backfilled contra hrmm-backend real, confirma `correo_confirmacion_enviado is True` y que el mensaje final arma "El correo de reserva fue enviado a tu correo." Limpieza: ambas citas canceladas vía `PATCH` (confirmado con éxito).
   - Encontrado y corregido un bug real de DISEÑO DE TEST en el camino: los 2 turnos elegidos por índice (`opciones[0]`/`opciones[1]`) podían compartir la misma fecha+hora (médicos distintos) y disparar el chequeo anti-duplicado LEGÍTIMO del recado 068 — corregido eligiendo explícitamente 2 turnos con fecha/hora distintas. Confirmado estable corriendo el archivo completo de pruebas reales 2 veces seguidas.
2. Las 2 pruebas reales del recado 085 (correo en el payload de creación) siguen pasando, corridas junto con la nueva.

### 4.3 Suite completa
`.venv/bin/pytest -q`: **633 passed + 17 skipped**, cero regresiones.

## 5. Archivos tocados

- `domains/health/identity_store.py` — `actualizar_correo` (Protocol + SQLite).
- `domains/health/gateway.py` — backfill en `_correo_conocido`, fix del `correo_conocido = None` hardcodeado en `_procesar_intento_de_codigo`, `tipo_gestion` en el sub-flujo verificado.
- `domains/health/models.py` — `sufijo_confirmacion_correo(correo_confirmacion_enviado, tipo_gestion)`.
- `domains/health/agent.py` — `tipo_gestion` en la confirmación de reservar/reprogramar.
- `tests/domains/health/test_identidad_persistente.py`, `test_hrmm_gateway_verification.py`, `test_hrmm_appointment_service.py`, `test_flujo_en_etapas_y_correo.py`, `test_saludo_sin_intencion_no_avanza.py` (fixture actualizada — nueva llamada real a `GET /api/agenda/citas` durante el backfill).

## 6. Siguiente paso

Pedir autorización para commitear/pushear (ya concedida por el usuario en este turno) y pedirle que redespliegue en EasyPanel. Una vez desplegado, el usuario reservará de nuevo con su documento real (72302972, ya reconocido sin wizard) para confirmar en producción real que el correo de confirmación llega esta vez — cierre completo del ciclo abierto desde el recado 085.
