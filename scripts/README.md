# scripts/

Utilidades independientes del stack tecnológico del proyecto instanciado. No asumen Python/Node/etc. — son bash puro con herramientas estándar (`grep`, `find`).

- **`verificar-aislamiento.sh`** — implementa el checklist de `.claude/rules/aislamiento-entre-proyectos.md`: busca referencias a nombres/dominios de otros proyectos dentro de este proyecto. Léelo como referencia; en un proyecto instanciado real, seed/migraciones/etc. propios del stack elegido viven también aquí.
