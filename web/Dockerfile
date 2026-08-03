# headway-web — React/Vite frontend built to static files, served by nginx.
# Build: docker build -t headway-web web
#
# Two stages, same shape as services/ingestion/Dockerfile: the node toolchain
# never reaches the runtime image; nginx runs as the non-root `nginx` user on
# an unprivileged port (see deploy/nginx.conf).
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# LIMITATION (Vite): VITE_API_BASE_URL is baked into the bundle at BUILD
# time — changing the API origin means rebuilding this image, not restarting
# the container. Empty (the default) means same-origin requests, for
# deployments that co-host or reverse-proxy the API.
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.29-alpine-slim
# Patch base-image packages: the release gate blocks fixable vulns (see .grype.yaml policy)
RUN apk upgrade --no-cache
# --chmod: COPY preserves the HOST file's mode, and this image runs nginx
# as non-root — a restrictive mode on the checked-out file (corporate
# umask, found live on the first agency VM 2026-07-28: 13 Permission
# denied crash loop) must never decide whether the container boots.
COPY --chmod=644 deploy/nginx.conf /etc/nginx/nginx.conf
# Drop the stock server config: nginx.conf above is the whole config and the
# image entrypoint's IPv6 tweak script must not race a root-owned file.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
# ENTRYPOINT/CMD inherited from the nginx image.
