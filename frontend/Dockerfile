# Next.js 16 container (D30): standalone output, non-root, Node 24 LTS.
FROM node:24-bookworm-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:24-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN groupadd --system --gid 10001 web && useradd --system --uid 10001 --gid web --no-create-home web
COPY --from=build --chown=web:web /app/.next ./.next
COPY --from=build --chown=web:web /app/public ./public
COPY --from=build --chown=web:web /app/node_modules ./node_modules
COPY --from=build --chown=web:web /app/package.json ./package.json
USER 10001:10001
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
