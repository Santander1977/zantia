# DESPLIEGUE — ZANTIA

> Mapa LOCAL → BUILD → DEPLOY → SERVICIO → DOMINIO → DEPENDENCIAS, por componente. Se documenta ANTES del primer deploy real, no se reconstruye después por auditoría.

| Componente | Local (dev) | Build | Deploy | Servicio/dominio | Dependencias |
|---|---|---|---|---|---|
| ZANTIA (service/app.py) | `uvicorn service.app:app --reload` (puerto libre a elección) | `Dockerfile` (raíz, `python:3.11-slim`, patrón idéntico a hrmm-backend/panel-admin) — **NO verificado con Docker real, ver R-16** | EasyPanel (mismo patrón que hrmm-backend/panel-admin) — **PENDIENTE: sin remoto git, ver R-17** | Sin dominio propio decidido todavía | hrmm-backend (vía `HrmmAppointmentService`), Chatwoot (vía `ChatwootChannel`) |

**Estado (2026-09-01, recado 011)**: Dockerfile + `service/app.py` (FastAPI/uvicorn, decisión D-5) construidos y probados localmente SIN Docker (no hay runtime de contenedores en esta máquina — ver R-16): `uvicorn service.app:app` real + `curl` real contra `/health` y `/webhook/chatwoot` funcionando de extremo a extremo con `MockAppointmentService`. 109 tests pasando + 1 deshabilitado a propósito (ver `.ai/TESTING.md`). Plataforma de despliegue: EasyPanel (mismo patrón que hrmm-backend/panel-admin), pendiente el primer despliegue real — lo ejecuta el usuario manualmente.

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
- [x] Dockerfile construido (patrón hrmm-backend/panel-admin) — **NO verificado con `docker build`/`docker run` reales** (no hay runtime de contenedores en esta máquina) (R-16).
- [ ] Ejecutar `docker build`/`docker run` reales antes del primer despliegue (R-16) — lo hace el usuario, donde sí hay Docker.
- [ ] Crear un remoto git (ej. GitHub) y hacer push de `main` — EasyPanel necesita un repo real para desplegar, y este repo no tiene remoto configurado (R-17).
- [ ] Crear el servicio en EasyPanel (mismo patrón que hrmm-backend/panel-admin): repo (pendiente R-17), rama `main`, Dockerfile en la raíz (`Dockerfile`), puerto `8000`.
- [ ] Decidir mecanismo real que dispare `fire_reminder` a su hora (cron/cola/worker) — hoy se invoca manualmente (R-10).
- [ ] Decidir persistencia real para `ConversationMemory`/`EventLog` (hoy en memoria de proceso) si el despliegue tendrá reinicios o múltiples instancias (R-11).
- [ ] Configurar `ANTHROPIC_API_KEY` y validar `AnthropicBrain` en vivo, si se requiere NLU real más allá de las reglas deterministas actuales (R-13).

**Variables de entorno a completar en el entorno de destino** (ver `.env.example`, nunca con valores en este repo): `ANTHROPIC_API_KEY`, `ZANTIA_DB_PATH`, `ZANTIA_IDENTIDAD_DB_PATH`, `HRMM_BACKEND_ENV`, `HRMM_BACKEND_URL`, `HRMM_BACKEND_SECRET`.

**Chatwoot — OPCIONAL desde recado 024 (decisión D-8)**: `CHATWOOT_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_TOKEN`. Un despliegue que no vaya a usar Chatwoot puede omitirlas — el proceso arranca igual, `POST /webhook/chatwoot` responde `503` explícito si se invoca sin configurar.

**Telegram — `TELEGRAM_BOT_TOKEN` opcional (perezosa, solo se necesita para responder), `TELEGRAM_WEBHOOK_SECRET` OBLIGATORIA si se va a usar este canal** (recados 022/023): sin `TELEGRAM_WEBHOOK_SECRET`, el proceso NO arranca (fail-fast) — a diferencia de Chatwoot, este canal siempre necesita poder validar el origen del webhook, nunca queda expuesto sin esa verificación.
