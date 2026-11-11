FROM docker.io/library/node:24-alpine3.23

ARG PI_VERSION=0.87.1
ARG SYNC_WEB_VERSION=0.1.0
RUN apk add --no-cache bash ca-certificates curl git python3 py3-pip libgcc libstdc++ openssl sqlite-libs \
    && npm install --global --ignore-scripts @earendil-works/pi-coding-agent@${PI_VERSION} \
    && mkdir -p /home/demo && chown node:node /home/demo
COPY tests/demos/messaging/agent/fetch-ledger.py /opt/demo/fetch-ledger.py
RUN python3 /opt/demo/fetch-ledger.py ${SYNC_WEB_VERSION}
COPY tools/journal-cli /opt/journal-cli
RUN python3 -m venv /opt/cli \
    && /opt/cli/bin/pip install --no-deps /opt/journal-cli
COPY tests/demos/messaging/agent /opt/demo
COPY tools/messenger/public/logic.mjs /opt/demo/message-logic.mjs
RUN find /opt/demo -type d -exec chmod 0755 {} + \
    && find /opt/demo -type f -exec chmod 0644 {} +
ENV PATH=/opt/cli/bin:/usr/local/bin:$PATH \
    HOME=/home/demo \
    PI_CODING_AGENT_DIR=/home/demo/.pi/agent \
    JOURNAL_CLI_CONFIG=/home/demo/journal-cli.json \
    SYNC_WEB_WASMER_KERNEL=/opt/ledger/kernel.wasmer
WORKDIR /home/demo
USER node
ENTRYPOINT ["python3", "/opt/demo/agent.py"]
