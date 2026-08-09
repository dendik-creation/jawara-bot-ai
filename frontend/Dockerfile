FROM oven/bun:1-alpine

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# NEXT_PUBLIC_* is inlined into the client bundle at build time, so these must be
# build args — a runtime `environment:` entry never reaches the browser.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

COPY . .
RUN bun run build

CMD ["bun", "run", "start"]
