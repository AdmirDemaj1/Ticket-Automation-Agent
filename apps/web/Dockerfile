# Build context: repository root. Local dev image (Vite dev server with /api proxy).
FROM node:22-bookworm-slim
RUN npm install -g pnpm@10.33.0
WORKDIR /repo
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/web/package.json apps/web/
COPY packages/contracts packages/contracts
RUN pnpm install --frozen-lockfile --filter @mtj/web...
COPY apps/web apps/web
RUN chown -R node:node /repo
USER node
WORKDIR /repo/apps/web
EXPOSE 5173
CMD ["pnpm", "exec", "vite", "--host", "0.0.0.0"]
