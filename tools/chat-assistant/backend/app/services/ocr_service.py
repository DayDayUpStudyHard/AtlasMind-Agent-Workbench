"""OCR provider facade for scanned PDF pages.

The first implementation uses local PaddleOCR. Cloud OCR settings are reserved
so production deployments can switch providers without changing the parser API.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class OcrService:
    """Run OCR for page images rendered from PDF files."""

    def __init__(self) -> None:
        self.provider = settings.ocr_provider
        self._engine: Any | None = None
        self._pdf_document: Any | None = None
        self._pdf_path: str | None = None

    def recognize_pdf_page(self, pdf_path: Path, page_index: int) -> str:
        """Recognize a 1-based PDF page and return plain text."""
        if self.provider == "paddle":
            return self._recognize_with_paddle(pdf_path, page_index)
        if self.provider == "cloud":
            raise RuntimeError(
                "云 OCR 接口已预留配置，但当前版本尚未接入具体厂商；请先使用 OCR_PROVIDER=paddle"
            )
        raise RuntimeError(f"不支持的 OCR_PROVIDER: {self.provider}")

    def close(self) -> None:
        if self._pdf_document is not None:
            self._pdf_document.close()
            self._pdf_document = None
            self._pdf_path = None

    def _recognize_with_paddle(self, pdf_path: Path, page_index: int) -> str:
        engine = self._get_paddle_engine()
        image = self._render_pdf_page(pdf_path, page_index)
        image_array = np.array(image)
        if hasattr(engine, "ocr"):
            try:
                result = engine.ocr(image_array, cls=True)
            except TypeError:
                result = engine.ocr(image_array)
        elif hasattr(engine, "predict"):
            result = engine.predict(input=image_array)
        else:
            raise RuntimeError("当前 PaddleOCR 版本未暴露 ocr/predict 调用接口")
        lines = self._extract_text_lines(result)
        return "\n".join(line for line in lines if line).strip()

    def _get_paddle_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "OCR 已启用，但缺少 PaddleOCR。请在 tools/chat-assistant/backend 中安装："
                "pip install -r requirements-ocr.txt"
            ) from exc

        kwargs = {"lang": settings.ocr_lang, "use_angle_cls": True}
        try:
            self._engine = PaddleOCR(show_log=False, **kwargs)
        except (TypeError, ValueError):
            self._engine = PaddleOCR(**kwargs)
        return self._engine

    def _render_pdf_page(self, pdf_path: Path, page_index: int) -> Any:
        try:
            import fitz
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "OCR 已启用，但缺少 PyMuPDF/Pillow。请在 tools/chat-assistant/backend 中安装："
                "pip install -r requirements-ocr.txt"
            ) from exc

        matrix_scale = max(settings.ocr_render_dpi, 72) / 72
        document = self._get_pdf_document(pdf_path)
        page = document.load_page(page_index - 1)
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(matrix_scale, matrix_scale),
            alpha=False,
        )
        return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")

    def _get_pdf_document(self, pdf_path: Path) -> Any:
        normalized_path = str(pdf_path)
        if self._pdf_document is not None and self._pdf_path == normalized_path:
            return self._pdf_document
        self.close()
        import fitz

        self._pdf_document = fitz.open(normalized_path)
        self._pdf_path = normalized_path
        return self._pdf_document

    def _extract_text_lines(self, result: Any) -> list[str]:
        lines: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, str):
                text = node.strip()
                if text:
                    lines.append(text)
                return
            if isinstance(node, dict):
                for key in ("text", "rec_text", "label", "rec_texts"):
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        lines.append(value.strip())
                for value in node.values():
                    visit(value)
                return
            if isinstance(node, (list, tuple)):
                if (
                    len(node) >= 2
                    and isinstance(node[0], str)
                    and isinstance(node[1], (float, int))
                ):
                    text = node[0].strip()
                    if text:
                        lines.append(text)
                    return
                for item in node:
                    visit(item)

        visit(result)
        return lines
