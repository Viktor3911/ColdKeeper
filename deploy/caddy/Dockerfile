# Reverse proxy image: the built frontend as static files + /api to the backend, TLS by domain.
FROM node:22.21.1-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.10.2-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /web/dist /srv
