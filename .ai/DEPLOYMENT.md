# DESPLIEGUE — ZANTIA

> Mapa LOCAL → BUILD → DEPLOY → SERVICIO → DOMINIO → DEPENDENCIAS, por componente. Se documenta ANTES del primer deploy real, no se reconstruye después por auditoría.

| Componente | Local (dev) | Build | Deploy | Servicio/dominio | Dependencias |
|---|---|---|---|---|---|
| ZANTIA (service/app.py) | `uvicorn service.app:app --reload` (puerto libre a elección) | `Dockerfile` (raíz, `python:3.11-slim`, patrón idéntico a hrmm-backend/panel-admin) — verificado con Docker real, R-16 RESUELTO | EasyPanel (mismo patrón que hrmm-backend/panel-admin), remoto git en `https://github.com/Santander1977/zantia.git`, R-17 RESUELTO | `https://curson8n-zantia.byrp3l.easypanel.host/` (confirmado real, ver nota 2026-09-10 abajo) | hrmm-backend (vía `HrmmAppointmentService`), Chatwoot (vía `ChatwootChannel`), Telegram (Bot API pública) |

**Estado (2026-09-01, recado 011)**: Dockerfile + `service/app.py` (FastAPI/uvicorn, decisión D-5) construidos y probados localmente SIN Docker (no hay runtime de contenedores en esta máquina — ver R-16): `uvicorn service.app:app` real + `curl` real contra `/health` y `/webhook/chatwoot` funcionando de extremo a extremo con `MockAppointmentService`. 109 tests pasando + 1 deshabilitado a propósito (ver `.ai/TESTING.md`). Plataforma de despliegue: EasyPanel (mismo patrón que hrmm-backend/panel-admin), pendiente el primer despliegue real — lo ejecuta el usuario manualmente.

**Estado (2026-09-10)**: Servicio real creado y corriendo en EasyPanel — el usuario confirmó haber redesplegado tras el commit `093775f` (recado 059) y compartió la URL pública. **[CONFIRMADO]** `GET https://curson8n-zantia.byrp3l.easypanel.host/health` responde real, ahora mismo: `HTTP/2 200`, `server: uvicorn`, body `{"status":"ok"}` — el servicio está arriba y corresponde al stack esperado (FastAPI/uvicorn, mismo patrón que hrmm-backend). **[DESCONOCIDO]** que el commit corriendo sea exactamente `093775f`: `service/app.py` solo expone `/health`, `/webhook/chatwoot` y `/webhook/telegram` — ninguno reporta un hash/versión de build, así que no existe hoy ningún mecanismo para correlacionar el commit desplegado contra `git ls-remote` vía HTTP. La única forma de confirmar el commit exacto sería (a) un endpoint de versión nuevo (no implementado, no pedido), o (b) verificación de comportamiento en una conversación real (p. ej. que el menú ya muestre la 5ta opción "Salir / terminar", exclusiva de `093775f`).

## Checklist mínimo antes de CADA redeploy (recado 068)

> Distinto del checklist de pre-deploy de abajo (ese es sobre requisitos
> de PRODUCTO/arquitectura antes del primer despliegue real con datos
> reales; este es un checklist RÁPIDO y MECÁNICO a correr antes de
> pedirle a EasyPanel que redespliegue, cada vez, sin excepción).

1. Correr `scripts/verificar-antes-de-desplegar.sh` (de solo lectura, nunca toca EasyPanel) — corre la suite completa (incluido el corpus de regresión de conversaciones reales, `tests/domains/health/corpus_regresion/`, automáticamente por ser parte de la suite normal), confirma que no hay cambios sin commitear, e imprime el hash real de `HEAD` comparado contra `origin/main`.
2. Si el script reporta cualquier ADVERTENCIA, resolverla antes de redesplegar (commitear/pushear lo que falte, o investigar el fallo de test).
3. Redesplegar en EasyPanel (acción manual del usuario, regla fija — ver `.claude/rules/proteccion-produccion-y-codigo.md`).
4. Confirmar el commit desplegado con el comportamiento real (ver nota "Estado (2026-09-10)" arriba: `service/app.py` no expone ningún endpoint de versión) — comparar contra el hash impreso por el script en el paso 1.
5. Si algún punto de `.ai/CONVERSATION_COVERAGE.md` cambió en este despliegue, confirmar que esa fila de la matriz está actualizada.

**Hallazgo real que motivó este checklist** (recado 068): el `.env` real de esta máquina tiene `HEALTH_BRAIN_TYPE=llm` configurado — un bug real (`_evaluar_ventana_de_gracia` crasheaba con `AttributeError` con el LLM activo, ver `.ai/CONVERSATION_COVERAGE.md` fila 12) nunca se detectó porque ningún test previo ejercía esa combinación exacta. El corpus de regresión (`tests/domains/health/corpus_regresion/`) y la matriz de cobertura existen precisamente para que el PRÓXIMO hallazgo de este tipo se descubra corriendo la suite, no en una conversación real de un paciente.

## `HRMM_BACKEND_URL` en producción — usar la red INTERNA de EasyPanel, nunca el dominio público (incidente 2026-09-11, recado 075)

> Esta sección documenta un incidente real que tumbó ZANTIA por completo en producción (crash al arrancar, el proceso nunca llegaba a aceptar tráfico) — se deja permanente para que ninguna sesión futura repita la misma investigación desde cero.

**[CONFIRMADO] Valor correcto de `HRMM_BACKEND_URL` cuando ZANTIA y hrmm-backend quedan en el mismo proyecto de EasyPanel:**

```
HRMM_BACKEND_URL=http://curson8n_hrmm-backend:8000
```

Dos detalles del formato que NO son errores de tipeo, son intencionales:
- **`http`, no `https`** — es tráfico interno dentro de la red privada Docker del mismo proyecto EasyPanel, nunca sale a internet, no necesita ni debe llevar TLS en este salto.
- **Guion bajo en el hostname (`curson8n_hrmm-backend`), no guion** — convención de EasyPanel/Docker para el nombre de servicio interno, DISTINTA del dominio público (`curson8n-hrmm-backend.byrp3l.easypanel.host`, con guion).

**Por qué NO usar el dominio público** (`https://curson8n-hrmm-backend.byrp3l.easypanel.host`) **para este tráfico entre servicios**: ese dominio tiene un certificado válido de Let's Encrypt y funciona perfectamente desde AFUERA del proyecto (navegador, esta máquina local, cualquier cliente externo — verificado real: `openssl`/Python `ssl` confirmó el certificado válido, emisor Let's Encrypt, sujeto `*.byrp3l.easypanel.host`). El problema aparece SOLO cuando la conexión se origina DENTRO de otro contenedor del mismo proyecto EasyPanel hacia ese mismo dominio público: esa ruta de red interna no pasa por el proxy que termina el TLS válido — el paciente en ese punto ve un certificado autofirmado que Python (correctamente) rechaza. Usar la URL interna elimina el problema de raíz porque el tráfico nunca sale a internet — no es una forma de evadir seguridad, es la ruta de red correcta para tráfico que siempre fue interno.

**Síntomas exactos a reconocer de inmediato la próxima vez** (para no repetir la investigación completa):

1. Si `HRMM_BACKEND_URL` queda apuntando al dominio PÚBLICO por error, el proceso crashea al arrancar (`service/app.py`, `_appointment_service = build_appointment_service()` corre a nivel de módulo, sin `try/except` — cualquier fallo acá tumba el proceso ENTERO, nunca llega a levantar Uvicorn) con:
   ```
   ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1016)
   ```
2. Si `HRMM_BACKEND_URL` queda con el hostname interno correcto pero el ESQUEMA sigue siendo `https://` (en vez de `http://`) — un error de edición fácil de cometer al cambiar la URL — el síntoma es distinto:
   ```
   ssl.SSLError: [SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1016)
   ```
   (el cliente intenta un handshake TLS contra un servidor interno que habla HTTP plano en el puerto 8000 — confirmado con evidencia de código: `domains/health/hrmm_http.py` no tiene NINGUNA lógica de esquema propia, `RealHttpClient` delega 100% en `urllib.request.urlopen()`, que sí respeta el esquema de la URL recibida — verificado empíricamente con un servidor HTTP real local. Si aparece este error, la causa casi segura es el valor de la variable de entorno, no el código.)

**Riesgo operacional real encontrado en el camino** (recado 075): al editar variables de entorno en el panel de EasyPanel, es fácil perder el NOMBRE de una variable por accidente (dejando solo el valor como una línea huérfana) o vaciar sin querer OTRAS variables sin relación con la que se estaba editando (en este incidente pasó con `HRMM_BACKEND_SECRET`/`TELEGRAM_BOT_TOKEN`/`TELEGRAM_WEBHOOK_SECRET`, ninguna relacionada con `HRMM_BACKEND_URL`). **Recomendación fija**: después de CUALQUIER edición de variables de entorno en EasyPanel, revisar la lista COMPLETA línea por línea (nombre Y valor de cada una, no solo la que se pretendía cambiar) antes de redesplegar — nunca asumir que el resto del panel quedó intacto.

## Checklist de pre-deploy

> Consolidado el 2026-09-01 a partir de `.ai/RISKS.md` (detalle de impacto/evidencia ahí). Ver agente `deployment-checklist`, que solo verifica, nunca ejecuta el deploy.

**Bloqueantes legales/clínicos (antes de cualquier dato real de un usuario final)**
- [ ] Confirmar con el cliente/usuario la jurisdicción/marco legal exacto de protección de datos (R-2).
- [ ] Validar con criterio clínico/legal el protocolo de riesgo/urgencia — sigue siendo el genérico no-médico del Core (R-1).
- [ ] Implementar el mecanismo de acceso/eliminación de datos personales del usuario final, exigido por la regla propia del proyecto (R-3).

**Configuración e integración**
- [x] Construir la capa de configuración que decida `MockAppointmentService` vs. `HrmmAppointmentService` según `HRMM_BACKEND_ENV` (R-5) — `domains/health/config.py`, recado `011`.
- [x] Construir el canal real (`ChatwootChannel`) — probado con fixtures y con un servidor uvicorn real (R-4, parcial: falta conectarlo a un inbox de prueba real).
- [ ] Conectar `ChatwootChannel` a un inbox/número de WhatsApp de PRUEBA real en Chatwoot (nunca el de producción de HRMM) (R-4).
- [x] Diseñar y construir la resolución de la brecha de identidad teléfono↔documento (R-15, recado `012`) — `domains/health/gateway.py:_gestionar_identificacion`, 6 tests con `FakeHttpClient`.
- [ ] Confirmar con evidencia real (red real, `HRMM_BACKEND_ENV=production` de verdad) que el mecanismo de R-15 funciona de punta a punta antes de cambiar el default de `HRMM_BACKEND_ENV` — mientras tanto, desplegar siempre con `mock`.
- [ ] Decidir qué hacer con un paciente genuinamente nuevo (sin historial en hrmm-backend) que `buscar-paciente` no encuentra — decisión de producto pendiente, ver `.ai/RISKS.md` R-15.
- [ ] Ejecutar el test de integración real ya escrito (`ZANTIA_RUN_REAL_HRMM_TESTS`) contra un entorno confirmado con el usuario — no existe staging para hrmm-backend, y no hay `HRMM_BACKEND_SECRET` disponible en esta máquina, decidir cómo probar (R-6, R-7).
- [x] Validar contra datos reales el `estado` de disponibilidad (`BloqueDisponibilidad`) — confirmado real: `"Libre"`/`"Reservado"` (R-9, parcial).
- [ ] Validar contra datos reales el mapeo de `Cita.estado` (`_MAPA_ESTADO_HRMM`) — requiere `HRMM_BACKEND_SECRET`, no usado todavía (R-9, pendiente).
- [ ] Implementar reintento/backoff y manejo de límites de tasa (429) hacia hrmm-backend (R-8).

**Infraestructura**
- [x] Dockerfile construido (patrón hrmm-backend/panel-admin) — verificado con `docker build`/`docker run` reales (R-16 RESUELTO, 2026-09-04).
- [x] Ejecutar `docker build`/`docker run` reales antes del primer despliegue (R-16) — hecho por el usuario.
- [x] Crear un remoto git (ej. GitHub) y hacer push de `main` — `https://github.com/Santander1977/zantia.git` (R-17 RESUELTO, 2026-09-02).
- [x] Crear el servicio en EasyPanel (mismo patrón que hrmm-backend/panel-admin) — servicio real corriendo en `https://curson8n-zantia.byrp3l.easypanel.host/`, confirmado con `GET /health` real (2026-09-10). Commit exacto desplegado no verificable vía HTTP (ver nota "Estado (2026-09-10)" arriba).
- [ ] Decidir mecanismo real que dispare `fire_reminder` a su hora (cron/cola/worker) — hoy se invoca manualmente (R-10).
- [ ] Decidir persistencia real para `ConversationMemory`/`EventLog` (hoy en memoria de proceso) si el despliegue tendrá reinicios o múltiples instancias (R-11).
- [ ] Configurar `ANTHROPIC_API_KEY` y validar `AnthropicBrain` en vivo, si se requiere NLU real más allá de las reglas deterministas actuales (R-13).

**Variables de entorno a completar en el entorno de destino** (ver `.env.example`, nunca con valores en este repo): `ANTHROPIC_API_KEY`, `ZANTIA_DB_PATH`, `ZANTIA_IDENTIDAD_DB_PATH`, `HRMM_BACKEND_ENV`, `HRMM_BACKEND_URL`, `HRMM_BACKEND_SECRET`.

**Chatwoot — OPCIONAL desde recado 024 (decisión D-8)**: `CHATWOOT_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_TOKEN`. Un despliegue que no vaya a usar Chatwoot puede omitirlas — el proceso arranca igual, `POST /webhook/chatwoot` responde `503` explícito si se invoca sin configurar.

**Telegram — `TELEGRAM_BOT_TOKEN` opcional (perezosa, solo se necesita para responder), `TELEGRAM_WEBHOOK_SECRET` OBLIGATORIA si se va a usar este canal** (recados 022/023): sin `TELEGRAM_WEBHOOK_SECRET`, el proceso NO arranca (fail-fast) — a diferencia de Chatwoot, este canal siempre necesita poder validar el origen del webhook, nunca queda expuesto sin esa verificación.
