FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UPLOAD_PATH=/app/upload \
    LIBREOFFICE_PATH=/usr/bin/soffice

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    fonts-noto-cjk \
    fontconfig \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-graph.txt ./
RUN pip install -r requirements.txt

# Contract PDF auto-reparse uses PaddleOCR when the extracted text layer is
# malformed. Keep this in the Worker image so a low-quality PDF is upgraded
# automatically instead of being silently accepted as normal text.
COPY requirements-ocr.txt ./
RUN pip install -r requirements-ocr.txt

COPY . .

EXPOSE 18088

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18088/api/chat/health?probe=true', timeout=5)" || exit 1

CMD ["python", "run.py"]
