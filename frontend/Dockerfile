# ---- Build stage ----
FROM node:20-alpine AS build
WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Build the SPA.
COPY . .
RUN npm run build

# ---- Serve stage ----
FROM nginx:alpine AS serve

# SPA + /api reverse-proxy config (proxies to the `backend` compose service).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
