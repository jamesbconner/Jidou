# ============================================================
# Jidou Frontend - React SPA via Nginx
# ============================================================

# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/nginx.conf.template

# Expose port 80 (mapped to 3100 in docker-compose)
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:80/ || exit 1

# Substitute only $JIDOU_API_KEY at startup so nginx variables ($host, $uri,
# etc.) are left intact, then start nginx in the foreground.
CMD ["/bin/sh", "-c", "envsubst '$JIDOU_API_KEY' < /etc/nginx/nginx.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
