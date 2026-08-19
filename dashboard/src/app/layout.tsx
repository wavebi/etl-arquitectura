import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Cotizaciones BCE — etl-arquitectura",
  description:
    "Tableros sobre los tipos de cambio de referencia del Banco Central Europeo, modelados en esquema estrella.",
};

const NAV = [
  { href: "/", label: "Panorama" },
  { href: "/monedas", label: "Monedas" },
  { href: "/euro", label: "Línea del euro" },
  { href: "/calidad", label: "Calidad del dato" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="es"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="bg-background text-foreground flex min-h-full flex-col">
        <header className="border-b">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-4">
            <Link href="/" className="font-heading text-base font-semibold tracking-tight">
              Cotizaciones BCE
            </Link>
            <nav className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>

        <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">{children}</main>

        <footer className="text-muted-foreground border-t px-6 py-4 text-center text-xs">
          Datos: tipos de cambio de referencia del BCE vía frankfurter.dev · Lectura de{" "}
          <code className="font-mono">marts</code> con el rol <code className="font-mono">bi_reader</code>
        </footer>
      </body>
    </html>
  );
}
