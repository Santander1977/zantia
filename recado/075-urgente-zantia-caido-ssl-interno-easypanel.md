# 075 — URGENTE: ZANTIA está caído en producción (SSL interno de EasyPanel, no un bug de código)

**Fecha**: 2026-09-11
**Severidad**: **CRÍTICA** — el proceso de ZANTIA no arranca en absoluto tras el redeploy del commit `4201717`.
**Estado**: Causa raíz y solución REAL confirmadas (ver "Solución confirmada" al final) — el usuario encontró la URL interna real dentro del proyecto de EasyPanel. Pendiente que el usuario cambie la variable de entorno y redespliegue para verificar de punta a punta.

---

## Lo más importante primero

**ZANTIA no está respondiendo ningún tráfico ahora mismo.** El traceback que compartiste no es un fallo de una función puntual (como el resto de los hallazgos de hoy) — es un **crash al arrancar el proceso**, antes de que Uvicorn llegue siquiera a levantar el servidor:

```
File "/app/service/app.py", line 94, in <module>
    _appointment_service = build_appointment_service()
```

`build_appointment_service()` se ejecuta a nivel de MÓDULO (línea 94 de `service/app.py`, fuera de cualquier función) — se llama UNA vez, al importar el archivo, antes de que exista ningún endpoint. Si falla, el proceso entero termina — no es "un endpoint que da error", es que el contenedor nunca llega a aceptar tráfico. Confirmado leyendo el código: no hay ningún `try/except` alrededor de esa línea.

---

## Causa raíz — confirmada, no es un bug de ZANTIA

### 1. El código hace exactamente lo correcto: rechazar un certificado no confiable

`domains/health/hrmm_http.py::RealHttpClient.request` usa `urllib.request.urlopen()` sin ningún contexto SSL personalizado — es decir, usa la verificación ESTÁNDAR de Python contra el almacén de certificados de confianza del sistema. El error `SSLCertVerificationError: self-signed certificate` significa que, en el momento de la conexión, el certificado presentado **no está firmado por ninguna autoridad reconocida** — el código está haciendo su trabajo correctamente al rechazarlo. **No se debe "arreglar" esto deshabilitando la verificación SSL** (`ssl._create_unverified_context()` o similar) — eso abriría la puerta a un ataque de intermediario real contra el tráfico con hrmm-backend (datos de pacientes). No lo voy a hacer, y te recomiendo explícitamente que nadie lo haga como atajo.

### 2. El endpoint público SÍ tiene un certificado válido — confirmado con evidencia directa, no supuesta

Verifiqué la conexión TLS real, desde afuera, contra el mismo hostname que usa `HRMM_BACKEND_URL`:

```
Host: curson8n-hrmm-backend.byrp3l.easypanel.host:443
Verificación TLS: OK (sin excepción)
Emisor: Let's Encrypt
Sujeto: *.byrp3l.easypanel.host
Válido desde: 2026-09-07  |  Válido hasta: 2026-12-06
```

Coincide exactamente con lo que viste en tu navegador. **Confirma tu hipótesis**: el problema no es el certificado público — es específico de la ruta de red que toma la conexión PROGRAMÁTICA desde DENTRO del contenedor de ZANTIA.

### 3. El código usa la URL tal cual, sin ninguna transformación

`domains/health/config.py:build_appointment_service` (línea 85): `url = os.environ.get(config.url_env_var)` — se usa el valor de `HRMM_BACKEND_URL` literal, sin reescribir el hostname, sin lógica condicional. Si el contenedor de ZANTIA ve un certificado autofirmado al conectarse a esa URL y un navegador externo ve uno válido en la MISMA URL, la diferencia está en la capa de red/DNS de EasyPanel entre contenedores, no en este código.

### 4. Sobre `HRMM_BACKEND_URL` — lo que puedo y no puedo confirmar

En el `.env` de esta máquina (que uso para las pruebas reales de esta sesión), `HRMM_BACKEND_URL` es el dominio público (`https://curson8n-hrmm-backend.byrp3l.easypanel.host`) — el mismo que verificaste en el navegador. **No tengo forma de ver qué valor tiene esa misma variable configurada en el entorno REAL de EasyPanel para el servicio ZANTIA** — no tengo acceso a ese panel. Si en EasyPanel está configurada distinto (una IP interna, un hostname `.internal`, etc.), eso lo tendrías que confirmar tú directamente ahí.

---

## Diagnóstico más probable (con la evidencia que tengo, marcado explícitamente como hipótesis, no como hecho confirmado)

Plataformas tipo EasyPanel frecuentemente enrutan el tráfico ENTRE contenedores/servicios del mismo proyecto por una red interna privada, distinta de la ruta pública (que pasa por su proxy con TLS de Let's Encrypt). Si ZANTIA y hrmm-backend están en el mismo proyecto de EasyPanel, es plausible que la resolución DNS interna del contenedor de ZANTIA para ese mismo hostname público apunte a la ruta interna (más rápida, sin salir a internet) — y que esa ruta interna termine el TLS con un certificado autofirmado propio de la plataforma, en vez de pasar por el proxy público con el certificado de Let's Encrypt. **Esto es una hipótesis razonable con la evidencia disponible, no algo que pueda confirmar sin acceso a la configuración de red de EasyPanel.**

## Importante: esto NO lo causó el commit `4201717`

Revisé el diff exacto de ese commit (`git show --stat 4201717`) — solo toca `domains/health/gateway.py`, `.ai/CONVERSATION_COVERAGE.md`, y un archivo de test nuevo. **Ninguno de los 3 tiene relación con HTTP/SSL/configuración de hrmm-backend.** Este problema no es una regresión de mi trabajo de hoy — es una condición de la infraestructura/configuración que existía antes, y que recién se hizo visible en el log que compartiste (posiblemente porque es la primera vez que este entorno específico arranca con `HRMM_BACKEND_ENV=production`, o porque el problema de red interna es intermitente — no lo sé con certeza, y no quiero especular más de lo que la evidencia permite).

---

## Qué necesito de ti para seguir (no puedo resolver esto yo solo — es configuración de EasyPanel, no código)

1. **Confirma qué valor tiene `HRMM_BACKEND_ENV` y `HRMM_BACKEND_URL` en las variables de entorno reales del servicio ZANTIA en EasyPanel** (panel de configuración del servicio, no este `.env` local).
2. **Revisa si EasyPanel ofrece un hostname/URL "interno" distinto para comunicación entre servicios del mismo proyecto** (muchas plataformas lo tienen, a veces documentado como "internal service URL" o similar) — si existe y usa `http://` (sin TLS, por ser red privada) o un certificado propio de esa plataforma que SÍ está en su almacén de confianza, sería la ruta correcta a usar en vez de forzar el tráfico interno por el dominio público.
3. Si EasyPanel no ofrece eso, esto podría requerir soporte de EasyPanel directamente (es su capa de red, no algo que ZANTIA controle).

**Mientras tanto, ZANTIA sigue caído.** Si hrmm-backend estuvo en `mock` antes y recién se cambió a `production`, la opción más rápida para restaurar el servicio (aunque sea temporalmente, sin datos reales) sería volver `HRMM_BACKEND_ENV` a `mock` hasta resolver el problema de red — dime si quieres que documente ese paso con más detalle, o si prefieres investigar primero la causa de red con EasyPanel antes de decidir.

---

## Hallazgo secundario, real, para cuando esto se resuelva (no urgente hoy, documentado por transparencia)

`build_appointment_service()` se ejecuta de forma SÍNCRONA al arrancar el proceso, sin ningún reintento ni modo degradado — cualquier falla de red hacia hrmm-backend en el momento exacto del arranque (esta, o una futura, aunque sea transitoria) tumba el proceso completo, no solo el tramo que depende de hrmm-backend. Esto es una decisión de diseño de que hoy no tiene ningún mecanismo de resiliencia (reintento con backoff, arranque en modo degradado, etc.). No lo toco sin que lo pidas — lo señalo porque es la clase de fragilidad que puede convertir un problema de red transitorio en una caída completa del servicio, como pasó hoy.

---

## Solución confirmada — causa raíz REAL: la URL configurada, no el certificado ni el código

El usuario encontró la URL interna real dentro del proyecto de EasyPanel: `http://curson8n_hrmm-backend:8000/` (nota: `http`, no `https`; guion bajo, no guion — la convención interna de red de EasyPanel para el mismo proyecto). Esto confirma la hipótesis de la sección anterior: el tráfico entre servicios del mismo proyecto EasyPanel usa una red Docker privada, distinta del dominio público — nunca necesitó pasar por TLS ni por el certificado público en primer lugar.

### Verificación ANTES de aplicar el cambio (pedida explícitamente antes de proceder)

**1. ¿`hrmm_http.py`/`config.py` soportan `http://` sin asumir TLS en ningún punto?** Confirmado por inspección Y de forma empírica:

- Grep de "https"/validación de esquema en `hrmm_http.py`, `hrmm_appointment_service.py`, `hrmm_catalog.py`, `config.py`: **cero resultados**. `RealHttpClient.request` usa `urllib.request.urlopen()`, que despacha automáticamente `http://` vs `https://` según el esquema de la URL — nada en el código asume ni fuerza TLS.
- Prueba real: levanté un servidor HTTP local de verdad (sin TLS, `http.server`) y apunté `RealHttpClient(base_url="http://127.0.0.1:<puerto>")` contra él —

  ```
  status: 200
  body: {'ok': True, 'path': '/api/agenda/servicios'}
  ```

  Petición real completa, exitosa, sobre `http://` puro, sin ningún error.

**2. ¿Es correcto el razonamiento de que esto elimina el problema SSL sin "saltarse" la seguridad?** Sí, de acuerdo — TLS protege datos en tránsito sobre una red NO confiable (la internet pública); el tráfico entre servicios del mismo proyecto EasyPanel, por su red Docker privada, nunca fue ese caso. Usar la URL interna es la ruta de red correcta, no una forma de evadir un control de seguridad real. Única salvedad honesta (no bloqueante): no tengo visibilidad de si la red interna de EasyPanel está aislada estrictamente por proyecto — el patrón estándar en plataformas basadas en Docker, y lo más probable — vale la pena confirmarlo con EasyPanel si el usuario quiere certeza total, pero no hay evidencia de que sea un problema real.

**3. Ningún cambio de código** — confirmado, `hrmm_http.py` queda intacto. Este es exclusivamente un cambio de la variable de entorno `HRMM_BACKEND_URL`, aplicado por el usuario directamente en EasyPanel.

### Verificación DESPUÉS del cambio — pendiente

`http://curson8n_hrmm-backend:8000/` es una dirección de la red PRIVADA de EasyPanel — no accesible desde este entorno (sin ruta de red hacia ahí, igual que no hay acceso al panel de EasyPanel). La verificación de los 3 puntos pedidos (arranque sin error, `catalog.sync()` exitoso, una llamada real como `get_availability`) se hará de la MISMA forma en que se diagnosticó el problema original: leyendo los logs de runtime de EasyPanel que el usuario comparta tras el cambio + redeploy — no por conexión directa desde este entorno.

**Pendiente**: que el usuario cambie `HRMM_BACKEND_URL` a `http://curson8n_hrmm-backend:8000/` en EasyPanel, redespliegue, y comparta el log de runtime resultante.

---

## Segundo error tras el cambio — el código queda descartado con evidencia doble

Tras cambiar `HRMM_BACKEND_URL` y redesplegar, el error cambió de `CERTIFICATE_VERIFY_FAILED` a:

```
ssl.SSLError: [SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1016)
```

Esto significa que el proceso SIGUE intentando un handshake TLS — el usuario pidió investigar si `hrmm_http.py` fuerza HTTPS en algún punto antes de sospechar de la variable de entorno.

### Investigación — código descartado con evidencia, no con suposición

1. **Cómo decide `RealHttpClient` entre HTTP/HTTPS**: no lo decide — delega 100% en `urllib.request.urlopen()` (`hrmm_http.py:77`), que despacha según el ESQUEMA de la URL recibida. La URL se arma en `hrmm_http.py:64` (`url = self._base_url + path`); `self._base_url` (línea 53) solo le quita la barra final a lo que llega — nunca toca ni fuerza el esquema.
2. **Cita exacta**: `grep -c "https" domains/health/hrmm_http.py` → **0 resultados** en todo el archivo. Cero lógica de esquema, en ningún punto.
3. **Único punto del repo que lee `HRMM_BACKEND_URL`**: `grep -rn "HRMM_BACKEND_URL" --include="*.py"` (excluyendo tests) → solo `config.py:85` (`url = os.environ.get(config.url_env_var)`), usado literal, sin transformación. No existe ningún otro camino de código que construya esta URL de otra forma.
4. **Prueba directa de que `urllib` respeta el esquema**:
   ```python
   >>> urllib.request.Request("http://curson8n_hrmm-backend:8000/x").type
   'http'
   >>> urllib.request.Request("https://curson8n_hrmm-backend:8000/x").type
   'https'
   ```
5. **Prueba de extremo a extremo ya hecha en la sección anterior**: un servidor HTTP real local + `RealHttpClient` completó una petición exitosa sobre `http://` puro (status 200) — sin ningún error de TLS.

**Conclusión**: el código está descartado como causa, con evidencia doble (lectura completa + comportamiento real verificado). Un `WRONG_VERSION_NUMBER` solo ocurre si la URL que de verdad recibió `urlopen` empezaba con `https://` — lo cual, dado que el código nunca la transforma, solo puede significar que el valor REAL que está usando el proceso en producción no es literalmente `http://curson8n_hrmm-backend:8000`.

### Dos hipótesis concretas (no de código, de configuración/plataforma) — pendiente de confirmar con el usuario

1. El valor guardado en el panel de EasyPanel no quedó exactamente como se pretendía (típicamente: `https://` por error de edición, o un carácter/espacio extra).
2. El "redeploy" reinició el contenedor con la imagen ya construida, pero no refrescó de verdad la variable de entorno del proceso — algunas plataformas distinguen entre reiniciar el contenedor y aplicar un cambio de variables de entorno, que a veces requiere una reconstrucción explícita para que el proceso vuelva a leer `os.environ` desde cero.

**Pendiente**: que el usuario confirme el valor EXACTO (carácter por carácter) que muestra ahora mismo el campo `HRMM_BACKEND_URL` en EasyPanel.
