"use client";

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export type Punto = { fecha: string; cotizacion: number };

const config = {
  cotizacion: { label: "Cotización", color: "var(--chart-1)" },
} satisfies ChartConfig;

/**
 * Serie temporal de una cotización.
 *
 * El eje Y NO arranca en cero a propósito: son tipos de cambio, donde lo que importa
 * es la variación relativa. Forzar el cero aplastaría un movimiento del 3% —que en
 * una moneda es enorme— hasta volverlo invisible.
 */
export function SerieChart({ datos, etiqueta }: { datos: Punto[]; etiqueta: string }) {
  const formatoFecha = (v: string) =>
    new Date(`${v}T00:00:00`).toLocaleDateString("es-AR", { month: "short", year: "2-digit" });

  return (
    <ChartContainer config={config} className="h-[320px] w-full">
      <AreaChart data={datos} margin={{ left: 4, right: 12, top: 8 }}>
        <defs>
          <linearGradient id="relleno" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-cotizacion)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--color-cotizacion)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="fecha"
          tickLine={false}
          axisLine={false}
          minTickGap={48}
          tickFormatter={formatoFecha}
        />
        <YAxis
          domain={["auto", "auto"]}
          tickLine={false}
          axisLine={false}
          width={64}
          tickFormatter={(v: number) =>
            new Intl.NumberFormat("es-AR", { maximumFractionDigits: 4 }).format(v)
          }
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(v) =>
                new Date(`${v}T00:00:00`).toLocaleDateString("es-AR", {
                  day: "2-digit",
                  month: "long",
                  year: "numeric",
                })
              }
              formatter={(value) => [
                new Intl.NumberFormat("es-AR", { maximumFractionDigits: 6 }).format(Number(value)),
                ` ${etiqueta}`,
              ]}
            />
          }
        />
        <Area
          dataKey="cotizacion"
          type="monotone"
          stroke="var(--color-cotizacion)"
          strokeWidth={2}
          fill="url(#relleno)"
        />
      </AreaChart>
    </ChartContainer>
  );
}
