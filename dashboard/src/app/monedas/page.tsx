import { Suspense } from "react";
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
import { KpiCard, cotiz, numero, pct } from "@/components/kpi-card";
import { SelectorMoneda } from "@/components/selector-moneda";
import { SerieChart } from "@/components/serie-chart";
import { getMonedas, getResumenMensual, getSerie } from "@/lib/queries";

// Renderizado por request, no en build.
//
// Un dashboard muestra el estado ACTUAL del warehouse: prerenderizarlo exigiría una
// base viva en tiempo de build (y el CI construye la imagen sin warehouse). Las
// consultas van contra `marts`, ya agregados y con índices, así que responden en
// milisegundos; el costo de consultar por request es menor que el de servir un
// número viejo sin que nadie lo note.
export const dynamic = "force-dynamic";

const RANGOS: Record<string, number | null> = { "1a": 1, "5a": 5, "10a": 10, todo: null };

/** Convierte el rango elegido en la fecha desde la que se consulta. */
function desdeDe(rango: string): string {
  const anios = RANGOS[rango] ?? null;
  if (anios === null) return "1900-01-01";
  const d = new Date();
  d.setFullYear(d.getFullYear() - anios);
  return d.toISOString().slice(0, 10);
}

export default async function Monedas({
  searchParams,
}: {
  searchParams: Promise<{ codigo?: string; rango?: string }>;
}) {
  const { codigo = "USD", rango = "5a" } = await searchParams;

  const monedas = await getMonedas();
  const elegida = monedas.find((m) => m.codigo_moneda === codigo) ?? monedas[0];

  const [serie, mensual] = await Promise.all([
    getSerie(elegida.codigo_moneda, desdeDe(rango)),
    getResumenMensual(elegida.codigo_moneda, 12),
  ]);

  const ultimo = serie.at(-1);
  const primero = serie.at(0);
  const variacionRango =
    ultimo && primero ? ((ultimo.cotizacion - primero.cotizacion) / primero.cotizacion) * 100 : 0;
  const maximo = serie.length ? Math.max(...serie.map((p) => p.cotizacion)) : 0;
  const minimo = serie.length ? Math.min(...serie.map((p) => p.cotizacion)) : 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">
            EUR → {elegida.codigo_moneda}
            {!elegida.es_vigente && (
              <Badge variant="outline" className="ml-3 align-middle">
                retirada
              </Badge>
            )}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {elegida.nombre_moneda} · {elegida.region} · publicada entre {elegida.primera_fecha} y{" "}
            {elegida.ultima_fecha}
          </p>
        </div>
        <Suspense fallback={null}>
          <SelectorMoneda monedas={monedas} codigo={elegida.codigo_moneda} rango={rango} />
        </Suspense>
      </div>

      {serie.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground py-10 text-center text-sm">
            No hay cotizaciones en ese rango. Esta moneda se publicó hasta{" "}
            {elegida.ultima_fecha}: probá con &ldquo;Todo el histórico&rdquo;.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              titulo="Última cotización"
              valor={cotiz(ultimo!.cotizacion)}
              detalle={`al ${ultimo!.fecha}`}
            />
            <KpiCard
              titulo="Variación del rango"
              valor={pct(variacionRango)}
              detalle={`desde ${primero!.fecha}`}
            />
            <KpiCard titulo="Máximo" valor={cotiz(maximo)} detalle="en el rango elegido" />
            <KpiCard titulo="Mínimo" valor={cotiz(minimo)} detalle="en el rango elegido" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Evolución diaria</CardTitle>
              <CardDescription>
                {numero(serie.length)} días publicados. Cuántos euros hacen falta para comprar una
                unidad de {elegida.codigo_moneda} — o al revés, cuántas unidades da un euro.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SerieChart datos={serie} etiqueta={elegida.codigo_moneda} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resumen mensual</CardTitle>
              <CardDescription>
                Sale de <code className="font-mono text-xs">rpt_cotizacion_mensual</code>, la tabla
                agregada: el tablero no recalcula 265.000 filas en cada refresh.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mes</TableHead>
                    <TableHead className="text-right">Días</TableHead>
                    <TableHead className="text-right">Apertura</TableHead>
                    <TableHead className="text-right">Cierre</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Mínima</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Máxima</TableHead>
                    <TableHead className="text-right">Volatilidad</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mensual.map((m) => (
                    <TableRow key={m.anio_mes}>
                      <TableCell className="font-medium">{m.anio_mes}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {m.cantidad_dias_publicados}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {cotiz(m.cotizacion_apertura)}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {cotiz(m.cotizacion_cierre)}
                      </TableCell>
                      <TableCell className="hidden text-right font-mono tabular-nums sm:table-cell">
                        {cotiz(m.cotizacion_minima)}
                      </TableCell>
                      <TableCell className="hidden text-right font-mono tabular-nums sm:table-cell">
                        {cotiz(m.cotizacion_maxima)}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-right font-mono tabular-nums">
                        {cotiz(m.volatilidad_pct)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
