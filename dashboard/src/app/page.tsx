import Link from "next/link";
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
import { getKpis, getMonedasPorRegion, getMovimientosDelDia } from "@/lib/queries";

// Renderizado por request, no en build.
//
// Un dashboard muestra el estado ACTUAL del warehouse: prerenderizarlo exigiría una
// base viva en tiempo de build (y el CI construye la imagen sin warehouse). Las
// consultas van contra `marts`, ya agregados y con índices, así que responden en
// milisegundos; el costo de consultar por request es menor que el de servir un
// número viejo sin que nadie lo note.
export const dynamic = "force-dynamic";

const fechaLarga = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("es-AR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });

export default async function Panorama() {
  const [kpis, movimientos, regiones] = await Promise.all([
    getKpis(),
    getMovimientosDelDia(),
    getMonedasPorRegion(),
  ]);

  const subas = movimientos.filter((m) => (m.variacion_pct ?? 0) > 0).length;
  const bajas = movimientos.filter((m) => (m.variacion_pct ?? 0) < 0).length;
  const destacados = movimientos.slice(0, 8);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Panorama</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Tipos de cambio de referencia del BCE contra el euro. Último día publicado:{" "}
          <strong className="text-foreground">{fechaLarga(kpis.ultima_fecha)}</strong>.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          titulo="Observaciones"
          valor={numero(kpis.observaciones)}
          detalle={`${numero(kpis.dias_publicados)} días publicados desde ${kpis.primera_fecha}`}
        />
        <KpiCard
          titulo="Monedas vigentes"
          valor={numero(kpis.vigentes)}
          detalle="Publicadas hoy por el BCE"
        />
        <KpiCard
          titulo="Monedas retiradas"
          valor={numero(kpis.retiradas)}
          detalle="Existen en el histórico y ya no se publican"
        />
        <KpiCard
          titulo="Movimiento del día"
          valor={`${subas} ↑ / ${bajas} ↓`}
          detalle="Contra el cierre publicado anterior"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Mayores movimientos del día</CardTitle>
            <CardDescription>
              Variación contra el día publicado anterior, que no siempre es el día previo: el
              BCE no publica fines de semana ni feriados.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Moneda</TableHead>
                  <TableHead className="hidden sm:table-cell">Región</TableHead>
                  <TableHead className="text-right">Cotización</TableHead>
                  <TableHead className="text-right">Variación</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {destacados.map((m) => (
                  <TableRow key={m.codigo_moneda}>
                    <TableCell>
                      <Link
                        href={`/monedas?codigo=${m.codigo_moneda}`}
                        className="font-medium hover:underline"
                      >
                        {m.codigo_moneda}
                      </Link>
                      <span className="text-muted-foreground ml-2 text-xs">{m.nombre_moneda}</span>
                    </TableCell>
                    <TableCell className="text-muted-foreground hidden sm:table-cell">
                      {m.region}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {cotiz(m.cotizacion)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      <span
                        className={
                          (m.variacion_pct ?? 0) >= 0
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-red-600 dark:text-red-400"
                        }
                      >
                        {pct(m.variacion_pct ?? 0)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Monedas vigentes por región</CardTitle>
            <CardDescription>
              La región sale de un seed versionado, no del origen: la API solo devuelve código y
              nombre.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {regiones.map((r) => (
              <div key={r.region} className="flex items-center justify-between gap-3">
                <span className="text-sm">{r.region}</span>
                <div className="flex flex-1 items-center gap-2">
                  <div className="bg-muted h-2 flex-1 overflow-hidden rounded-full">
                    <div
                      className="bg-primary h-full rounded-full"
                      style={{ width: `${(r.monedas / regiones[0].monedas) * 100}%` }}
                    />
                  </div>
                  <Badge variant="secondary" className="tabular-nums">
                    {r.monedas}
                  </Badge>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
