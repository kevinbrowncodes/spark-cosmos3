# Flow UI sidecar (EPIC_002 / STORY_023). Build context is the repo root so the
# test stage can see pytest.ini and .coveragerc; the root .dockerignore
# whitelists only flow/ and those two files.
FROM python:3.12-slim AS base

ARG FLOW_VERSION=v0.1.0
ARG GIT_SHA=unknown
LABEL git.sha=$GIT_SHA flow.version=$FLOW_VERSION

# ffmpeg: poster frames for video thumbnails (the UI renders thumbnails in
# <img>, so a video body would be a broken tile). git: pip installs
# flow-protocol straight from the flow repo tag. curl: the UI tarball.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# One pin, two artefacts: the protocol package and the UI bundle are released
# together under the same tag and must never disagree.
RUN pip install --no-cache-dir \
    "flow-protocol[server] @ git+https://github.com/kevinbrowncodes/flow@${FLOW_VERSION}#subdirectory=protocol/python"
# The release tarball is flat (tar -C dist .), so it unpacks straight in.
RUN mkdir -p /app/flow-ui \
 && curl -fsSL "https://github.com/kevinbrowncodes/flow/releases/download/${FLOW_VERSION}/flow-ui-${FLOW_VERSION}.tar.gz" \
    | tar -xz -C /app/flow-ui

WORKDIR /app
COPY flow/__init__.py flow/gateway.py flow/app.py ./flow/

# The suite runs at build time with the coverage gate: a red suite never
# becomes an image. The runtime stage copies the marker to force this stage.
FROM base AS test
COPY pytest.ini .coveragerc ./
COPY flow/requirements-test.txt ./flow/
RUN pip install --no-cache-dir -r flow/requirements-test.txt
COPY flow/tests ./flow/tests
RUN python -m pytest flow/tests -q --cov=flow --cov-fail-under=95 && touch /app/.tests-passed

FROM base AS runtime
COPY --from=test /app/.tests-passed /app/.tests-passed
EXPOSE 8003
CMD ["uvicorn", "flow.app:build_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
