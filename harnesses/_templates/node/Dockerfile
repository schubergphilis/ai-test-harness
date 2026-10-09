# build context: repo root
FROM node:22.23.3-slim AS build
WORKDIR /app
COPY harnesses/__HARNESS__/package.json harnesses/__HARNESS__/package-lock.json harnesses/__HARNESS__/tsconfig.json ./
RUN npm ci
COPY harnesses/__HARNESS__/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22.23.3-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY harnesses/__HARNESS__/package.json ./
COPY compat/fixtures/canary.json /app/canary.json
COPY compat/fixtures/scenarios /app/scenarios
COPY prompts /app/prompts
RUN chown node /app   # writable workdir (OpenShell uses it as workspace)
USER 1000
EXPOSE 8080
CMD ["node", "dist/server.js"]
