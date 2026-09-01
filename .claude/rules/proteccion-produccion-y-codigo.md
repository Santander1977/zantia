# Protección de producción y de código existente

## Reglas obligatorias

- **Nunca** ejecutar un comando que pueda afectar un servicio en producción (deploy, reinicio, migración aplicada contra la base real, rotación de credenciales) sin autorización explícita del usuario en esa sesión concreta — una autorización dada para una acción no cubre una acción distinta, aunque sea similar.
- **Nunca** desactivar un gate de seguridad (auth, rate limit) "temporalmente para probar algo" contra un entorno que sirve tráfico real.
- Toda migración de esquema es **aditiva por defecto**. Una migración destructiva (borrar columna/tabla, cambio de tipo con pérdida de datos) requiere aprobación explícita y un plan de rollback documentado antes de aplicarse.
- Antes de modificar un archivo, verificar con `git status`/`git diff` si ya tiene cambios sin commitear que no se originaron en esta sesión. Si los hay, tratarlos como trabajo en curso de otra persona/sesión — nunca sobreescribir sin señalarlo primero.
- No refactorizar código que no es objeto directo de la tarea encomendada, aunque se detecte deuda técnica al pasar por ahí — documentarla, no corregirla sin que se pida.
- Ningún commit se crea salvo pedido explícito del usuario en el turno correspondiente. Ningún push, jamás, sin pedido explícito.
- Todo cambio de estructura/reorganización de carpetas se hace en una rama separada, nunca directo sobre la rama de trabajo activa si esta tiene cambios sin commitear pendientes de decisión.
- Todo cambio de estructura se hace en commits separados y reversibles (`git revert`), nunca con operaciones que reescriban historia compartida (`reset --hard`, `push --force`) salvo pedido explícito del usuario.
- Antes de mover cualquier carpeta usada por un build de despliegue (Dockerfile, config de la plataforma de hosting), probar el build en una rama aparte.
- Antes de tocar un componente marcado como 🔴 CRÍTICO en `.ai/ARCHITECTURE.md`, confirmar explícitamente con el usuario, aunque el cambio parezca menor.

## Origen de estas reglas

Extraídas directamente de incidentes reales evitados en un proyecto en producción: trabajo real sin commitear encontrado simultáneamente en 2 repos distintos durante una auditoría (pudo haberse perdido con una operación ciega), y la ausencia de Docker local que hace que un `Dockerfile` roto solo se detecte en el deploy remoto.
