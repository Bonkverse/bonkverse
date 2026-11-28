# Room service for room-code sign-in (docs/adr/0026). Its own Railway
# service, private to Railway's network; Bonkverse calls it with ROOMBOT_TOKEN.
FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY src ./src
COPY certs ./certs

# bonk.io's room servers send an incomplete TLS chain (no intermediate).
# Trust the missing Sectigo intermediate instead of turning verification off.
ENV NODE_ENV=production \
    NODE_EXTRA_CA_CERTS=/app/certs/sectigo-public-server-authentication-ca-dv-r36.pem

USER node
EXPOSE 8080
CMD ["node", "src/index.mjs"]
