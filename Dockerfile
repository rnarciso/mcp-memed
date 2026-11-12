FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --uid 10001 --create-home app && mkdir -p /data && chown app /data

USER app
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz').read()==b'ok' else 1)"
ENTRYPOINT ["memed-mcp"]
CMD ["serve"]
