#!/usr/bin/env bash
# Checklist de aislamiento entre proyectos (.claude/rules/aislamiento-entre-proyectos.md).
# Busca, de forma puramente read-only, referencias a nombres/dominios de OTROS proyectos
# dentro del árbol de este proyecto. Cero resultados esperados antes del primer commit.
#
# Uso:
#   scripts/verificar-aislamiento.sh "otro-cliente" "otrodominio.com" "OtroProyecto"
#
# No requiere ningún runtime de stack (Python/Node/etc.) — solo bash + grep + find.
# No modifica nada: es de solo lectura.

set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Uso: $0 <termino-prohibido-1> [termino-prohibido-2 ...]" >&2
  echo "Ejemplo: $0 nombre-cliente-anterior dominio-anterior.com otro-repo-relacionado" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FALLOS=0

echo "Verificando aislamiento en: $ROOT_DIR"
echo

for termino in "$@"; do
  echo "--- Buscando: '$termino' ---"
  # Excluye .git, node_modules, .venv y el propio .gitkeep vacío
  resultados=$(grep -rIn --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
    --exclude-dir=venv --exclude-dir=__pycache__ -i "$termino" "$ROOT_DIR" 2>/dev/null || true)
  if [ -n "$resultados" ]; then
    echo "⚠️  ENCONTRADO — revisar antes de continuar:"
    echo "$resultados"
    FALLOS=$((FALLOS + 1))
  else
    echo "✅ Sin resultados."
  fi
  echo
done

if [ "$FALLOS" -gt 0 ]; then
  echo "RESULTADO: $FALLOS término(s) encontrados. Corregir antes del primer commit."
  exit 1
else
  echo "RESULTADO: aislamiento verificado, sin referencias a los términos dados."
  exit 0
fi
