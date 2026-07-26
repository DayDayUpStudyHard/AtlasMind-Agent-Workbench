"""MinerU integration for high quality PDF parsing.

MinerU is intentionally kept behind a provider boundary because it is heavier
than pypdf/PaddleOCR and is best deployed as an optional worker capability.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator

from app.config import settings
from app.services.document_parser_types import ParsedBlock


class MineruService:
    """Run MinerU and stream its Markdown output as parsed blocks."""

    def iter_parse_pdf(self, pdf_path: Path) -> Iterator[ParsedBlock]:
        if not settings.mineru_enabled:
            raise RuntimeError("高质量解析需要先启用 MINERU_ENABLED=true，并安装/配置 MinerU")

        output_root = Path(settings.mineru_output_dir).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        job_dir = output_root / f"{pdf_path.stem}-{int(time.time() * 1000)}"
        job_dir.mkdir(parents=True, exist_ok=True)

        command = settings.mineru_command.format(
            input=str(pdf_path),
            output=str(job_dir),
        )
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(pdf_path.parent),
                text=True,
                capture_output=True,
                timeout=None,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"MinerU 解析失败：{detail[:1000]}")

            markdown_files = sorted(job_dir.rglob("*.md"))
            if not markdown_files:
                raise RuntimeError("MinerU 未生成 Markdown 输出，请检查 MINERU_COMMAND")

            for markdown_path in markdown_files:
                text = markdown_path.read_text(encoding="utf-8", errors="ignore")
                for block in self._iter_markdown_blocks(text):
                    yield block
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def _iter_markdown_blocks(self, text: str) -> Iterator[ParsedBlock]:
        current_title = ""
        current_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                yield from self._emit_block(current_lines, current_title)
                current_title = stripped.lstrip("#").strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        yield from self._emit_block(current_lines, current_title)

    def _emit_block(self, lines: list[str], title: str) -> Iterator[ParsedBlock]:
        cleaned = "\n".join(lines).strip()
        if cleaned:
            yield ParsedBlock(cleaned, section_title=title)
