# syntax=docker/dockerfile:1.7
ARG NODE_IMAGE=node:22.18.0-bookworm-slim@sha256:752ea8a2f758c34002a0461bd9f1cee4f9a3c36d48494586f60ffce1fc708e0e
FROM ${NODE_IMAGE}
ARG AGENT_BROWSER_VERSION=0.26.0
ARG MOVA_GIT_SHA=unknown
LABEL org.opencontainers.image.title="MOVA FPL isolated browser" \
      org.opencontainers.image.revision="${MOVA_GIT_SHA}"
ENV DISPLAY=:99 \
    AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium \
    AGENT_BROWSER_PROFILE=/var/lib/mova-fpl/browser-profile \
    MOVA_GIT_SHA=${MOVA_GIT_SHA}
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates chromium curl dbus-x11 fluxbox fonts-liberation novnc supervisor \
      websockify x11vnc xvfb \
 && rm -rf /var/lib/apt/lists/* \
 && npm install --global "agent-browser@${AGENT_BROWSER_VERSION}" \
 && npm cache clean --force \
 && agent-browser --version
COPY deploy/docker/supervisord-browser.conf /etc/supervisor/conf.d/mova-browser.conf
COPY deploy/docker/browser-entrypoint.sh /usr/local/bin/mova-browser-entrypoint
COPY deploy/browser/private-team-state.js /opt/mova/private-team-state.js
RUN mkdir -p /var/lib/mova-fpl/browser-profile /var/log/supervisor \
 && chown -R node:node /var/lib/mova-fpl /var/log/supervisor \
 && chmod 0444 /opt/mova/private-team-state.js \
 && chmod 0755 /usr/local/bin/mova-browser-entrypoint
USER node
EXPOSE 6080
ENTRYPOINT ["/usr/local/bin/mova-browser-entrypoint"]
CMD ["/usr/bin/supervisord","-n","-c","/etc/supervisor/conf.d/mova-browser.conf"]
