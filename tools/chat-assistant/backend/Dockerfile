# Use a mainland-accessible mirror by default; deployments can override this
# with --build-arg PYTHON_BASE_IMAGE=python:3.12-slim when Docker Hub is reachable.
ARG PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    UPLOAD_PATH=/app/upload \
    LIBREOFFICE_PATH=/usr/bin/soffice

WORKDIR /app

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
            -e 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
            -e 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
            /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
            -e 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
            /etc/apt/sources.list; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    fonts-noto-cjk \
    fontconfig \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-graph.txt ./
# sentence-transformers is used for the optional local memory index. Install
# the CPU wheel first so pip does not resolve the default CUDA-enabled torch
# distribution on hosts without an NVIDIA runtime.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.7.1+cpu" \
    && pip install --no-cache-dir -r requirements.txt

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
