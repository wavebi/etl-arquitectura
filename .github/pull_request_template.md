## Qué cambia

<!-- Descripción breve. Si toca un mart o un endpoint, decí cuál. -->

## Por qué

<!-- Issue, pedido del cliente, bug. Link si corresponde. -->

## Impacto en datos

- [ ] No cambia datos existentes
- [ ] Requiere backfill / reproceso (indicar deployment y rango)
- [ ] Cambia el contrato de un mart consumido por BI (avisar a quien lo consume)

## Checklist

- [ ] `make lint` y `make test` pasan
- [ ] `make sqlfmt` pasa (si toqué modelos dbt)
- [ ] Modelos nuevos documentados en su `_models.yml` con tests
- [ ] Variables nuevas agregadas a `.env.tpl` / `.env.local.tpl` / `.env.prod.tpl` y a los GitHub Secrets
- [ ] `CLAUDE.md` / `docs/` actualizados si cambió la arquitectura
