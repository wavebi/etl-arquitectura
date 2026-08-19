import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Imagen de producción mínima: Next arma un bundle con solo las dependencias que
  // realmente usa, así el contenedor no lleva los ~400 MB de node_modules.
  output: "standalone",
};

export default nextConfig;
