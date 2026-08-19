import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function KpiCard({
  titulo,
  valor,
  detalle,
}: {
  titulo: string;
  valor: string;
  detalle?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-muted-foreground text-sm font-medium">{titulo}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="font-heading text-3xl font-semibold tabular-nums">{valor}</p>
        {detalle ? <p className="text-muted-foreground mt-1 text-xs">{detalle}</p> : null}
      </CardContent>
    </Card>
  );
}

/** Formatea un entero con separador de miles en es-AR. */
export const numero = (n: number) => new Intl.NumberFormat("es-AR").format(n);

/** Cotizaciones: hasta 6 decimales, sin ceros de relleno. */
export const cotiz = (n: number) =>
  new Intl.NumberFormat("es-AR", { maximumFractionDigits: 6 }).format(n);

/** Porcentaje con signo explícito: importa ver si subió o bajó. */
export const pct = (n: number) =>
  `${n > 0 ? "+" : ""}${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(n)}%`;
