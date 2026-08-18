# Guía para agentes

Las convenciones, la arquitectura y los invariantes de este proyecto están en
**[CLAUDE.md](CLAUDE.md)**. Leelo antes de tocar código.

Contexto adicional según la tarea:

| Si vas a... | Leé primero |
|---|---|
| entender cómo está armado el ETL | `docs/arquitectura.md` |
| sumar una fuente de datos | `docs/agregar_una_fuente.md` |
| diagnosticar una falla | `docs/runbook.md` |
| tocar deploy o secretos | `docs/deploy.md` |
| entender la fuente de ejemplo | `docs/fuentes/frankfurter.md` |
| cambiar una decisión de arquitectura | `docs/adr/` (y registrá la nueva) |

Antes de dar una tarea por terminada: `make lint && make test` (y `make sqlfmt` si
tocaste modelos dbt).
