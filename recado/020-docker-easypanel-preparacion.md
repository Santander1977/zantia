# RECADO PARA CHATGPT

Fecha: 2026-09-03
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Retomar Fase A/C del recado 011 (empaquetado Docker real + preparación EasyPanel) — BLOQUEADA por falta de Docker en esta máquina
Objetivo: Confirmar si Docker está disponible (no lo está), dar instrucciones exactas de instalación, y entregar lo que SÍ se pudo preparar sin Docker: lista de variables de entorno verificada contra el código real, datos exactos para EasyPanel, y revisión estática de secretos.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = bloqueado, nunca simulado.

---

## Resumen ejecutivo

HECHO: `docker version` → `command not found`. Docker sigue sin estar instalado en esta máquina (misma situación que recado 011). Por instrucción EXPLÍCITA del usuario en este pedido ("si Docker no está disponible... detente ahí — no sigas con un método alternativo sin decírmelo explícitamente"), **NO se hizo ningún workaround con uvicorn+curl esta vez** — los puntos 2 y las verificaciones 1/2/4 del pedido (build real, run real, curl contra el contenedor, suite dentro del contenedor) quedan **PENDIENTES**, bloqueados hasta que el usuario instale Docker.

HECHO: lo que sí se pudo hacer sin Docker — (a) lista exacta y VERIFICADA (no de memoria) de variables de entorno que el proceso real lee, distinguiendo cuáles son necesarias para arrancar, cuáles son opcionales, y cuáles están documentadas pero actualmente SIN NINGÚN EFECTO en el proceso real (hallazgo nuevo); (b) datos exactos para crear el servicio en EasyPanel, verificados contra la estructura real del repo; (c) revisión estática de que el Dockerfile/`.dockerignore` no incluyen ni podrían incluir ningún secreto.

## Qué instalar (para que la próxima sesión pueda continuar con Docker real)

Máquina: macOS 26.5.1, Apple Silicon (arm64), Homebrew disponible (`/opt/homebrew/bin/brew`).

Opción recomendada: **Docker Desktop para Mac (Apple Silicon)**.
```
brew install --cask docker
```
o descargarlo directo de docker.com (elegir la versión "Apple Silicon"). Tras instalar, hay que ABRIR Docker Desktop al menos una vez (arranca el daemon; sin esto `docker version` sigue fallando aunque el binario ya esté instalado). Confirmar con `docker version` que responde tanto el cliente como el servidor antes de continuar.

## Lista EXACTA de variables de entorno (verificada leyendo el código real, no de memoria)

Grep real ejecutado sobre todo el árbol (`os.environ.get`/`os.environ[...]`, incluidos los casos indirectos vía dataclass, ej. `HealthServiceConfig.env_var`) — confirmó estas y ninguna otra:

**Obligatorias para que el contenedor ARRANQUE** (si falta cualquiera, `service/app.py` lanza `HealthConfigError` al importar el módulo — el proceso nunca llega a levantar `/health`):
| Variable | De dónde sale el valor real |
|---|---|
| `CHATWOOT_URL` | De tu instancia de Chatwoot (URL base) |
| `CHATWOOT_ACCOUNT_ID` | De tu instancia de Chatwoot (ID numérico, visible en la URL del panel) |
| `HRMM_BACKEND_URL` *(solo si `HRMM_BACKEND_ENV=production`)* | Copiás el mismo valor real que usás para el servicio de hrmm-backend en EasyPanel |
| `HRMM_BACKEND_SECRET` *(solo si `HRMM_BACKEND_ENV=production`)* | Copiás el MISMO valor que `BACKEND_TRUSTED_SECRET` del lado de hrmm-backend (mismo secreto compartido, nombre de variable distinto a propósito — ver `.ai/SECURITY.md`) |

**Necesarias para que el servicio FUNCIONE bien, pero no bloquean el arranque**:
| Variable | De dónde sale |
|---|---|
| `CHATWOOT_API_TOKEN` | Chatwoot → perfil del agente/bot → Profile Settings → Access Token. Sin ella el contenedor arranca, pero falla al intentar RESPONDER un mensaje real |
| `HRMM_BACKEND_ENV` | La tipeás vos: `production` para el despliegue real (si se omite, cae al default seguro `mock` — NO usaría la agenda real) |

**Opcional, mejora persistencia**:
| Variable | De dónde sale |
|---|---|
| `ZANTIA_IDENTIDAD_DB_PATH` | NUEVA, la generás vos: una ruta de archivo DENTRO del contenedor (ej. `/app/data/identidad_canal.db`). **Importante**: el filesystem de un contenedor en EasyPanel normalmente NO sobrevive un redeploy salvo que montes un volumen persistente — sin volumen configurado, esta variable no logra el objetivo real de "sobrevivir un reinicio" (recado 014/016). Si querés persistencia real, hay que configurar un volumen en EasyPanel apuntando a esa ruta — no lo hice yo, es una decisión/acción tuya en el panel |

**Documentadas en `.env.example` pero SIN EFECTO en el proceso real hoy** (hallazgo de esta sesión — verificado leyendo `core/agent_contract.py` y confirmando que nada las importa en el camino real):
| Variable | Por qué no hace nada hoy |
|---|---|
| `ZANTIA_DB_PATH` | `core/agent_contract.py:build_orchestrator` tiene `SQLiteStateStore(":memory:")` **hardcodeado** — nunca lee esta variable. Configurarla no cambia nada (brecha de wiring preexistente, ya documentada, no resuelta en esta sesión) |
| `ANTHROPIC_API_KEY` | Solo la usaría `core/brain.py:AnthropicBrain`, que nunca se instancia en el camino real de `domains/health` (usa `HealthBrain`, determinista) |

No configurarlas no rompe nada — solo aclarado para que no pierdas tiempo buscándoles un valor real que hoy no se usaría.

## Datos exactos para EasyPanel (verificados contra la estructura real del repo — Dockerfile SÍ se leyó, build/run NO se probaron)

- **Repositorio**: `Santander1977/zantia`
- **Rama**: `main`
- **Builder**: Dockerfile (NO Buildpacks)
- **Ruta de compilación (build context)**: raíz del repo — el `Dockerfile` hace `COPY requirements.txt .` y `COPY . .` asumiendo que el contexto es la raíz
- **Ruta exacta del Dockerfile**: `Dockerfile` (está en la raíz del repo, confirmado con `ls`, no en una subcarpeta)
- **Puerto que expone el contenedor**: `8000` (`EXPOSE 8000`, y el `CMD` corre `uvicorn ... --port 8000` — coincide)

## Verificación estática de secretos (sin Docker, por lectura directa)

HECHO:
- `Dockerfile` leído completo — sin ningún valor de secreto, ARG ni ENV hardcodeado, solo instala dependencias y corre uvicorn.
- `.dockerignore` excluye explícitamente `.env`, `.env.*` (con excepción de `.env.example`), `.git`, `*.db`.
- Confirmado con `ls` que **no existe ningún archivo `.env` real** en todo el árbol de `icaco` — nada que `COPY . .` pudiera copiar por accidente aunque el `.dockerignore` fallara.
- `requirements.txt` revisado — solo nombres de paquetes, sin URLs privadas ni tokens.

Conclusión: el build (cuando se pueda ejecutar) no debería incluir ningún secreto — pero esto es lectura estática, no un build real; la verificación completa pedida (`docker build` real + inspección de la imagen resultante) sigue PENDIENTE.

## Pendiente (bloqueado, no resuelto aquí)

1. Instalar Docker Desktop (arriba).
2. `docker build` real — mostrar salida completa.
3. `docker run` real + `curl` real a `GET /health` contra el contenedor.
4. Suite de tests completa DENTRO del contenedor (no solo en el entorno local ya usado durante toda esta sesión).
5. Confirmar volumen persistente en EasyPanel si se quiere que `ZANTIA_IDENTIDAD_DB_PATH` sobreviva un redeploy.

Ninguno de estos 5 puntos se simuló ni se dio por hecho — quedan explícitamente sin verificar hasta que Docker esté disponible.

RECADO GENERADO: /Users/enzoalfonso/recado/020-docker-easypanel-preparacion.md
