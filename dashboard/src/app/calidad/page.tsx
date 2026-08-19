import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { KpiCard, numero } from "@/components/kpi-card";
import { getCoberturaMensual, getIntegridad } from "@/lib/queries";

// Renderizado por request, no en build.
//
// Un dashboard muestra el estado ACTUAL del warehouse: prerenderizarlo exigiría una
// base viva en tiempo de build (y el CI construye la imagen sin warehouse). Las
// consultas van contra `marts`, ya agregados y con índices, así que responden en
// milisegundos; el costo de consultar por request es menor que el de servir un
// número viejo sin que nadie lo note.
export const dynamic = "force-dynamic";

export default async function Calidad() {
  const [integridad, cobertura] = await Promise.all([
    getIntegridad(),
    getCoberturaMensual(18),
  ]);

  const pctVersion = (integridad.version_desconocida / integridad.filas_hecho) * 100;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Calidad del dato</h1>
        <p className="text-muted-foreground mt-1 max-w-3xl text-sm">
          Integridad referencial y cobertura. Estos números existen porque cada dimensión tiene un
          miembro desconocido: con <code className="font-mono">inner join</code> las filas que no
          resuelven desaparecerían y no habría nada que contar.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard titulo="Filas del hecho" valor={numero(integridad.filas_hecho)} />
        <KpiCard
          titulo="Moneda sin resolver"
          valor={numero(integridad.fk_moneda_desconocida)}
          detalle="Debe ser 0"
        />
        <KpiCard
          titulo="Fecha sin resolver"
          valor={numero(integridad.fk_fecha_desconocida)}
          detalle="Debe ser 0"
        />
        <KpiCard
          titulo="Sin versión histórica"
          valor={numero(integridad.version_desconocida)}
          detalle={`${pctVersion.toFixed(1)}% — esperado, ver abajo`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Cómo leer estos números</CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground space-y-3 text-sm">
            <p>
              <strong className="text-foreground">Moneda y fecha sin resolver deben ser 0.</strong>{" "}
              Si suben, entró al hecho un código que la dimensión no conoce. No se pierde la fila
              —para eso está el miembro desconocido— pero hay que mirarlo.
            </p>
            <p>
              <strong className="text-foreground">Sin versión histórica es distinto:</strong> son
              cotizaciones de monedas retiradas que el catálogo del origen nunca publicó, así que
              el snapshot SCD Type 2 no tiene nada que contar sobre ellas. Es una limitación del
              origen, no un defecto del ETL, y por eso se muestra en vez de esconderse en un
              <code className="font-mono"> NULL</code>.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Cobertura mensual</CardTitle>
            <CardDescription>
              Días con publicación y monedas cubiertas. Nunca hay 30 o 31 días: el BCE no publica
              fines de semana ni feriados europeos, así que 20-23 es lo normal.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mes</TableHead>
                  <TableHead className="text-right">Días publicados</TableHead>
                  <TableHead className="text-right">Monedas</TableHead>
                  <TableHead className="text-right">Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cobertura.map((c) => {
                  // Un mes completo tiene entre 18 y 23 días hábiles. Menos de 15
                  // sugiere un hueco de ingesta; el mes en curso siempre está a medias.
                  const parcial = c.dias_publicados < 15;
                  return (
                    <TableRow key={c.anio_mes}>
                      <TableCell className="font-medium">{c.anio_mes}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.dias_publicados}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.monedas}</TableCell>
                      <TableCell className="text-right">
                        <Badge variant={parcial ? "outline" : "secondary"}>
                          {parcial ? "parcial" : "completo"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
