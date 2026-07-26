"""知识库文档解析与混合切片。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Iterator

from app.config import settings
from app.services.document_parser_types import Chunk, ParsedBlock
from app.services.mineru_service import MineruService
from app.services.ocr_service import OcrService


class DocumentParser:
    """解析 Markdown / TXT / PDF 为文本块。"""

    def parse(self, file_path: str, file_type: str) -> list[ParsedBlock]:
        return list(self.iter_parse(file_path, file_type))

    def iter_parse(
        self,
        file_path: str,
        file_type: str,
        progress_callback: Callable[[int, int, bool], None] | None = None,
        parse_mode: str | None = None,
    ) -> Iterator[ParsedBlock]:
        path = Path(file_path)
        normalized = file_type.upper()
        if normalized == "MD":
            yield from self._iter_markdown(path)
            return
        if normalized == "TXT":
            yield from self._iter_txt(path)
            return
        if normalized == "PDF":
            mode = self._normalize_pdf_parse_mode(parse_mode)
            if mode == "MINERU":
                yield from MineruService().iter_parse_pdf(path)
                return
            yield from self._iter_pdf(path, progress_callback, mode)
            return
        raise ValueError(f"unsupported file type: {file_type}")

    def _parse_markdown(self, path: Path) -> list[ParsedBlock]:
        return list(self._iter_markdown(path))

    def _iter_markdown(self, path: Path) -> Iterator[ParsedBlock]:
        current_title = ""
        current_lines: list[str] = []

        with path.open("r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                line = line.rstrip("\n")
                heading = re.match(r"^(#{1,6})\s+(.+)$", line)
                if heading:
                    yield from self._iter_block("\n".join(current_lines), current_title)
                    current_title = heading.group(2).strip()
                    current_lines = [line]
                else:
                    current_lines.append(line)
        yield from self._iter_block("\n".join(current_lines), current_title)

    def _parse_txt(self, path: Path) -> list[ParsedBlock]:
        return list(self._iter_txt(path))

    def _iter_txt(self, path: Path) -> Iterator[ParsedBlock]:
        current_lines: list[str] = []
        with path.open("r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                if line.strip():
                    current_lines.append(line.rstrip("\n"))
                    continue
                if current_lines:
                    yield ParsedBlock("\n".join(current_lines).strip())
                    current_lines = []
        if current_lines:
            yield ParsedBlock("\n".join(current_lines).strip())

    def _parse_pdf(self, path: Path) -> list[ParsedBlock]:
        return list(self._iter_pdf(path))

    def _iter_pdf(
        self,
        path: Path,
        progress_callback: Callable[[int, int, bool], None] | None = None,
        parse_mode: str = "OCR",
    ) -> Iterator[ParsedBlock]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF 解析需要安装 pypdf") from exc

        ocr = OcrService() if parse_mode == "OCR" else None
        if parse_mode == "OCR" and not settings.ocr_enabled:
            raise RuntimeError("扫描 OCR 解析需要先启用 OCR_ENABLED=true")
        try:
            with path.open("rb") as file:
                reader = PdfReader(file)
                total_pages = len(reader.pages)
                ocr_pages = 0
                for page_index, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ""
                    used_ocr = False
                    if ocr and len(text.strip()) < settings.ocr_min_text_chars:
                        if settings.ocr_max_pages > 0 and ocr_pages >= settings.ocr_max_pages:
                            raise RuntimeError(
                                f"OCR 页数超过 OCR_MAX_PAGES={settings.ocr_max_pages}，请调高上限或拆分文档"
                            )
                        used_ocr = True
                        ocr_pages += 1
                        text = ocr.recognize_pdf_page(path, page_index)

                    if progress_callback:
                        progress_callback(page_index, total_pages, used_ocr)

                    for part in re.split(r"\n\s*\n", text):
                        cleaned = part.strip()
                        if cleaned:
                            yield ParsedBlock(cleaned, source_page=page_index)
        finally:
            if ocr:
                ocr.close()

    def _normalize_pdf_parse_mode(self, parse_mode: str | None) -> str:
        mode = (parse_mode or settings.pdf_parse_provider or "auto").strip().upper()
        if mode == "AUTO":
            return "OCR" if settings.ocr_enabled else "FAST"
        if mode in {"PYPDF", "TEXT", "FAST"}:
            return "FAST"
        if mode in {"OCR", "PADDLE"}:
            return "OCR"
        if mode in {"MINERU", "ADVANCED"}:
            return "MINERU"
        raise RuntimeError(f"不支持的 PDF_PARSE_PROVIDER/parseMode: {parse_mode}")

    def _append_block(self, blocks: list[ParsedBlock], text: str, title: str) -> None:
        cleaned = text.strip()
        if cleaned:
            blocks.append(ParsedBlock(cleaned, section_title=title))

    def _iter_block(self, text: str, title: str) -> Iterator[ParsedBlock]:
        cleaned = text.strip()
        if cleaned:
            yield ParsedBlock(cleaned, section_title=title)


class HybridChunker:
    """标题/段落优先，固定长度兜底，保留 overlap。"""

    def __init__(self, chunk_size: int = 1000, overlap: int = 150):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, blocks: Iterable[ParsedBlock]) -> list[Chunk]:
        return list(self.iter_chunks(blocks))

    def iter_chunks(self, blocks: Iterable[ParsedBlock]) -> Iterator[Chunk]:
        for block in blocks:
            text = self._normalize(block.text)
            if len(text) <= self.chunk_size:
                yield Chunk(text, block.section_title, block.source_page)
                continue

            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                yield Chunk(text[start:end], block.section_title, block.source_page)
                if end >= len(text):
                    break
                start = max(end - self.overlap, start + 1)

    def _normalize(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)
