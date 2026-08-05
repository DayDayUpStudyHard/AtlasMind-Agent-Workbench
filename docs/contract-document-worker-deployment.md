# Contract Document Worker Deployment

This project parses contract files on the server side. Browsers only upload
files; the Python AI service reads the saved file and performs parsing,
chunking, embedding, indexing, timeline extraction, and intake extraction.

## Supported Formats

- `.txt`, `.md`: parsed as text.
- `.pdf`: parsed by the PDF pipeline, with optional MinerU/OCR support.
- `.docx`: parsed natively with `python-docx`.
- `.doc`: converted to `.docx` with LibreOffice, then parsed with `python-docx`.

## Docker Deployment

`tools/chat-assistant/backend/Dockerfile` installs:

- LibreOffice / Writer, for `.doc` to `.docx` conversion.
- Noto CJK fonts, for Chinese contract text rendering/conversion.
- PaddleOCR, OpenCV and PDF rendering dependencies, for automatic PDF quality
  escalation when the original text layer is malformed.
- Python dependencies from `requirements.txt`.

The PDF parser runs `pypdf` first. When its quality detector finds broken
characters or malformed numbers, it automatically tries MinerU when configured
and then PaddleOCR when available. The selected provider and attempts are
stored in the internal parse diagnostics; the user-facing timeline keeps the
candidate date and marks it as potentially inaccurate instead of hiding it.

`docker-compose.yml` now runs `ai-service` and mounts the same `upload_data`
volume used by `agent-server`:

```text
agent-server writes /upload/... -> upload_data
ai-service reads /app/upload/... -> parses document -> writes MySQL/ES results
```

Start production-style services with:

```bash
docker compose up -d --build
```

The Java backend calls the Python service through:

```env
CHAT_ASSISTANT_URL=http://ai-service:18088
```

## Required Environment

Set these in `.env` or the deployment platform:

```env
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
EMBEDDING_DIM=2560

MYSQL_ROOT_PASSWORD=...
CHAT_ASSISTANT_TOKEN=
```

## Local Development

If you run Python directly on Windows with `python run.py`, `.doc` parsing
requires local LibreOffice. Either install LibreOffice and add `soffice` to
`PATH`, or set:

```powershell
$env:LIBREOFFICE_PATH='C:\Program Files\LibreOffice\program\soffice.exe'
```

This requirement applies only to the machine running the Python worker. It does
not apply to end users' browsers.
