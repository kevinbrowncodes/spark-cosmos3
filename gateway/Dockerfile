FROM python:3.12-slim

RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]==0.32.*" \
    httpx==0.28.* python-multipart==0.0.20 anthropic

WORKDIR /app
COPY server.py upsampler.py ./

EXPOSE 8002
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002"]
