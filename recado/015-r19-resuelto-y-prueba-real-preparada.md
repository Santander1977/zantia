# RECADO PARA CHATGPT

Fecha: 2026-09-02
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: R-19 confirmado RESUELTO (endpoint real en hrmm-backend) + prueba de extremo a extremo de `identidad_canal` PREPARADA pero NO EJECUTADA contra producción real
Objetivo: Documentar la verificación independiente de que `POST /api/agenda/verificacion/confirmar` está vivo en producción, el diseño de la prueba real de `identidad_canal`, y los dos bloqueos concretos que impiden ejecutarla hoy de punta a punta.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = no ejecutado, nunca inventado.

---

## Resumen ejecutivo

HECHO: R-19 (`.ai/RISKS.md`) se marcó **RESUELTO** — pero no solo porque el usuario lo reportó ("visible en /docs"), sino porque se verificó de forma independiente: `curl https://curson8n-hrmm-backend.byrp3l.easypanel.host/openapi.json` (llamada real, de solo lectura, sin secreto) confirma que `POST /api/agenda/verificacion/confirmar` está registrado en el `openapi.json` de la producción real de hrmm-backend.

HECHO: se escribió `test_identidad_canal_real_e2e` (`tests/domains/health/test_identidad_persistente.py`), una prueba REAL de extremo a extremo contra esa producción — deshabilitada por defecto (`ZANTIA_RUN_REAL_HRMM_TESTS`, mismo patrón que `test_get_availability_contra_hrmm_backend_real`), manual e interactiva (usa `input()`, requiere `pytest -s`). **NO se ejecutó** — dos bloqueos reales, no evitables desde esta sesión:

1. Esta máquina/repo (`icaco`) no tiene `.env` — sin `HRMM_BACKEND_URL`/`HRMM_BACKEND_SECRET` reales configurados, ninguna llamada autenticada es posible (R-6/R-7, ya conocido, sin resolver).
2. El código de verificación se envía por CORREO real — ningún agente puede leer una bandeja de entrada por sí mismo. La prueba pide el código con `input()`, dos veces (identidad + limpieza de la cita de prueba), para que un humano lo teclee en el momento.

HALLAZGO NUEVO (no buscado, encontrado al diseñar la prueba): `HrmmAppointmentService.book_appointment` (ZANTIA) nunca envía el campo `correo` en el body de `POST /api/agenda/citas` — cualquier cita reservada EXCLUSIVAMENTE por WhatsApp/Chatwoot queda sin correo en hrmm-backend, así que `verificacion/enviar` no tendría a dónde mandar un código para ese paciente si nunca tuvo otra cita por otro canal. Documentado como **R-21** (nuevo, MEDIA, ABIERTO) — no corregido, fuera del alcance de este pedido.

## Verificación independiente de R-19 (no solo "el usuario lo dijo")

```
$ curl -sS -o /tmp/hrmm_openapi.json -w "HTTP_STATUS:%{http_code}\n" \
    "https://curson8n-hrmm-backend.byrp3l.easypanel.host/openapi.json"
HTTP_STATUS:200
```
```python
>>> [p for p in openapi["paths"] if "verificacion" in p]
['/api/agenda/verificacion/confirmar', '/api/agenda/verificacion/enviar']
```
Ambos endpoints POST registrados. Sin usar ningún secreto (openapi.json es público, mismo patrón FastAPI por defecto). `.ai/RISKS.md` R-19 actualizado a RESUELTO con esta evidencia, no solo con la palabra del usuario — consistente con `.claude/rules/discovery-antes-de-modificar.md` (nunca `[CONFIRMADO]` sin verificar).

## Diseño de la prueba real (`test_identidad_canal_real_e2e`)

Flujo completo, contra infraestructura real (no `FakeHttpClient`):

1. **Setup**: crea una cita real mínima (`POST /api/agenda/citas` directo, con `correo=ZANTIA_TEST_CORREO_REAL`) para un documento claramente marcado `ZANTIA-TEST-IDENTIDAD-<epoch>` — necesario porque `verificacion/enviar` solo manda correo si hay una cita con correo registrado, y `book_appointment` de ZANTIA no lo manda (R-21, ver arriba) — se usa una llamada HTTP directa, mismo patrón que `_crear_cita_portal` en la suite de hrmm-backend.
2. **Wizard vía `handle_inbound_message`** (el código REAL de `HealthGateway`, no un atajo): "hola" → pide documento → documento → pide código → `input()` con el código real leído del correo → confirma identidad.
3. Verifica `identity_store.get(telefono).estado == VERIFICADO`.
4. **Segundo `HealthGateway`** (simula "otro proceso"), mismo `identity_store` → confirma reconocimiento inmediato sin repetir el wizard (requisito #3, recado 014) — esta vez contra infraestructura real, no solo `FakeHttpClient`.
5. **Limpieza** (finally, mismo rigor que `_cancelar_trusted` de la suite de hrmm-backend): envía un SEGUNDO código real (el primero ya se consumió, un solo uso), `input()` de nuevo, y cancela la cita de prueba — confirmado `AppointmentStatus.CANCELLED`.

## Por qué no se ejecutó hoy

No es una limitación de diseño — es que genuinamente requiere un humano en el bucle dos veces (leer 2 correos reales) y credenciales reales que no viven en este repo. Ninguna de las dos cosas puede resolverlas un agente por su cuenta sin inventar o rodear una restricción de seguridad deliberada (`.claude/rules/seguridad-y-secretos.md`: el usuario copia los secretos, nunca un agente los mueve entre proyectos por su cuenta).

## Pendiente (no resuelto aquí, ni inventado)

- Ejecutar `test_identidad_canal_real_e2e` de verdad: requiere que el usuario configure `icaco/.env` (`HRMM_BACKEND_ENV=production`, `HRMM_BACKEND_URL`, `HRMM_BACKEND_SECRET`, `ZANTIA_TEST_CORREO_REAL`) y corra `pytest -s` él mismo (o en una sesión donde relaye los 2 códigos en vivo).
- R-21 (`book_appointment` sin `correo`) — decisión de diseño pendiente, no trivial (el Protocol `AppointmentService.book_appointment` no recibe un `correo` explícito hoy).
- R-20 (retención de `identidad_canal`) sigue sin resolver, sin cambios desde el recado 014.

RECADO GENERADO: /Users/enzoalfonso/recado/015-r19-resuelto-y-prueba-real-preparada.md
