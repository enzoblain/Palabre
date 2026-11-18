# The app in a browser (phone, tablet...): nginx serves the built interface and passes
# /api on to the backend, so the page and the API share one address

# The built files are the same on every architecture: build them once, natively
FROM --platform=$BUILDPLATFORM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS build
# Built from the repo root: ../shared (API types) sits next to frontend/
WORKDIR /web/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY shared /web/shared
COPY frontend .
RUN npm run build

FROM nginx:1.31-alpine@sha256:fed7e14be83cbd2661a75cdc5b872d936cf155d46c327084d30b8df19ae88d72
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/frontend/dist /usr/share/nginx/html
EXPOSE 80
