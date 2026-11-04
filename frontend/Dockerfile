# The app in a browser (phone, tablet...): nginx serves the built interface and passes
# /api on to the backend, so the page and the API share one address

# The built files are the same on every architecture: build them once, natively
FROM --platform=$BUILDPLATFORM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS build
# Built from the repo root: ../shared (API types) sits next to frontend/
WORKDIR /web/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY shared /web/shared
COPY frontend .
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/frontend/dist /usr/share/nginx/html
EXPOSE 80
