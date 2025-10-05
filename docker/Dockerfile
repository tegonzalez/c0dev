# Base stage with system dependencies
FROM oven/bun:latest AS base

# Install system dependencies once for both stages
RUN apt update && apt install -y \
    build-essential \
    cmake \
    curl \
    git \
    libssl-dev \
    tzdata

# Rename bun user to dev (keeping same UID/GID)
RUN usermod -l dev bun && groupmod -n dev bun && usermod -d /home/dev -m dev

WORKDIR /home/dev
RUN rmdir app

# Tools builder stage
FROM base AS tools-builder

# Set up dev user
USER dev
WORKDIR /home/dev

# uv installs in ~/.local/
RUN curl -fsSL https://astral.sh/uv/install.sh | sh

# cursor CLI installs in ~/.local/
RUN curl -fsSL https://cursor.com/install | bash

# factory.ai droid installs in ~/.local/
RUN curl -fsSL https://app.factory.ai/cli | sh

# graph-code (code-graph-rag) installs in ~/.local/
WORKDIR /home/dev/.local/shared/
RUN mkdir code-graph-rag
WORKDIR /home/dev/.local/shared/code-graph-rag
RUN git init
RUN git fetch --depth=1 https://github.com/vitali87/code-graph-rag.git 0037ad482657995048540497db14776a2371c21f
RUN git checkout FETCH_HEAD
RUN ~/.local/bin/uv sync --extra treesitter-full
RUN <<EOF cat >> .env
# code-graph-rag env uses local ollama
LOCAL_MODEL_ENDPOINT=http://host.docker.internal:11434/v1
LOCAL_ORCHESTRATOR_MODEL_ID=gpt-oss:20b
LOCAL_CYPHER_MODEL_ID=gpt-oss:20b
LOCAL_MODEL_API_KEY=ollama
EOF
RUN make build-grammars
RUN . ".venv/bin/activate" && python3 build_binary.py
# graph-code-linux-arm64
RUN cp dist/* ../../bin/graph-code
WORKDIR /home/dev

# Install rustup and cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/home/dev/.cargo/bin:$PATH"
RUN rustup target add wasm32-unknown-unknown

# Install additional cargo tools
RUN cargo install --git https://github.com/sharkdp/fd --rev v10.3.0
# RUN cargo install --git https://github.com/BurntSushi/ripgrep --rev 14.1.1
RUN cargo install --locked ripgrep
# RUN cargo install --git https://github.com/ast-grep/ast-grep.git --rev 0.39.4 ast-grep
RUN cargo install --locked ast-grep
#RUN cargo install --git https://github.com/zellij-org/zellij.git --rev v0.43.1
RUN cargo install --locked zellij
RUN cargo install --locked cargo-cache
RUN cargo cache --remove-dir registry

# Final stage
FROM base

RUN apt install -y \
    locales procps \
    bc fzf jq yq \
    iproute2 iputils-ping net-tools socat netcat-traditional \
    tmux vim \
    wget bat btop

# && rm -rf /var/lib/apt/lists/*

# Install global bun packages
RUN bun i -g opencode-ai@latest
RUN bun i -g @openai/codex@latest
RUN bun i -g @anthropic-ai/claude-code@latest
# > 300s WTAF??
# RUN bun i -g @google/gemini-cli@latest

# errata: handle bun -g installing as local user garbage
RUN chmod +rx /root

# Set the locale
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Set timezone (default to Los Angeles, can be overridden with TZ env var)
ARG TZ=America/Los_Angeles
ENV TZ=${TZ}
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Expose ports
# Codex server
EXPOSE 1455
# dev http
EXPOSE 3000

# Copy entrypoint script before switching user
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set up dev user
USER dev
WORKDIR /home/dev

# Add activation to profile
RUN echo 'if [ -n "$BASH_VERSION" ]; then . "$HOME/bin/activate"; fi' >> ~/.profile

# Ensure bash is available and set proper shell
ENV SHELL=/bin/bash

# Use entrypoint script that handles both interactive and daemon modes
#ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
ENTRYPOINT [""]
