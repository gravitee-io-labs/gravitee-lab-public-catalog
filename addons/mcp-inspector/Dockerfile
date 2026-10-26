# MCPJam Inspector, from its npm package: the build that runs is the one published, without building its sources
FROM node:24-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53

ARG MCPJAM_VERSION

# npm stays, for the STDIO servers an inspector starts with npx, at a release newer than the one Node bundles: what the bundled
# npm carries (undici, brace-expansion) would stay in the image unpatched
ARG NPM_VERSION=12.2.1

# No browser download for the widget previews, and no local terminal (node-pty, optional): the add-on turns both off
RUN npm install -g "npm@${NPM_VERSION}" \
    && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install -g --omit=optional "@mcpjam/inspector@${MCPJAM_VERSION}" \
    && npm cache clean --force \
    && mkdir -p /home/node/.mcpjam && chown node:node /home/node/.mcpjam

COPY ollama-forward.js /opt/ollama-forward.js

# Listens on 0.0.0.0 and opens no browser, as in MCPJam's own image
ENV NODE_ENV=production DOCKER_CONTAINER=true
USER node
WORKDIR /home/node
EXPOSE 6274
CMD ["sh", "-c", "node /opt/ollama-forward.js & exec inspector"]
