# The app in a browser (phone, tablet...): nginx serves the built interface and passes
# /api on to the backend, so the page and the API share one address

# The built files are the same on every architecture: build them once, natively
FROM --platform=$BUILDPLATFORM node:22-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS build
# Built from the repo root: ../shared (API types) sits next to frontend/
WORKDIR /web/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY shared /web/shared
COPY frontend .
RUN npm run build

FROM nginx:1.31-alpine@sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/frontend/dist /usr/share/nginx/html
EXPOSE 80
