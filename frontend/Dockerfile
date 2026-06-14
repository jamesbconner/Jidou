# ============================================================
# Jidou Frontend - React SPA via Nginx
# ============================================================

# --- Build stage: compile React SPA ---
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files first for better caching
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build for production
RUN npm run build

# --- Production stage: serve via Nginx ---
FROM nginx:alpine AS production

# Remove default nginx config and replace with ours
RUN rm /etc/nginx/conf.d/default.conf

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built SPA from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port 80 (mapped to 3100 in docker-compose)
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:80/ || exit 1

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
