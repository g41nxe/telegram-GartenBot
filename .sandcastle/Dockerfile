FROM node:22-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  python3 \
  python3-pip \
  python3-paho-mqtt \
  && rm -rf /var/lib/apt/lists/*

# Install system dependencies for Beads
RUN apt-get update && apt-get install -y \
  dpkg-dev \
  libicu72 \
  && rm -rf /var/lib/apt/lists/* \
  && ARCH_DIR=$(dpkg-architecture -qDEB_HOST_MULTIARCH) \
  && for lib in /usr/lib/$ARCH_DIR/libicu*.so.72; do \
       ln -s "$lib" "${lib%.72}.74"; \
     done

RUN curl -fsSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash

RUN corepack enable

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# Rename the base image's "node" user to "agent" and align UID/GID.
RUN groupmod -o -g $AGENT_GID node && usermod -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m -l agent node
USER ${AGENT_UID}:${AGENT_GID}

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash

# Add Claude to PATH
ENV PATH="/home/agent/.local/bin:$PATH"

WORKDIR /home/agent

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
