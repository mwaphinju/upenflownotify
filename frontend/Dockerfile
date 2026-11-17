FROM node:22-alpine AS base
WORKDIR /web
COPY package*.json ./
RUN npm ci

# Local development target (docker-compose's default): live-reloading Vite dev server.
# Vite's dev server is not designed for production use — see the `prod` stage below.
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM base AS build
COPY . .
RUN npm run build

# Production target: static build served by nginx with security headers and SPA fallback.
# Build with: docker build --target prod -t upenflow-notify-web:prod ./frontend
FROM nginx:1.27-alpine AS prod
COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
