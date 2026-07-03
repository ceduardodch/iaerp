FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/api/v1
ARG VITE_AUTH_MODE=keycloak
ARG VITE_KEYCLOAK_URL
ARG VITE_KEYCLOAK_REALM=iaerp
ARG VITE_KEYCLOAK_CLIENT_ID=iaerp-web
ENV VITE_API_URL=$VITE_API_URL \
    VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL \
    VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM \
    VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
