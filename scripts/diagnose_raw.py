#!/usr/bin/env python3
"""Diagnóstico READ-ONLY de la capa raw.

Responde las tres preguntas que aparecen cuando un mart da un número raro:

    1. ¿Hay filas duplicadas por clave natural? Si las hay, el `primary_key` del
       resource no identifica de verdad la fila y el merge está insertando en vez
       de pisar: todos los promedios y sumas aguas abajo quedan mal.
    2. ¿Hasta qué fecha llegó cada tabla? Un cursor clavado se ve así.
    3. ¿Cuántas filas tienen el cursor nulo? Son filas que no se pueden ubicar en
       el tiempo (fecha del origen que no se pudo parsear).

No modifica nada. Uso:

    make diagnose                                   # dentro del container
    python scripts/diagnose_raw.py               # con el .env cargado
    python scripts/diagnose_raw.py --table raw_frankfurter_exchange_rates
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.pipelines.frankfurter.constants import RAW_TABLES
from shared.constants import RAW
from shared.settings import settings
from shared.utils.warehouse import get_connection


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """,
        (RAW, table),
    )
    return cur.fetchone() is not None


def diagnose(only: str | None) -> int:
    """Devuelve la cantidad de problemas encontrados (0 = todo bien)."""
    problems = 0
    tables = {t: cfg for t, cfg in RAW_TABLES.items() if not only or t == only}

    if not tables:
        print(f"No hay tablas declaradas que coincidan con {only!r}.")
        print(f"Declaradas: {', '.join(sorted(RAW_TABLES))}")
        return 0

    print(f"Diagnóstico de raw — {settings.DB_NAME}.{RAW} (env={settings.ENV})\n")

    with get_connection() as conn, conn.cursor() as cur:
        for table, config in sorted(tables.items()):
            if not _table_exists(cur, table):
                print(f"  ⚠️  {table:<45} no existe todavía")
                problems += 1
                continue

            cur.execute(f'SELECT count(*) AS n FROM {RAW}."{table}"')
            total = cur.fetchone()["n"]

            primary_key = ", ".join(f'"{c}"' for c in config["primary_key"])
            cur.execute(
                f"""
                SELECT count(*) AS n FROM (
                    SELECT {primary_key} FROM {RAW}."{table}"
                    GROUP BY {primary_key} HAVING count(*) > 1
                ) AS d
                """
            )
            duplicates = cur.fetchone()["n"]

            line = f"  {table:<45} {total:>10,} filas"

            cursor_column = config["cursor"]
            if cursor_column:
                cur.execute(
                    f'SELECT min("{cursor_column}") AS desde, max("{cursor_column}") AS hasta, '
                    f'count(*) FILTER (WHERE "{cursor_column}" IS NULL) AS nulos '
                    f'FROM {RAW}."{table}"'
                )
                row = cur.fetchone()
                line += f"  | {row['desde']} → {row['hasta']}"
                if row["nulos"]:
                    line += f"  ⚠️ {row['nulos']:,} sin fecha"
                    problems += 1

            if duplicates:
                line += f"  ⚠️ {duplicates:,} claves duplicadas"
                problems += 1

            print(line)

    if problems:
        print(f"\n⚠️  {problems} problema(s) para revisar. Ver docs/runbook.md.")
    else:
        print("\n✅ Sin problemas detectados.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico read-only de raw.")
    parser.add_argument("--table", help="Analizar solo esta tabla.")
    args = parser.parse_args()
    return 1 if diagnose(args.table) else 0


if __name__ == "__main__":
    raise SystemExit(main())
