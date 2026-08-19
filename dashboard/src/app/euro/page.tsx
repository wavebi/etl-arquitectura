import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { numero } from "@/components/kpi-card";
import { getMonedasRetiradas } from "@/lib/queries";

// Renderizado por request, no en build.
//
// Un dashboard muestra el estado ACTUAL del warehouse: prerenderizarlo exigiría una
// base viva en tiempo de build (y el CI construye la imagen sin warehouse). Las
// consultas van contra `marts`, ya agregados y con índices, así que responden en
// milisegundos; el costo de consultar por request es menor que el de servir un
// número viejo sin que nadie lo note.
export const dynamic = "force-dynamic";

/**
 * Las monedas que el origen dejó de publicar.
 *
 * Es el tablero más distintivo de esta fuente, y sale gratis del modelo: la
 * dimensión conserva las monedas retiradas (`es_vigente = false`) justamente para
 * que ningún hecho histórico quede huérfano. El efecto lateral es que la dimensión
 * cuenta, sola, la historia de la ampliación de la eurozona.
 */
export default async function LineaDelEuro() {
  const retiradas = await getMonedasRetiradas();

  // El BCE deja de publicar una moneda el último día hábil del año en que su país
  // adopta el euro. Agrupar por año hace visible ese patrón.
  const porAnio = retiradas.reduce<Record<number, typeof retiradas>>((acc, m) => {
    (acc[m.anio_salida] ??= []).push(m);
    return acc;
  }, {});
  const anios = Object.keys(porAnio)
    .map(Number)
    .sort((a, b) => b - a);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Línea del euro</h1>
        <p className="text-muted-foreground mt-1 max-w-3xl text-sm">
          {numero(retiradas.length)} monedas aparecen en el histórico y ya no se publican. Casi
          todas dejan de cotizar un <strong>31 de diciembre</strong>, porque su país adoptó el
          euro el 1° de enero siguiente. Las excepciones tienen su propia historia.
        </p>
      </div>

      <div className="space-y-6">
        {anios.map((anio) => (
          <div key={anio} className="grid gap-4 sm:grid-cols-[6rem_1fr]">
            <div className="flex sm:justify-end">
              <span className="font-heading text-muted-foreground text-2xl font-semibold tabular-nums">
                {anio}
              </span>
            </div>
            <div className="border-border space-y-3 border-l pl-5">
              {porAnio[anio].map((m) => {
                const cierraElAnio = m.ultima_fecha.endsWith("-12-31") || m.ultima_fecha.endsWith("-12-30") || m.ultima_fecha.endsWith("-12-29");
                return (
                  <Card key={m.codigo_moneda}>
                    <CardHeader className="pb-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-base">
                          <Link
                            href={`/monedas?codigo=${m.codigo_moneda}&rango=todo`}
                            className="hover:underline"
                          >
                            {m.codigo_moneda} — {m.nombre_moneda}
                          </Link>
                        </CardTitle>
                        <Badge variant="secondary">{m.region}</Badge>
                        {cierraElAnio ? (
                          <Badge variant="outline">adopta el euro</Badge>
                        ) : (
                          <Badge variant="destructive">baja fuera de calendario</Badge>
                        )}
                      </div>
                      <CardDescription>
                        Publicada del {m.primera_fecha} al {m.ultima_fecha} ·{" "}
                        {numero(m.cantidad_dias_cotizados)} días cotizados
                      </CardDescription>
                    </CardHeader>
                  </Card>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Por qué esto importa para el modelo</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground space-y-2 text-sm">
          <p>
            El catálogo del origen (<code className="font-mono">/currencies</code>) devuelve solo
            las monedas de hoy e ignora cualquier fecha. Si la dimensión se armara con él, un
            tercio de los hechos históricos no tendría fila a la cual apuntar.
          </p>
          <p>
            Por eso se construye con la <strong>unión</strong> de lo observado en las cotizaciones
            y el catálogo actual. Estas {numero(retiradas.length)} monedas existen en la dimensión
            precisamente para que los hechos de 1999 sigan siendo consultables hoy.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
