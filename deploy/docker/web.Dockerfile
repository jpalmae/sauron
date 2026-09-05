# syntax=docker/dockerfile:1
#
# Sauron dashboard: React build -> nginx static + reverse proxy.
#   docker build -f deploy/docker/web.Dockerfile -t sauron/web:0.1.0 .
FROM node:24-alpine AS build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM nginx:1.27-alpine
# Template procesado por envsubst (entrypoint de la imagen nginx):
# ALPR_BASIC_TOKEN se inyecta en runtime sin hornear credenciales en la imagen.
COPY deploy/docker/nginx.conf /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx/conf.d
COPY --from=build /app/dist /usr/share/nginx/html
# White-label override: mount client assets over /brand without rebuilding:
#   -v ./brand:/usr/share/nginx/html/brand:ro
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
