# Stage 1: Build Vite React application
FROM node:22-slim AS builder

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy application source code
COPY . .

# Build arguments for Vite environment variables (embedded at build time)
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_STORAGE_BUCKET
ARG VITE_FIREBASE_MESSAGING_SENDER_ID
ARG VITE_FIREBASE_APP_ID
ARG VITE_FIRESTORE_DATABASE_ID
ARG VITE_USE_EMULATOR=false

# Build production bundle to dist/
RUN npm run build

# Stage 2: Serve using Nginx
FROM nginx:alpine

ENV PORT=8080
# Tell nginx entrypoint to only substitute ${PORT} so $uri in try_files is preserved
ENV NGINX_ENVSUBST_FILTER="PORT"

# Clean default nginx site configs
RUN rm -rf /etc/nginx/conf.d/*

# Copy configuration template and built static files
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
