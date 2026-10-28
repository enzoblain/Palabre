# The app in a browser (phone, tablet...): nginx serves the built interface and passes
# /api on to the backend, so the page and the API share one address

# The built files are the same on every architecture: build them once, natively
FROM --platform=$BUILDPLATFORM node:22-slim AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
