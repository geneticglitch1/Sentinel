# sentinel-agent: the Claude Agent SDK app + dashboard API (runs on 192.168.1.217).
# Bundles Node + the `claude` CLI because claude-agent-sdk drives it under the hood.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates openssh-client gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY sentinel ./sentinel
RUN pip install .

# Audit DB lives on a mounted volume so the dashboard can read it.
ENV SENTINEL_AUDIT_DB=/data/audit.db
VOLUME ["/data"]
EXPOSE 8799

CMD ["sentinel", "serve", "--host", "0.0.0.0", "--port", "8799"]
