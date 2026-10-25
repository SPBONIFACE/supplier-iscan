# Frontend development image: the Vite dev server on port 5173. No secret and no data file is
# copied in.
FROM node:24.22.1-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    CI=true

# pnpm through Corepack, at the version and hash pinned in package.json (never npm install).
RUN corepack enable pnpm \
    && mkdir /app \
    && chown node:node /app

USER node
WORKDIR /app

# Dependencies from the committed lockfile, without changing it.
COPY --chown=node:node package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY --chown=node:node . .

# Listens on all container interfaces (vite.config.ts); the host publishes it on 127.0.0.1 only.
EXPOSE 5173
CMD ["pnpm", "dev"]
