FROM mcr.microsoft.com/playwright:v1.61.1-noble

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends x11vnc novnc websockify openbox \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/frontend /data/profiles \
    && chown -R ubuntu:ubuntu /app /data

COPY infra/sri-importer/package*.json /app/frontend/
WORKDIR /app/frontend
RUN npm ci --omit=dev --ignore-scripts && npm audit --omit=dev --audit-level=high
COPY --chown=ubuntu:ubuntu scripts/*.mjs /app/scripts/
COPY --chown=ubuntu:ubuntu infra/sri-importer/*.mjs /app/infra/sri-importer/

USER ubuntu
ENV DISPLAY=:99 \
    IAERP_SRI_PROFILE_ROOT=/data/profiles \
    IAERP_SRI_ACCOUNTS_FILE=/run/secrets/sri-accounts.json \
    TZ=America/Guayaquil
WORKDIR /app
CMD ["node", "infra/sri-importer/server.mjs"]
