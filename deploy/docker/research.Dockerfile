# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim@sha256:4d676821dff059fd00d277ee4261ef34ea712317fed0737c03941481b5760c96

ARG CODEX_VERSION=0.144.6
RUN npm install --global --omit=dev "@openai/codex@${CODEX_VERSION}" && npm cache clean --force && groupadd --gid 10002 research && useradd --uid 10002 --gid 10002 --home-dir /home/research --create-home research

WORKDIR /opt/mova-research
COPY deploy/research/codex-worker.mjs /opt/mova-research/codex-worker.mjs
COPY deploy/research/research-brief.schema.json /opt/mova-research/research-brief.schema.json
RUN chmod 0555 /opt/mova-research/codex-worker.mjs && install -d -m 0700 -o 10002 -g 10002 /home/research/.codex /tmp/mova-research

ENV HOME=/home/research CODEX_HOME=/home/research/.codex MOVA_RESEARCH_ROOT=/research MOVA_RESEARCH_MODEL=gpt-5.4
USER 10002:10002
ENTRYPOINT ["node","/opt/mova-research/codex-worker.mjs"]
