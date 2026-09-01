# Seguridad y secretos

## Reglas obligatorias

- Ningún secreto (API key, contraseña, token, connection string con credenciales) se escribe en código versionado, en `PROJECT.md`, en `.ai/*` ni en ningún archivo trackeado por git. Siempre vía variable de entorno, con un `.env.example` que documenta el NOMBRE de la variable y su propósito, nunca el valor.
- El archivo de contexto de cliente (`docs/CLIENT.local.md`) está en `.gitignore` desde el primer commit del proyecto — no se agrega después de que ya se haya podido commitear por error.
- `.ai/SECURITY.md` mantiene un inventario de qué secretos existen, para qué sirven y dónde se configuran (nombre de la plataforma, nunca el valor) — se actualiza en el mismo cambio que introduce un secreto nuevo.
- Antes de cualquier `git add`/commit, revisar que no se esté incluyendo un archivo de credenciales por accidente, incluso si el nombre del archivo parece inocuo.
- Si un secreto llega a exponerse por error, se reporta como "POSIBLE SECRETO DETECTADO EN: [ruta]" — nunca se muestra el valor, ni siquiera para confirmar el hallazgo.

## Origen de estas reglas

Ninguna vulneración real de este tipo se encontró en el proyecto que originó este ADN — es, precisamente, la práctica que ya funcionaba bien ahí y que esta regla busca preservar como estándar en todo proyecto nuevo, en vez de confiar en que se repita por buena costumbre.
