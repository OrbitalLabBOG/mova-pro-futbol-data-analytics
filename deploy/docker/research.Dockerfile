# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim@sha256:4d676821dff059fd00d277ee4261ef34ea712317fed0737c03941481b5760c96

ARG CODEX_VERSION=0.144.6
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 && rm -rf /var/lib/apt/lists/* && npm install --global --omit=dev "@openai/codex@${CODEX_VERSION}" && npm cache clean --force && groupadd --gid 10002 research && useradd --uid 10002 --gid 10002 --home-dir /home/research --create-home research

WORKDIR /opt/mova-research
COPY mova_fpl/ops/research_evidence.py /opt/mova-research/research_evidence.py
COPY mova_fpl/ops/research_quality.py /opt/mova-research/research_quality.py
COPY deploy/research/evidence-tool.py /opt/mova-research/evidence-tool.py
COPY deploy/research/agent-releases.json /opt/mova-research/agent-releases.json
COPY deploy/research/codex-worker.mjs /opt/mova-research/codex-worker.mjs
COPY deploy/research/research-context.mjs /opt/mova-research/research-context.mjs
COPY deploy/research/research-normalize.mjs /opt/mova-research/research-normalize.mjs
COPY deploy/research/research-brief.schema.json /opt/mova-research/research-brief.schema.json
COPY deploy/research/decision-deliberation.schema.json /opt/mova-research/decision-deliberation.schema.json
RUN chmod 0555 /opt/mova-research/codex-worker.mjs /opt/mova-research/research-normalize.mjs && install -d -m 0700 -o 10002 -g 10002 /home/research/.codex /tmp/mova-research

ENV HOME=/home/research \
    CODEX_HOME=/home/research/.codex \
    MOVA_RESEARCH_ROOT=/research \
    MOVA_RESEARCH_MODEL=gpt-5.6-luna \
    MOVA_RESEARCH_REASONING_EFFORT=medium \
    MOVA_DELIBERATION_MODEL=gpt-5.6-terra \
    MOVA_DELIBERATION_REASONING_EFFORT=high
USER 10002:10002
ENTRYPOINT ["node","/opt/mova-research/codex-worker.mjs"]
