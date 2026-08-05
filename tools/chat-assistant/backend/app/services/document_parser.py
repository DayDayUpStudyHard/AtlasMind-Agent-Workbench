"""知识库文档解析与混合切片。"""
from __future__ import annotations

import logging
import importlib
import re
import shlex
import shutil
from pathlib import Path
from typing import Callable, Iterable, Iterator

from app.config import settings
from app.services.document_parser_types import Chunk, ParsedBlock
from app.services.mineru_service import MineruService
from app.services.ocr_service import OcrService

logger = logging.getLogger(__name__)


def _module_available(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _ocr_runtime_available() -> bool:
    # PaddleOCR can have a discoverable package while still failing at import
    # time when one of its native/image dependencies is missing. Import the
    # actual entry point so auto-reparse never reports a capability that will
    # fail only after a long PDF job has started.
    try:
        for name in ("fitz", "PIL", "numpy", "cv2", "paddle"):
            importlib.import_module(name)
        from paddleocr import PaddleOCR  # noqa: F401
        return True
    except Exception:
        return False


def _mineru_runtime_available() -> bool:
    command = str(settings.mineru_command or "").strip()
    executable = shlex.split(command, posix=False)[0] if command else ""
    return bool(
        _module_available("mineru")
        or _module_available("magic_pdf")
        or (executable and shutil.which(executable))
    )


_MALFORMED_NUMBER_PATTERN = re.compile(r"[:：]\s*[\\|Il]{1,3}\s*\d")
_SUSPICIOUS_PARTY_PATTERN = re.compile(
    r"(?:[A-Za-z0-9\\]{1,6}|[叩印])方|[甲乙][A-Za-z0-9\\]{1,4}方",
    re.IGNORECASE,
)
_EMBEDDED_LATIN_PATTERN = re.compile(
    r"(?<=[\u4e00-\u9fff])\s+[A-Za-z\\][A-Za-z0-9\\:;']{0,4}\s+(?=[\u4e00-\u9fff])"
)


def assess_extracted_text_quality(text: str) -> dict:
    """Estimate whether extracted PDF text is reliable enough for semantics.

    The detector is deliberately conservative: it does not rewrite evidence. It
    only identifies patterns strongly associated with broken PDF font maps or
    OCR output so callers can route the page through a better parser.
    """
    value = str(text or "")
    compact_length = len(re.sub(r"\s+", "", value))
    malformed_numbers = len(_MALFORMED_NUMBER_PATTERN.findall(value))
    suspicious_parties = len(_SUSPICIOUS_PARTY_PATTERN.findall(value))
    embedded_latin = len(_EMBEDDED_LATIN_PATTERN.findall(value))
    replacement_chars = value.count("\ufffd") + value.count("\x00")
    mojibake_markers = sum(value.count(marker) for marker in ("锛", "銆", "鐨", "闇", "瑙"))

    signals: list[dict] = []
    for name, count in (
        ("MALFORMED_NUMBER", malformed_numbers),
        ("SUSPICIOUS_PARTY", suspicious_parties),
        ("EMBEDDED_LATIN_GLYPH", embedded_latin),
        ("REPLACEMENT_CHARACTER", replacement_chars),
        ("MOJIBAKE", mojibake_markers),
    ):
        if count:
            signals.append({"type": name, "count": count})

    density_base = max(compact_length / 1000.0, 0.25)
    weighted_errors = (
        malformed_numbers * 4.0
        + suspicious_parties * 3.0
        + embedded_latin * 1.2
        + replacement_chars * 4.0
        + mojibake_markers * 2.0
    )
    score = max(0.0, min(1.0, 1.0 - weighted_errors / (18.0 * density_base)))
    severe = malformed_numbers > 0 or replacement_chars > 0 or suspicious_parties >= 2
    if severe or score < 0.62:
        level = "LOW"
    elif signals or score < 0.88:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return {
        "level": level,
        "score": round(score, 4),
        "requiresOcr": level == "LOW",
        "requiresReview": level != "HIGH",
        "signals": signals,
        "textLength": len(value),
    }


class DocumentParser:
    """解析 Markdown / TXT / PDF 为文本块。"""

    def __init__(self) -> None:
        self.last_diagnostics: dict = {}

    def parse(
        self,
        file_path: str,
        file_type: str,
        progress_callback: Callable[[int, int, bool], None] | None = None,
        parse_mode: str | None = None,
    ) -> list[ParsedBlock]:
        return list(self.iter_parse(file_path, file_type, progress_callback, parse_mode))

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
            if mode == "AUTO":
                yield from self._iter_pdf_auto(path, progress_callback)
                return
            if mode == "MINERU":
                blocks = list(MineruService().iter_parse_pdf(path))
                quality = assess_extracted_text_quality("\n".join(block.text for block in blocks))
                self.last_diagnostics = {
                    "provider": "MINERU",
                    "quality": quality,
                    "requiresReparse": quality["requiresOcr"],
                }
                yield from blocks
                return
            blocks = list(self._iter_pdf(path, progress_callback, mode))
            quality = assess_extracted_text_quality("\n".join(block.text for block in blocks))
            self.last_diagnostics = {
                "provider": mode,
                "quality": quality,
                "requiresReparse": quality["requiresOcr"],
            }
            yield from blocks
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
        force_ocr: bool = False,
        allow_disabled_ocr: bool = False,
        ocr_page_filter: set[int] | None = None,
    ) -> Iterator[ParsedBlock]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF 解析需要安装 pypdf") from exc

        ocr = OcrService() if parse_mode == "OCR" else None
        if parse_mode == "OCR" and not settings.ocr_enabled and not allow_disabled_ocr:
            raise RuntimeError("扫描 OCR 解析需要先启用 OCR_ENABLED=true")
        try:
            with path.open("rb") as file:
                reader = PdfReader(file)
                total_pages = len(reader.pages)
                ocr_pages = 0
                for page_index, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ""
                    used_ocr = False
                    should_ocr = bool(
                        ocr
                        and (
                            len(text.strip()) < settings.ocr_min_text_chars
                            or (
                                force_ocr
                                and (
                                    ocr_page_filter is None
                                    or page_index in ocr_page_filter
                                )
                            )
                        )
                    )
                    if should_ocr:
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

    def _iter_pdf_auto(
        self,
        path: Path,
        progress_callback: Callable[[int, int, bool], None] | None = None,
    ) -> Iterator[ParsedBlock]:
        fast_blocks = list(self._iter_pdf(path, progress_callback, "FAST"))
        fast_quality = assess_extracted_text_quality("\n".join(block.text for block in fast_blocks))
        attempts = [{"provider": "FAST", "quality": fast_quality}]
        selected_blocks = fast_blocks
        selected_provider = "FAST"
        selected_quality = fast_quality
        auto_reparse_attempted = False

        page_text: dict[int, list[str]] = {}
        for block in fast_blocks:
            if block.source_page:
                page_text.setdefault(block.source_page, []).append(block.text)
        suspicious_pages = {
            page
            for page, values in page_text.items()
            if assess_extracted_text_quality("\n".join(values))["requiresOcr"]
        }
        # If fast extraction produced no usable page text, this is likely a
        # scanned PDF. Let OCR inspect every page because there is no reliable
        # page-level signal to narrow the work.
        if fast_quality["requiresOcr"] and not suspicious_pages:
            suspicious_pages = None

        if fast_quality["requiresOcr"] and settings.pdf_auto_reparse:
            auto_reparse_attempted = True
            # Surface the expensive provider switch immediately. The page
            # callback uses page=0 as a stage marker, so the UI can show that
            # OCR/MinerU is being attempted while the provider initializes.
            if progress_callback:
                progress_callback(0, 1, True)
            if settings.mineru_enabled or _mineru_runtime_available():
                try:
                    mineru_blocks = list(MineruService().iter_parse_pdf(path, allow_auto=True))
                    mineru_quality = assess_extracted_text_quality(
                        "\n".join(block.text for block in mineru_blocks)
                    )
                    attempts.append({"provider": "MINERU", "quality": mineru_quality})
                    if mineru_quality["score"] > selected_quality["score"]:
                        selected_blocks = mineru_blocks
                        selected_provider = "MINERU"
                        selected_quality = mineru_quality
                except Exception as exc:
                    logger.warning("MinerU fallback failed for %s: %s", path, exc)
                    attempts.append({"provider": "MINERU", "error": str(exc)[:300]})
            else:
                attempts.append({"provider": "MINERU", "status": "UNAVAILABLE"})

        if selected_quality["requiresOcr"] and settings.pdf_auto_reparse:
            if settings.ocr_enabled or _ocr_runtime_available():
                try:
                    ocr_kwargs = {
                        "progress_callback": progress_callback,
                        "parse_mode": "OCR",
                        "force_ocr": True,
                        "allow_disabled_ocr": True,
                    }
                    if suspicious_pages is not None:
                        ocr_kwargs["ocr_page_filter"] = suspicious_pages
                    ocr_blocks = list(self._iter_pdf(path, **ocr_kwargs))
                    merged_blocks = _merge_page_blocks(
                        fast_blocks, ocr_blocks, suspicious_pages
                    )
                    ocr_quality = assess_extracted_text_quality(
                        "\n".join(block.text for block in merged_blocks)
                    )
                    attempts.append({
                        "provider": "OCR",
                        "quality": ocr_quality,
                        "pages": sorted(suspicious_pages) if suspicious_pages else "all",
                    })
                    if ocr_quality["score"] >= selected_quality["score"]:
                        selected_blocks = merged_blocks
                        selected_provider = "OCR"
                        selected_quality = ocr_quality
                except Exception as exc:
                    logger.warning("OCR fallback failed for %s: %s", path, exc)
                    attempts.append({"provider": "OCR", "error": str(exc)[:300]})
            else:
                attempts.append({"provider": "OCR", "status": "UNAVAILABLE"})

        self.last_diagnostics = {
            "provider": selected_provider,
            "quality": selected_quality,
            "attempts": attempts,
            "requiresReparse": selected_quality["requiresOcr"],
            "autoReparseEnabled": settings.pdf_auto_reparse,
            "qualityEscalated": selected_provider != "FAST",
            "autoReparseAttempted": auto_reparse_attempted,
            "qualityEscalationPages": (
                sorted(suspicious_pages) if suspicious_pages else "all"
            ) if auto_reparse_attempted and fast_quality["requiresOcr"] else [],
            "qualityEscalationStatus": (
                "ESCALATED" if selected_provider != "FAST"
                else "UNAVAILABLE" if fast_quality["requiresOcr"] and auto_reparse_attempted
                else "NOT_REQUIRED"
            ),
            "recommendedProvider": "MINERU_OR_OCR" if selected_quality["requiresOcr"] else selected_provider,
        }
        yield from selected_blocks
    def _normalize_pdf_parse_mode(self, parse_mode: str | None) -> str:
        mode = (parse_mode or settings.pdf_parse_provider or "auto").strip().upper()
        if mode == "AUTO":
            return "AUTO"
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


def _merge_page_blocks(
    original: list[ParsedBlock],
    replacement: list[ParsedBlock],
    page_filter: set[int] | None,
) -> list[ParsedBlock]:
    """Replace only OCR-targeted pages while retaining the fast text elsewhere."""
    if page_filter is None:
        return replacement or original
    replacement_pages = {block.source_page for block in replacement if block.source_page}
    if not replacement_pages:
        return original

    original_by_page: dict[int, list[ParsedBlock]] = {}
    replacement_by_page: dict[int, list[ParsedBlock]] = {}
    unpaged: list[ParsedBlock] = []
    for block in original:
        if block.source_page:
            original_by_page.setdefault(block.source_page, []).append(block)
        else:
            unpaged.append(block)
    for block in replacement:
        if block.source_page:
            replacement_by_page.setdefault(block.source_page, []).append(block)

    merged: list[ParsedBlock] = []
    seen_pages: set[int] = set()
    for block in original:
        page = block.source_page
        if not page:
            continue
        if page in seen_pages:
            continue
        seen_pages.add(page)
        merged.extend(
            replacement_by_page.get(page, original_by_page.get(page, []))
            if page in page_filter
            else original_by_page.get(page, [])
        )
    for page in sorted(replacement_pages - seen_pages):
        merged.extend(replacement_by_page[page])
    merged.extend(unpaged)
    return merged


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
