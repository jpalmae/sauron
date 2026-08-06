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
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# White-label override: mount client assets over /brand without rebuilding:
#   -v ./brand:/usr/share/nginx/html/brand:ro
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost/ >/dev/null || exit 1
