FROM python:3.12-slim

ARG GIT_SHA=unknown
LABEL git.sha=$GIT_SHA

# anthropic is retained though gemma is the default reasoner: opus stays
# selectable so it can be enabled later with an API key and no code change.
# av: decode/trim the V2V conditioning clip (STORY_018). The wheel bundles
# ffmpeg, so no system packages are needed — and it is the same library the
# engine decodes with, so our frame counts match its own exactly.
RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]==0.32.*" \
    httpx==0.28.* python-multipart==0.0.20 anthropic av==18.0.*

WORKDIR /app
COPY server.py upsampler.py job_logger.py video.py ./

EXPOSE 8002
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002"]
