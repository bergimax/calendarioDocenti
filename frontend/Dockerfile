# Frontend: TanStack Start (nitro node-server preset, see vite.config.ts).
# Multi-stage: nitro's build output is fully self-contained (it traces and
# bundles its own minimal node_modules), so the runtime stage needs nothing
# beyond Node itself - no npm install at runtime, no dev toolchain shipped.

FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
COPY --from=build /app/.output ./.output
ENV HOST=0.0.0.0
ENV PORT=3000
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
