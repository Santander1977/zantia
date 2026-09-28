# 082 — Fix: timeout de transporte hacia hrmm-backend no capturado, causaba el error genérico "Tuvimos un problema procesando tu mensaje"

**Fecha**: 2026-09-12 (madrugada, continuación de la sesión maratónica del 2026-09-11)
**Tipo**: corrección real, probada (código + tests + reproducción real con credenciales de producción), **NO desplegada** — a la espera de que el usuario redespliegue en EasyPanel tras confirmar el push.
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Continúa**: recado `081` (mensaje honesto cuando hrmm-backend responde `enviado: false`) — este es un fallo DISTINTO, un paso antes: la llamada HTTP ni siquiera llega a completarse.

## 1. El pedido, textual (resumen)

El sitio real `chat.semcolombia.com` volvió a mostrar "Tuvimos un problema procesando tu mensaje" al identificarse con el documento `72302972`, justo después de que el usuario reiniciara n8n (Task Runner colgado) y redesplegara ZANTIA con el fix del recado 081 ya incluido. Pedido con autonomía completa: investigar, encontrar el traceback real, corregir la causa raíz, verificar, y commitear/pushear sin pausas intermedias.

## 2. Reproducción real, contra el servicio desplegado

```
POST https://curson8n-zantia.byrp3l.easypanel.host/webhook/web  {"message":"hola","sessionId":"auditoria-real-001"}
→ 200, saludo institucional normal (con \n\n, fix del recado 080 confirmado vivo)

POST .../webhook/web  {"message":"72302972","sessionId":"auditoria-real-001"}
→ 200 {"reply":"Tuvimos un problema procesando tu mensaje. Por favor intenta de nuevo en un momento."}
```

Reproducido tal cual reportó el usuario.

## 3. Traceback real — obtenido localmente, sin tocar producción ni agregar logging temporal

En vez de agregar logging temporal y pedir un redeploy solo para verlo (como sugería el pedido como opción), se reprodujo la MISMA secuencia localmente llamando a `handle_inbound_message` directo en Python, con las credenciales reales de producción del `.env` local (mismo patrón ya usado en el recado 080) — así el traceback real queda visible de inmediato, sin pasar por el `except Exception` genérico de `service/app.py`:

```
File ".../domains/health/gateway.py", line 2329, in _iniciar_verificacion_de_identidad
    resultado_envio = gateway.appointment_service.send_verification_code(documento)
File ".../domains/health/hrmm_appointment_service.py", line 344, in send_verification_code
    respuesta = self._http.request(...)
File ".../domains/health/hrmm_http.py", line 77, in request
    with urllib.request.urlopen(solicitud, timeout=self._timeout) as respuesta:
...
File ".../http/client.py", line 277, in _read_status
    line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
...
socket.timeout: The read operation timed out
```

## 4. Causa raíz real, confirmada con evidencia — no asumida

Dos hallazgos, uno estructural (el bug real) y uno circunstancial (el disparador de hoy):

1. **Bug real en `hrmm_http.py:RealHttpClient.request`**: solo capturaba `urllib.error.URLError` para envolver en `HttpError`. Confirmado leyendo la implementación real de `urllib.request.AbstractHTTPHandler.do_open`: ese método solo envuelve en `URLError` los `OSError` ocurridos DENTRO de `h.request(...)` (enviando la solicitud) — `h.getresponse()` (esperando/leyendo la respuesta) queda FUERA de ese `try`, así que un timeout ahí se propaga como `socket.timeout` crudo, nunca como `URLError`. `HttpError` nunca se disparaba para este caso específico — pese a que el propio docstring de la clase ya prometía cubrir "timeout" desde el día 1.
2. **`HttpError` nunca se capturaba en `hrmm_appointment_service.py`** — se importaba (`from .hrmm_http import HttpClient, HttpError`) pero ningún método lo atrapaba. Aunque el punto 1 se hubiera corregido antes, `HttpError` habría seguido escapando de los 3 `except AppointmentServiceError` de `gateway.py` (no es esa clase) y terminando en el `except Exception` genérico de `service/app.py`.
3. **Disparador de hoy (circunstancial, no el bug en sí)**: el usuario reinició n8n (Task Runner colgado) minutos antes — muy probablemente hrmm-backend, al llamar a SU webhook de n8n (`N8N_WEBHOOK_CODIGO_URL`, con su propio timeout de 20s), tardó más de lo normal con n8n recién reiniciado, y el timeout de 10s de ZANTIA hacia hrmm-backend (`RealHttpClient(timeout_seconds=10.0)` default) se disparó primero. Esto es infraestructura transitoria, no algo que este fix resuelva por sí solo — lo que sí resuelve es que ZANTIA deje de mostrar un error genérico y feo cuando esto (o cualquier otro fallo de transporte real) vuelva a pasar.

## 5. La corrección — 2 archivos, mínima y quirúrgica

- **`domains/health/hrmm_http.py`**: `except urllib.error.URLError` → `except OSError` (URLError ya es subclase de OSError, así que esto amplía la cobertura sin duplicar lógica ni tocar el caso ya manejado de `HTTPError`, que se captura antes y por separado).
- **`domains/health/hrmm_appointment_service.py::send_verification_code`**: ahora envuelve la llamada HTTP en `try/except HttpError`, convirtiéndolo en `AppointmentServiceError` — el mismo tipo que los 3 call-sites de `gateway.py` (recado 081) ya sabían manejar con gracia.

No se tocó el timeout de 10s en sí (ni el de hrmm-backend hacia n8n, que es de otro proyecto) — el pedido era corregir el error genérico, no ajustar temporización, y cambiar el valor del timeout no habría evitado que ESTE MISMO bug volviera a aparecer ante cualquier otro fallo de transporte real en el futuro.

**Alcance deliberadamente NO ampliado**: el mismo patrón (`HttpError` nunca capturado) probablemente existe en los demás métodos de `HrmmAppointmentService` (`get_availability`, `book_appointment`, `buscar_paciente`, etc.) — no se tocaron, por ser una ampliación de alcance más allá de la causa raíz de ESTE reporte puntual. Queda como hallazgo para una decisión futura, no una corrección silenciosa de algo no pedido.

## 6. Verificación

### 6.1 Tests nuevos (3)
- `tests/domains/health/test_hrmm_http.py` (2 tests, **con un socket TCP real y local**, sin red externa): un servidor que acepta la conexión y nunca responde reproduce el timeout EXACTO de producción → confirma `HttpError` (no `socket.timeout` crudo). Control con un puerto cerrado (`ConnectionRefusedError`, otro tipo de `OSError`) → mismo resultado.
- `tests/domains/health/test_hrmm_appointment_service.py` (1 test nuevo): `send_verification_code` con un `FakeHttpClient` que lanza `HttpError` → confirma que se relanza como `AppointmentServiceError`.

### 6.2 Suite completa
`python -m pytest -q`: **608 passed + 15 skipped** (605 previas + 3 nuevas) — cero regresiones.

### 6.3 Reproducción real, end-to-end, con credenciales de producción — ANTES de commitear

Mismo mecanismo del recado 080/081 (ZANTIA local, `.env` real de producción, sin tocar EasyPanel):

```
--- turno 2: documento ---
No pude enviarte el código de verificación (verificacion/enviar: fallo de transporte
(The read operation timed out)). Intenta de nuevo en un momento.
```

Ya NO es el error genérico — es el mensaje honesto esperado (mismo texto que ya daba `_iniciar_verificacion_de_identidad` para el caso de HTTP != 200, ahora también alcanzable para fallos de transporte). El timeout real hacia hrmm-backend/n8n SIGUE ocurriendo en este momento (madrugada del 2026-09-12) — eso es infraestructura de otro proyecto, no algo que este fix resuelva — pero el paciente ya no ve un error críptico sin sentido.

**Pendiente, no ejecutable desde esta sesión**: repetir esta misma prueba contra el servicio REAL desplegado (`https://curson8n-zantia.byrp3l.easypanel.host/webhook/web`) después de que el usuario redespliegue — solo entonces se puede confirmar que el mismo comportamiento honesto se ve en producción real, no solo local.

## 7. Commit

`domains/health/hrmm_http.py`, `domains/health/hrmm_appointment_service.py`, `tests/domains/health/test_hrmm_http.py` (nuevo), `tests/domains/health/test_hrmm_appointment_service.py`. Commiteado y pusheado a `origin/main` en la misma sesión (ver hash en el mensaje al usuario) — el usuario pidió explícitamente no pausar para confirmar el commit en este caso puntual.

## 8. Siguiente paso

Pedir al usuario que redespliegue en EasyPanel (única acción que esta sesión no puede hacer), y ofrecer repetir la prueba real contra `chat.semcolombia.com`/`webhook/web` una vez hecho, para cerrar el ciclo de verificación contra el servicio real desplegado — tal como pedía el punto 5 del pedido original.
