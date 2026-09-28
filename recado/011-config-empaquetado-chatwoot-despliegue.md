# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Recado CONSOLIDADO (entregable único pedido explícitamente por el usuario) — capa de configuración Mock/Hrmm, prueba de integración real (bloqueada), empaquetado como servicio HTTP, canal real `ChatwootChannel`, y preparación de despliegue en EasyPanel.
Objetivo: Un solo documento, con autorización explícita del usuario para tomar decisiones técnicas autónomas en los puntos donde antes preguntaba, que reporte: qué se decidió y por qué, qué quedó verificado con evidencia real (comandos ejecutados, no de memoria), y qué queda pendiente de acción manual del usuario.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. INFERENCIA = conclusión razonada, no confirmada. PENDIENTE = decisión o dato aún no confirmable, nunca inventado. Ver recado `009` para el contexto completo del adaptador real a hrmm-backend, y recado `010` para la validación real de `estado` (Fase 1 de la instrucción del usuario — ya cerrada y confirmada por el usuario antes de este recado).

---

## Resumen ejecutivo

HECHO: se construyeron y probaron localmente, con 100% de la suite pasando (**109 tests + 1 deshabilitado a propósito, 110 recolectados**), cuatro piezas nuevas: (1) `domains/health/config.py` — capa de configuración Mock/Hrmm; (2) `channels/chatwoot_channel.py` — canal real de WhatsApp vía Chatwoot; (3) `service/app.py` + `Dockerfile` — empaquetado del proceso como servicio HTTP (decisión D-5); (4) preparación (no ejecución) de los datos de despliegue en EasyPanel.

BLOQUEADO, no inventado: la Fase 3 pedida (prueba de integración real de ESCRITURA contra hrmm-backend — reservar/reprogramar/cancelar con datos de prueba marcados) **no se ejecutó**. No hay `HRMM_BACKEND_SECRET` disponible en esta máquina (ni en `.env`, ni en el entorno del shell) — verificado explícitamente antes de empezar. Por la regla del propio usuario ("si dudas entre producción real o Mock/fixture, quédate en Mock/fixture"), se optó por NO ejecutar ninguna escritura real. Este secreto lo copia el usuario mismo desde EasyPanel — nunca se pide ni se pasa por chat.

BLOQUEADO, no inventado: el build de Docker (`docker build`/`docker run`) **no se pudo verificar** — no hay ningún runtime de contenedores instalado en esta máquina (se buscó `docker`, `podman`, `nerdctl`, `colima`, ninguno encontrado). Se verificó el equivalente funcional más cercano posible: correr `uvicorn service.app:app --host 0.0.0.0 --port 8123` (el mismo comando del `CMD` del Dockerfile) y hacer peticiones `curl` reales contra el servidor vivo.

## FASE 1 (referencia, ya cerrada) — validación de `estado`

Ya completada y confirmada por el usuario en el turno anterior a este recado — ver recado `010-validacion-real-estado-hrmm.md`. No se repitió trabajo aquí.

## FASE 2 — Capa de configuración Mock/Production

**Decisión de diseño** (punto donde antes se habría preguntado): único punto de composición en `domains/health/config.py:build_appointment_service()`, que lee `HRMM_BACKEND_ENV` (default seguro `mock` si no está definida) y construye `MockAppointmentService` o `HrmmAppointmentService`. Acepta un parámetro `http_client` opcional, usado SOLO por los tests (para poder verificar la composición contra `production` sin tocar la red real, inyectando un `FakeHttpClient`) — en uso real, siempre se omite y se construye un `RealHttpClient` real. Ningún otro archivo de `domains/health/` lee `HRMM_BACKEND_ENV`.

**Comportamiento**:
- Sin definir, o `mock` explícito -> `MockAppointmentService()`.
- `production` con `HRMM_BACKEND_URL`+`HRMM_BACKEND_SECRET` completos -> sincroniza el catálogo (`CatalogMirror.sync`) y construye `HrmmAppointmentService` real.
- `production` sin alguna de las dos -> `HealthConfigError` al arrancar (nunca cae al Mock en silencio).
- `staging` -> `HealthConfigError` explícito: no existe un staging real documentado para hrmm-backend (recado `009`) — nunca se inventa una URL ni se redirige a producción.
- Cualquier otro valor -> `HealthConfigError` explícito.

HECHO — 7 tests nuevos, todos pasando: default mock, mock explícito, production completo (con `FakeHttpClient` inyectado — CERO llamadas de red real, verificado contando las llamadas registradas: solo `GET /servicios` y `GET /medicos`, nunca disponibilidad/citas/reservas), production sin URL, production sin secreto, staging, valor desconocido.

## FASE 3 — Prueba de integración real (escritura) — NO EJECUTADA

**Verificación previa realizada** (antes de decidir): se comprobó explícitamente, sin exponer ningún valor, que NINGUNA de estas variables está definida en esta máquina: `HRMM_BACKEND_ENV`, `HRMM_BACKEND_URL`, `HRMM_BACKEND_SECRET`, `ANTHROPIC_API_KEY`, `ZANTIA_DB_PATH` — ni en el entorno del shell ni en un archivo `.env` (no existe `.env` en este proyecto).

**Decisión** (punto donde antes se habría preguntado): sin `HRMM_BACKEND_SECRET`, es físicamente imposible ejecutar `book_appointment`/`reschedule_appointment_verified`/`cancel_appointment_verified` contra la producción real de hrmm-backend. Por instrucción explícita y ya vigente del usuario ("nunca ejecutes una prueba de red real... si dudas, quédate en Mock/fixture y documenta la decisión"), se decidió NO intentar ningún rodeo (no se pidió el secreto por chat, no se buscó en otros proyectos del ecosistema). Se documenta como PENDIENTE, no como hecho.

**Pendiente de acción del usuario**: si se quiere ejecutar esta fase en una sesión futura, el usuario debe colocar `HRMM_BACKEND_SECRET`/`HRMM_BACKEND_URL`/`HRMM_BACKEND_ENV=production` en un archivo `.env` local (ya gitignored) — nunca pegarlo en el chat. El test ya existe y está listo (`test_get_availability_contra_hrmm_backend_real`, gateado por `ZANTIA_RUN_REAL_HRMM_TESTS`), pero cubre solo disponibilidad (lectura); un test de escritura real con limpieza verificada NO está escrito todavía — se escribiría en esa sesión futura, con datos de prueba marcados (ej. documento "0000000001", nombre "PRUEBA ZANTIA INTEGRACION") y limpieza verificada con una consulta real al final, tal como pidió el usuario.

## FASE 4A — Empaquetado como servicio HTTP

**Decisión de diseño, documentada formalmente** (`docs/decisions/d-5-empaquetado-fastapi-chatwoot.md`, D-5): se agregó FastAPI+uvicorn como capa de TRANSPORTE (`service/app.py`), mismo patrón ya probado en `hrmm-backend`/`panel-admin` de este ecosistema (verificado leyendo su `requirements.txt`/`Dockerfile` reales, solo lectura). El Core y los dominios (`core/`, `domains/`) siguen siendo 100% stdlib (D-1 no se toca) — el framework nuevo vive solo en `service/app.py`.

**`GET /health`**: idéntico en forma al de hrmm-backend (`{"status": "ok"}`).

**Composición al arrancar**: `service/app.py` llama `domains.health.config.build_appointment_service()` UNA sola vez al importar el módulo — si `HRMM_BACKEND_ENV=production` está mal configurado, el proceso no arranca (mismo principio de "fallar claro al arrancar, nunca en medio de una conversación" de la Fase 2). Por defecto (sin `HRMM_BACKEND_ENV`), el servicio corre con `MockAppointmentService` — decisión deliberada, nunca `production` por defecto en ningún archivo de plantilla.

**Dockerfile**: idéntico en forma al de hrmm-backend — `python:3.11-slim`, `WORKDIR /app`, `pip install -r requirements.txt`, `EXPOSE 8000`, `CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]`.

**Verificación real ejecutada** (NO Docker — ver bloqueo arriba):
```
uvicorn service.app:app --host 0.0.0.0 --port 8123   (mismo comando del CMD)
curl http://127.0.0.1:8123/health                      -> 200 {"status":"ok"}
curl -X POST http://127.0.0.1:8123/webhook/chatwoot ... -> 200, flujo completo hasta MockAppointmentService
```

**Bug real encontrado con esta verificación manual** (no con el test automatizado — el test usaba un doble de prueba que nunca fallaba): al probar con un dominio de Chatwoot que no resuelve, `_canal.send()` lanzaba `ChatwootChannelError` sin capturar, produciendo un 500 sin contexto en el endpoint del webhook — después de que la lógica de dominio YA había procesado el mensaje del paciente correctamente. Corregido con un `try/except` explícito en `service/app.py:webhook_chatwoot` que registra el error y devuelve `{"procesado": true, "respondido": false, "motivo": ...}` en vez de un 500. Se agregó un test de regresión (`test_webhook_fallo_al_responder_a_chatwoot_no_produce_500`) y se re-verificó con el mismo `curl` real — confirmado, ya no hay 500.

## FASE 4B — Canal real `ChatwootChannel`

**Decisión de diseño** (punto donde antes se habría preguntado): `channels/chatwoot_channel.py`, deliberadamente agnóstico de dominio (no importa nada de `domains/`) — implementa el `Channel` Protocol existente (`channels/contract.py`, sin modificarlo) reconciliando el modelo "pull" del contrato (`receive()`) con el modelo "push" real de un webhook, mediante una cola interna — mismo patrón exacto que `MockChannel.enqueue_patient_message`/`receive`, sin inventar un mecanismo nuevo.

**Filtrado de eco**: `handle_webhook_payload` ignora explícitamente cualquier evento con `message_type != "incoming"` — evita el bucle clásico de procesar el eco de las propias respuestas salientes de ZANTIA.

**No se investigó "TuRed123"**: el usuario mencionó reutilizar el patrón de un proyecto llamado "TuRed123" — se buscó en `/Users/enzoalfonso/Orangutan/` y no se encontró ninguna carpeta con ese nombre ni similar en esta máquina. El diseño de `ChatwootChannel` se basó en el contrato público y bien documentado del evento `message_created` de Chatwoot, no en código de ese proyecto (que no fue accesible). Si "TuRed123" existe en otra ubicación/máquina y tiene diferencias relevantes, deben revisarse en una sesión futura.

**No conectado a ningún inbox real**: cumpliendo el límite explícito del usuario (nunca el número de producción de HRMM 573150434810; si no hay inbox de prueba disponible y no se puede crear, quedarse en mock/fixture) — este agente NO tiene credenciales ni acceso a ninguna instancia de Chatwoot, por lo que no pudo verificar si existe un inbox de prueba ni crear uno. Probado exclusivamente con payloads fijos (fixtures) y, para la verificación de extremo a extremo, con `http_post` sustituido por un doble de prueba — CERO llamadas de red real hacia Chatwoot en toda la sesión.

HECHO — 6 tests nuevos (`tests/channels/test_chatwoot_channel.py`), todos pasando: webhook entrante se traduce correctamente, eco de saliente se ignora, webhook sin remitente falla explícito, `send` responde a la conversación correcta con el payload correcto, `send` sin conversación previa falla explícito, `send` sin token configurado falla explícito.

## Hallazgo no resuelto, documentado explícitamente (no inventado): brecha de identidad teléfono↔documento

Al conectar `ChatwootChannel` con `domains/health/gateway.py:handle_inbound_message`, se encontró que ese contrato ya existente espera `patient_reference` como parámetro — y en TODO el diseño de `HrmmAppointmentService` (recado `009`, decisión D-4), `patient_reference` **ES** el documento de identidad real del paciente. Pero un webhook de WhatsApp solo entrega el NÚMERO de teléfono, no el documento. `HealthGateway._identidad_resuelta` (campo declarado en la Fase bidireccional, recado `008`) nunca se conectó a ninguna resolución real — no existe hoy un endpoint de hrmm-backend para buscar por teléfono (`buscar-paciente` solo acepta `?documento=`).

**No se inventó una solución** — se documentó como riesgo nuevo (`.ai/RISKS.md` R-15) y se mitigó de la única forma honesta disponible: el despliegue real de este servicio corre con `HRMM_BACKEND_ENV=mock` (default seguro), nunca `production`, mientras esta brecha no se resuelva explícitamente (opciones para una sesión futura: pedir el documento al paciente en el primer mensaje de un canal real, o negociar un endpoint nuevo de búsqueda por teléfono con el proyecto hrmm-backend — ninguna de las dos se implementó aquí, es una decisión de producto, no solo técnica).

## FASE 4C — Datos para EasyPanel (preparados, NO ejecutados)

**Repo**: BLOQUEADO — `git remote -v` no devuelve ningún remoto configurado en este proyecto. No es posible dar una URL de repo real porque no existe. **Acción pendiente del usuario**: crear un remoto (ej. GitHub) y hacer `git push` de la rama `main` antes de poder crear el servicio en EasyPanel.

**Rama**: `main` (confirmado con `git branch --show-current`).

**Ruta del Dockerfile**: `Dockerfile` en la raíz del repo (no en una subcarpeta).

**Puerto**: `8000` (`EXPOSE 8000` en el Dockerfile, mismo puerto que `hrmm-backend`).

**Variables de entorno a configurar en EasyPanel** (nombre exacto, nunca el valor por este medio):

| Variable | Obligatoria para arrancar? | De dónde sale el valor |
|---|---|---|
| `CHATWOOT_URL` | Sí | URL de la instancia de Chatwoot del ecosistema |
| `CHATWOOT_ACCOUNT_ID` | Sí | ID de cuenta visible en el panel de Chatwoot |
| `CHATWOOT_API_TOKEN` | No estrictamente para arrancar, sí para poder responder mensajes | Chatwoot -> Profile Settings -> Access Token (del agente/bot) |
| `HRMM_BACKEND_ENV` | No (default seguro `mock`) | Dejar SIN definir o en `mock` hasta resolver R-15 |
| `HRMM_BACKEND_URL` | Solo si `HRMM_BACKEND_ENV=production` | URL real de hrmm-backend (ya conocida: `https://curson8n-hrmm-backend.byrp3l.easypanel.host`) |
| `HRMM_BACKEND_SECRET` | Solo si `HRMM_BACKEND_ENV=production` | Copiar del mismo valor que `BACKEND_TRUSTED_SECRET` en hrmm-backend, desde EasyPanel |
| `ANTHROPIC_API_KEY` | No (Core corre con `FakeBrain`/`HealthBrain`, deterministas) | Solo si se decide activar NLU real |
| `ZANTIA_DB_PATH` | No (default `:memory:`) | Solo si se quiere persistencia real entre reinicios |

## Verificación final

TESTS EJECUTADOS: 110 recolectados (99 anteriores a esta fase + 6 `ChatwootChannel` + 4 `service/app.py`, incluyendo la regresión del bug de 500... nota: 1 test de `service/app.py` se agregó DESPUÉS del bug, son 4 en total en `tests/service/test_app.py`)
TESTS PASANDO: 109
TESTS DESHABILITADOS A PROPÓSITO: 1 (`test_get_availability_contra_hrmm_backend_real`, sin cambios)
TESTS FALLANDO: 0

Comando ejecutado: `.venv/bin/pytest -q` -> `109 passed, 1 skipped`.

## Resumen de decisiones autónomas tomadas (autorización explícita del usuario)

1. FastAPI+uvicorn como transporte HTTP (no `http.server` stdlib puro) — para reutilizar el patrón ya probado del ecosistema en EasyPanel. Documentado como D-5.
2. `patient_reference` = número de WhatsApp cuando el canal es `ChatwootChannel` — funcionalmente correcto para Mock y para correlación, pero deja abierta la brecha de identidad con `HrmmAppointmentService` real (R-15), documentada, no resuelta.
3. Ante Docker no disponible: verificar el equivalente funcional más cercano (uvicorn real + curl real) en vez de omitir la verificación o simular un resultado.
4. Ante secreto no disponible para Fase 3: quedarse en Mock/fixture y documentar, tal como exige la regla explícita del usuario, en vez de buscar un atajo.
5. `/webhook/chatwoot` sin autenticación de origen — documentado como decisión consciente con mitigación mínima (R-18), no como olvido.

## Pendiente de acción MANUAL del usuario (nada de esto lo ejecuta el agente)

1. **Docker real**: ejecutar `docker build -t zantia .` y `docker run -p 8000:8000 --env-file .env zantia` en una máquina con Docker, y confirmar `curl localhost:8000/health` — el agente no tiene runtime de contenedores disponible.
2. **Repo remoto**: crear un remoto git (ej. GitHub) y hacer push de `main` — EasyPanel no puede desplegar sin un repo real.
3. **Crear el servicio en EasyPanel**: usando los datos exactos de la sección "FASE 4C" arriba, una vez exista el remoto.
4. **Inbox de prueba en Chatwoot**: confirmar o crear un inbox/número de WhatsApp de PRUEBA (nunca el 573150434810 de producción de HRMM) y configurar `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID`/`CHATWOOT_API_TOKEN` en EasyPanel.
5. **`HRMM_BACKEND_SECRET`** (solo si se quiere activar `HRMM_BACKEND_ENV=production` en algún momento): copiarlo desde EasyPanel a `.env` local o a las variables de EasyPanel del nuevo servicio — nunca pegarlo en el chat.
6. **Resolver la brecha de identidad teléfono↔documento (R-15)** antes de combinar canal real + `HRMM_BACKEND_ENV=production` — es una decisión de producto (qué pedirle al paciente, o negociar un endpoint nuevo con hrmm-backend), no algo que el agente pueda decidir unilateralmente.
7. **Prueba manual de extremo a extremo** (una vez desplegado y con inbox de prueba conectado): el usuario envía un WhatsApp de prueba al número de prueba; se confirma que Chatwoot dispara el webhook, que ZANTIA responde (visible en los logs de EasyPanel y en la conversación de Chatwoot), y que la respuesta llega al WhatsApp del usuario.

RECADO GENERADO: /Users/enzoalfonso/recado/011-config-empaquetado-chatwoot-despliegue.md
