# D-5: Empaquetado de ZANTIA como servicio HTTP con FastAPI+uvicorn, y canal real vía Chatwoot

**Decisión**: Introducir FastAPI+uvicorn como la capa de transporte HTTP del proceso ZANTIA (`service/app.py`), exclusivamente para exponer `GET /health` y `POST /webhook/chatwoot` — el Core y los dominios (`core/`, `domains/health/`) siguen siendo 100% stdlib, sin ningún framework nuevo en su lógica interna. El canal real de mensajería se implementa como `ChatwootChannel` (`channels/chatwoot_channel.py`), cumpliendo el `Channel` Protocol existente (`channels/contract.py`, sin modificarlo) sin reemplazar `MockChannel`.

**Motivo**: D-1 (stack del Core) decidió minimalismo stdlib para la LÓGICA del proyecto (evitar ORM, evitar `requests`) — nunca prohibió explícitamente un framework HTTP para el proceso de entrada, porque en ese momento no existía la necesidad de exponer un servicio real. Ahora sí existe (2026-09-01): ZANTIA necesita un servicio HTTP real para recibir webhooks de Chatwoot y desplegarse en EasyPanel junto al resto del ecosistema (hrmm-backend, panel-admin), que ya usan FastAPI+uvicorn.

**Alternativas consideradas**:
1. `http.server` (stdlib puro, `BaseHTTPRequestHandler`) — cero dependencias nuevas, coherente al 100% con D-1.
2. FastAPI+uvicorn — mismo patrón que hrmm-backend/panel-admin (`app/main.py`, puerto 8000, `Dockerfile` idéntico en forma), validación automática de payloads con pydantic (ya es dependencia del proyecto).
3. Flask+gunicorn — patrón intermedio, sin precedente en este ecosistema.

**Ventajas de la opción elegida (2, FastAPI+uvicorn)**:
- Reutiliza EXACTAMENTE el patrón de despliegue ya probado y funcionando en EasyPanel para hrmm-backend/panel-admin (mismo `Dockerfile`, mismo `EXPOSE 8000`, mismo comando `uvicorn ... --host 0.0.0.0 --port 8000`) — reduce el riesgo de un despliegue nuevo con un patrón nunca antes usado en este ecosistema.
- pydantic (ya dependencia real del Core, D-1) se integra nativamente para validar el payload del webhook de Chatwoot.
- Documentación automática (`/docs`) útil para depurar el webhook manualmente durante la prueba con Andrés.

**Desventajas**:
- Añade 2 dependencias nuevas (`fastapi`, `uvicorn`) que D-1 no contemplaba — filosóficamente en tensión con el minimalismo original, aunque D-1 hablaba de la lógica interna, no del transporte HTTP del proceso.
- Superficie nueva de mantenimiento (versiones de FastAPI/uvicorn a mantener al día).

**Riesgo**: Bajo — FastAPI/uvicorn son las mismas versiones de framework ya operando en producción real para hrmm-backend en este mismo ecosistema (EasyPanel), sin incidentes reportados.

**Impacto**: Nuevo archivo `service/app.py` (capa de transporte, sin lógica de dominio), `requirements.txt` actualizado, `Dockerfile` nuevo. `core/` y `domains/health/` sin cambios de dependencias.

**Estado**: IMPLEMENTADA (2026-09-01, recado `011`).
