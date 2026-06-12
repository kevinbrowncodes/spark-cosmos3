FROM python:3.12-slim

RUN pip install --no-cache-dir docker==7.1.0

WORKDIR /app
COPY server.py .

EXPOSE 8001
CMD ["python", "-u", "server.py"]
