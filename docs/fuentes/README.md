# Fuentes de datos

Un documento por fuente, con lo que hay que saber para mantenerla. Es lo primero
que se lee cuando algo se rompe y lo primero que se escribe cuando se da de alta.

Plantilla mínima:

```markdown
# <Fuente>

- **Tipo:** API REST / Excel en Drive / base SQL / CSV por SFTP
- **Contacto del lado del cliente:** quién habilita permisos o corrige datos
- **Autenticación:** mecanismo, vencimiento del token, variables de entorno
- **Límites:** cuota de requests, timeout, tamaño máximo de página o de rango

## Recursos que traemos

| Endpoint / archivo | Tabla raw | Clave de negocio | Cursor | Notas |
|---|---|---|---|---|

## Rarezas verificadas

Cosas que se comprobaron empíricamente y no son obvias: endpoints que ignoran el
filtro de fechas, campos que cambian entre corridas, códigos que llegan con ceros
a la izquierda, hojas que el cliente renombra. **Con fecha de verificación**: sin
eso no se sabe si sigue siendo cierto.

## Pendientes con el cliente

Endpoints pedidos y no habilitados, campos que faltan, datos que hoy llegan por
planilla y deberían venir por API.
```
