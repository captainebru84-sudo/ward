FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Confidential Space launch policy: allow container logs into Cloud Logging
LABEL "tee.launch_policy.log_redirect"="always"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY tokens.json policies.json ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
# MockDEX on Coston2 (public). WARD_SIGNER_KEY is deliberately absent:
# with no key configured the agent generates an ephemeral one inside the TEE.
ENV WARD_DEX_ADDRESS=0xe1570af51Bfc33CDaEAD58378eE15416b370279e

EXPOSE 8080
CMD ["ward-agent", "serve"]
