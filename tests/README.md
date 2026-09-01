# tests/

En un proyecto instanciado, los tests de cada componente viven co-ubicados dentro de ese componente (ej. `backend/tests/`, no aquí). Este `tests/` raíz es **solo** para:

1. Pruebas de contrato/integración que cruzan más de un componente (ver `.claude/rules/testing.md`).
2. En `PROJECT-TEMPLATE` mismo (antes de instanciar cualquier proyecto): la auto-validación de que la plantilla no contiene secretos ni conocimiento específico de otro proyecto — ver `validar-plantilla.sh`.

No se crean aquí tests unitarios de un componente específico — eso rompería el principio de que cada componente es dueño de sus propios tests.

## ⚠️ `validar-plantilla.sh` NO se copia a proyectos nuevos

Este script es la auto-validación de `PROJECT-TEMPLATE` **en sí mismo**, antes de su primer uso — su checklist verifica específicamente que la plantilla no arrastre restos del proyecto real que originó este ADN. Un proyecto instanciado con `/new-project` **no debe heredar este archivo**: su lista de términos ya no tendría sentido ahí y generaría ruido/falsos positivos permanentes. Lo que sí viaja con cada proyecto nuevo es `scripts/verificar-aislamiento.sh` (genérico, recibe los términos a verificar como argumentos, sin nada hardcodeado).
