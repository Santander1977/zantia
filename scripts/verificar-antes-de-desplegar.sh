#!/usr/bin/env bash
# Checklist mínimo antes de cualquier redeploy a producción (recado 068).
# De solo lectura — nunca ejecuta un deploy, nunca toca EasyPanel: esa
# acción sigue siendo, por regla fija del proyecto
# (.claude/rules/proteccion-produccion-y-codigo.md), exclusivamente del
# usuario.
#
# Uso:
#   scripts/verificar-antes-de-desplegar.sh
#
# Qué hace:
#   1. Corre la suite COMPLETA (incluido el corpus de regresión de
#      conversaciones reales, tests/domains/health/corpus_regresion/,
#      que se ejecuta automáticamente por ser parte de la suite normal).
#   2. Confirma que no hay cambios sin commitear en el working tree.
#   3. Imprime el hash real de HEAD y lo compara contra origin/main
#      (git ls-remote) — el mismo commit que EasyPanel va a desplegar,
#      para que el usuario lo compare manualmente contra el hash que
#      EasyPanel muestre tras el deploy (ver .ai/DEPLOYMENT.md).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== 1/3: Suite completa (incluye el corpus de regresión) =="
if [ -x ".venv/bin/pytest" ]; then
  PYTEST=".venv/bin/pytest"
else
  PYTEST="pytest"
fi
"$PYTEST" -q
echo

echo "== 2/3: Working tree limpio =="
if [ -n "$(git status --porcelain)" ]; then
  echo "ADVERTENCIA: hay cambios sin commitear — lo que se despliegue puede NO coincidir con lo que se acaba de probar."
  git status --short
else
  echo "OK — working tree limpio."
fi
echo

echo "== 3/3: Hash real que se desplegaría =="
LOCAL_HASH="$(git rev-parse HEAD)"
REMOTE_HASH="$(git ls-remote origin refs/heads/main | cut -f1)"
echo "HEAD local:      $LOCAL_HASH"
echo "origin/main:     $REMOTE_HASH"
if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
  echo "OK — coinciden. Este es el commit que EasyPanel desplegará."
else
  echo "ADVERTENCIA: HEAD local y origin/main NO coinciden — hace falta 'git push' antes de redesplegar."
fi
echo
echo "Checklist de solo lectura completo. El redeploy en EasyPanel sigue siendo una acción manual del usuario."
