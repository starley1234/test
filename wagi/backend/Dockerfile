# WenAGI Gateway — production image (distroless-style, no deps to install)
FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
COPY package.json server.js ./
COPY src ./src
COPY public ./public
RUN mkdir -p data && addgroup -S wagi && adduser -S wagi -G wagi && chown -R wagi:wagi /app
USER wagi
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
CMD ["node", "server.js"]
