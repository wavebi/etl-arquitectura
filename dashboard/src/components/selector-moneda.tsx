"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Opcion = { codigo_moneda: string; nombre_moneda: string; es_vigente: boolean };

/**
 * Selector de moneda y de rango. Escribe en la query string y deja que el Server
 * Component vuelva a consultar: así el filtrado ocurre en Postgres y no se manda al
 * navegador una serie de 27 años para recortarla en JS.
 */
export function SelectorMoneda({
  monedas,
  codigo,
  rango,
}: {
  monedas: Opcion[];
  codigo: string;
  rango: string;
}) {
  const router = useRouter();
  const params = useSearchParams();

  const navegar = (clave: string, valor: string) => {
    const siguiente = new URLSearchParams(params.toString());
    siguiente.set(clave, valor);
    router.push(`/monedas?${siguiente.toString()}`);
  };

  const vigentes = monedas.filter((m) => m.es_vigente);
  const retiradas = monedas.filter((m) => !m.es_vigente);

  return (
    <div className="flex flex-wrap gap-3">
      <Select value={codigo} onValueChange={(v) => navegar("codigo", v)}>
        <SelectTrigger className="w-[280px]">
          <SelectValue placeholder="Elegí una moneda" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Vigentes</SelectLabel>
            {vigentes.map((m) => (
              <SelectItem key={m.codigo_moneda} value={m.codigo_moneda}>
                {m.codigo_moneda} — {m.nombre_moneda}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectGroup>
            <SelectLabel>Retiradas</SelectLabel>
            {retiradas.map((m) => (
              <SelectItem key={m.codigo_moneda} value={m.codigo_moneda}>
                {m.codigo_moneda} — {m.nombre_moneda}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      <Select value={rango} onValueChange={(v) => navegar("rango", v)}>
        <SelectTrigger className="w-[180px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="1a">Último año</SelectItem>
          <SelectItem value="5a">Últimos 5 años</SelectItem>
          <SelectItem value="10a">Últimos 10 años</SelectItem>
          <SelectItem value="todo">Todo el histórico</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
