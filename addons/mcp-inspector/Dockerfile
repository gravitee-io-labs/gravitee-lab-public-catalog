# MCPJam Inspector, from its npm package: the build that runs is the one published, without building its sources
FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f

ARG MCPJAM_VERSION

# No browser download for the widget previews, and no local terminal (node-pty, optional): the add-on turns both off
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install -g --omit=optional "@mcpjam/inspector@${MCPJAM_VERSION}" \
    && npm cache clean --force \
    && mkdir -p /home/node/.mcpjam && chown node:node /home/node/.mcpjam

COPY ollama-forward.js /opt/ollama-forward.js

# Listens on 0.0.0.0 and opens no browser, as in MCPJam's own image
ENV NODE_ENV=production DOCKER_CONTAINER=true
USER node
WORKDIR /home/node
EXPOSE 6274
CMD ["sh", "-c", "node /opt/ollama-forward.js & exec inspector"]
