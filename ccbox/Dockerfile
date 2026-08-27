# ccbox image — adapted from anthropics/claude-code .devcontainer (node:22 base, node user, egress firewall)
FROM node:22
ARG TZ=UTC
ENV TZ="$TZ"
RUN apt-get update && apt-get install -y --no-install-recommends \
  less git procps sudo fzf man-db unzip gnupg2 gh iptables ipset iproute2 dnsutils aggregate jq nano vim \
  tmux curl ca-certificates python3 python3-venv build-essential ripgrep \
  && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /usr/local/share/npm-global && chown -R node:node /usr/local/share
RUN mkdir -p /commandhistory && touch /commandhistory/.bash_history && chown -R node /commandhistory
RUN mkdir -p /workspace /home/node/.claude /etc/ccbox && chown -R node:node /workspace /home/node/.claude
ENV DEVCONTAINER=true
ENV NODE_OPTIONS=--max-old-space-size=4096
ENV CLAUDE_CONFIG_DIR=/home/node/.claude
ENV HISTFILE=/commandhistory/.bash_history
ENV EDITOR=nano VISUAL=nano
WORKDIR /workspace
USER node
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}
COPY --chown=node:node tmux.conf /home/node/.tmux.conf
COPY init-firewall.sh entrypoint.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh /usr/local/bin/entrypoint.sh && \
  echo "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && chmod 0440 /etc/sudoers.d/node-firewall
USER node
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
