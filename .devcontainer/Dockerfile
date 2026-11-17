FROM node:24-bookworm-slim
ARG EOS_MCP_VERSION=0.13.1-beta
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv openssh-client git ca-certificates less \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/diagnostics \
    && /opt/diagnostics/bin/pip install --no-cache-dir PyYAML==6.0.3 \
    && npm install -g @aristanetworks/eos-mcp-server@${EOS_MCP_VERSION}
ENV PATH="/opt/diagnostics/bin:${PATH}"
WORKDIR /workspaces/EOS-MCP-Test
USER node
CMD ["sleep", "infinity"]
