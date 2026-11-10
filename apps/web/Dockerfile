# Dev/CI toolchain image. Build context is the repo root; source is bind-mounted.
FROM node:22-slim
RUN npm install -g pnpm@9.15.4
ENV CI=true \
    NEXT_TELEMETRY_DISABLED=1 \
    WATCHPACK_POLLING=true
WORKDIR /repo
COPY apps/web/docker-entrypoint.sh /usr/local/bin/stylecut-web-entrypoint
RUN chmod +x /usr/local/bin/stylecut-web-entrypoint
ENTRYPOINT ["stylecut-web-entrypoint"]
CMD ["pnpm", "--filter", "web", "dev"]
