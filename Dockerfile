# The SmolVM image: one OCI image = TerminusDB server + the Python engine + Vibe CLI.
# Boot it with:  smolvm --image <this image saved via `docker save`>
# (smolvm boots local container images as micro-VMs; no daemon inside the VM.)
# v12 + default storage path per terminusdb.com/llms.txt (see docs/research/deps-log.md)
FROM terminusdb/terminusdb-server:v12.1.0-rc2

ENV TERMINUSDB_SERVER_DB_PATH=/app/terminusdb/storage \
    TERMINUSDB_ADMIN_PASS=root \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

# Latest stable Python via uv (standalone build), plus the Vibe CLI (the
# human-facing LLM surface). Mistral Large 4 via the mistral provider; the key
# arrives at runtime (host-side secret / env), never baked in.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN uv python install 3.14 && uv venv /opt/venv --python 3.14 \
    && uv tool install mistral-vibe
ENV PATH="/opt/venv/bin:/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
# pydantic-ai = the programmatic LLM backend (sensing). Build-time egress is
# the host's; at runtime the only egress is api.mistral.ai (the mistral provider).
RUN uv pip install -e .

COPY .vibe/ /app/.vibe/

EXPOSE 6363

# Start the store, then keep the VM alive for exec'd commands
# (smolvm exec / the engine CLI). The engine talks to 127.0.0.1:6363 in-VM.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
