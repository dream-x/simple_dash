FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    SUBNETS= \
    SCAN_INTERVAL=60 \
    PORT=8080

WORKDIR /app
COPY generate_dashboard.py serve_dashboard.py dashboard_config.json ports_catalog.json docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT', '8080'), timeout=2).read(1)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
