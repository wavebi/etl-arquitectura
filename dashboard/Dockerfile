# Dashboard de cotizaciones — imagen multi-stage.
#
# Separada del ETL a propósito: son runtimes distintos (Node vs Python) y ciclos de
# vida distintos. Meter Node en la imagen del worker la engordaría sin que el ETL lo
# use nunca.

# ── deps: solo las dependencias, en su propia capa cacheable ──────────────────
FROM node:26-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ── builder: compila la app ───────────────────────────────────────────────────
FROM node:26-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# El build NO consulta la base: todas las páginas con datos declaran
# `dynamic = "force-dynamic"`. Si alguna intentara prerenderizar, este paso fallaría
# con ECONNREFUSED — y sería correcto que fallara: significa que le falta el flag.
RUN npm run build

# ── runner: lo mínimo para servir ─────────────────────────────────────────────
FROM node:26-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Usuario sin privilegios: el proceso solo necesita leer sus propios archivos.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
